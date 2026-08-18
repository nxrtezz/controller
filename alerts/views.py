from datetime import timedelta
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from .forms import RuleForm
from .models import AlertEvent, Operator, Rule, Service, Vehicle
from .services import api_get, sync_operator_fleet, sync_operator_services, upsert_operator


@login_required
def rule_list(request):
    rules = Rule.objects.select_related("operator").annotate(event_count=Count("events"))
    return render(request, "alerts/rule_list.html", {"rules": rules})


@login_required
def rule_create(request):
    noc = request.GET.get("operator")
    catalogue_all = request.GET.get("catalogue") == "all"
    operator = Operator.objects.filter(noc=noc).first() if noc else None
    search_term, search_results = request.GET.get("search", "").strip(), []
    if search_term and not operator:
        try:
            # Fetch all operators (API ignores search parameter, so we filter client-side)
            payload = api_get("https://bustimes.org/api/operators/")
            all_results = payload.get("results", [])
            
            # Handle pagination if needed
            while payload.get("next"):
                payload = api_get(payload["next"])
                all_results.extend(payload.get("results", []))
            
            # Filter results by name or NOC (case-insensitive)
            search_term_lower = search_term.lower()
            search_results = [
                r for r in all_results 
                if search_term_lower in r.get("name", "").lower() or search_term_lower in r.get("noc", "").lower()
            ][:50]  # Limit to 50 results
        except Exception:
            messages.error(request, "Bustimes could not be reached. Please try the operator's NOC instead.")
    if request.method == "POST":
        posted_operator = Operator.objects.filter(pk=request.POST.get("operator")).first()
        form = RuleForm(request.POST, initial={"operator": posted_operator} if posted_operator else {}, catalogue_all=catalogue_all)
        if form.is_valid():
            try:
                rule = form.save(commit=False)
                if posted_operator and not rule.operator:
                    rule.operator = posted_operator
                rule.save()
                form.save_m2m()
                messages.success(request, f'Rule "{rule.name}" is now watching {rule.operator.name}.')
                return redirect("rule_list")
            except Exception as e:
                messages.error(request, f"Error saving rule: {str(e)}")
        else:
            # Form is invalid, show errors
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else: form = RuleForm(initial={"operator": operator} if operator else {}, catalogue_all=catalogue_all)
    return render(request, "alerts/rule_form.html", {"form": form, "operator": operator, "page_title": "Create rule", "catalogue_all": catalogue_all, "search_term": search_term, "search_results": search_results})
@login_required
def operator_select(request, noc):
    """Import a selected Bustimes operator and take the user straight to rule definition."""
    operator = Operator.objects.filter(noc=noc).first()
    if not operator:
        try:
            # Fetch all operators (API ignores search parameter, so we filter client-side)
            payload = api_get("https://bustimes.org/api/operators/")
            all_results = payload.get("results", [])
            
            # Handle pagination if needed
            while payload.get("next"):
                payload = api_get(payload["next"])
                all_results.extend(payload.get("results", []))
            
            # Find the specific operator by NOC
            match = next((row for row in all_results if row.get("noc") == noc), None)
            if match:
                operator = upsert_operator(match)
        except Exception:
            operator = None
    if not operator:
        messages.error(request, "That operator could not be found in Bustimes.")
        return redirect("rule_create")
    try:
        vehicles, services = sync_operator_fleet(noc), sync_operator_services(noc)
        messages.success(request, f"Imported {vehicles} vehicles and {services} routes for {operator.name}.")
    except Exception:
        messages.warning(request, f"{operator.name} was selected, but its current fleet data could not be imported. You can still create the rule.")
    return redirect(f"{reverse('rule_create')}?operator={noc}")


@login_required
def rule_edit(request, pk):
    rule = get_object_or_404(Rule, pk=pk)
    catalogue_all = request.GET.get("catalogue") == "all"
    form = RuleForm(request.POST or None, instance=rule, catalogue_all=catalogue_all)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "Rule updated."); return redirect("rule_list")
    return render(request, "alerts/rule_form.html", {"form": form, "operator": rule.operator, "page_title": "Edit rule", "catalogue_all": catalogue_all})


@login_required
def rule_toggle(request, pk):
    rule = get_object_or_404(Rule, pk=pk)
    if request.method == "POST":
        rule.active = not rule.active; rule.save(update_fields=["active", "updated_at"])
        messages.success(request, f'Rule {"activated" if rule.active else "deactivated"}.')
    return redirect(request.POST.get("next") or "rule_list")


@login_required
def rule_activity(request, pk):
    rule = get_object_or_404(Rule, pk=pk)
    now = timezone.now()
    periods = {"24 hours": now - timedelta(days=1), "7 days": now - timedelta(days=7), "31 days": now - timedelta(days=31)}
    counts = {name: rule.events.filter(created_at__gte=start).count() for name, start in periods.items()}; counts["All time"] = rule.events.count()
    events = rule.events.select_related("operator")[:100]
    return render(request, "alerts/rule_activity.html", {"rule": rule, "counts": counts, "events": events})


@login_required
def operator_list(request):
    operators = Operator.objects.filter(rules__isnull=False).distinct().annotate(vehicle_count=Count("vehicles", distinct=True), service_count=Count("services", distinct=True), rule_count=Count("rules", distinct=True))
    return render(request, "alerts/operator_list.html", {"operators": operators})


@login_required
def operator_detail(request, noc):
    operator = get_object_or_404(Operator.objects.annotate(vehicle_count=Count("vehicles", distinct=True), service_count=Count("services", distinct=True), rule_count=Count("rules", distinct=True)), noc=noc)
    tab = request.GET.get("tab", "rules")
    context = {"operator": operator, "tab": tab}
    if tab == "vehicles": context["vehicles"] = operator.vehicles.select_related("vehicle_type", "livery")
    elif tab == "routes":
        routes = defaultdict_route_data(operator)
        context["routes"] = routes
    else: context["rules"] = operator.rules.all().annotate(event_count=Count("events"))
    return render(request, "alerts/operator_detail.html", context)


def defaultdict_route_data(operator):
    routes = {}
    for service in operator.services.all(): routes.setdefault(service.line_name, {"line": service.line_name, "services": []})["services"].append(service)
    # Live events capture destinations and can reveal observed routes even if a service catalogue record is absent.
    for event in operator.events.filter(event_type="tracking")[:2000]:
        service = (event.payload or {}).get("service") or {}
        line = service.get("line_name")
        if line: routes.setdefault(line, {"line": line, "services": []})
    for route in routes.values():
        destinations = set()
        for event in operator.events.filter(event_type="tracking"):
            payload = event.payload or {}
            if ((payload.get("service") or {}).get("line_name")) == route["line"] and payload.get("destination"): destinations.add(payload["destination"])
        route["destinations"] = sorted(destinations)
    return sorted(routes.values(), key=lambda r: r["line"])


@login_required
def activity(request):
    return render(request, "alerts/activity.html", {"total_rules": Rule.objects.count(), "active_rules": Rule.objects.filter(active=True).count(), "inactive_rules": Rule.objects.filter(active=False).count(), "tracked_operators": Operator.objects.filter(rules__active=True).distinct().count(), "tracked_vehicles": Vehicle.objects.filter(operator__rules__active=True).distinct().count(), "tracked_services": Service.objects.filter(operator__rules__active=True).distinct().count(), "events": AlertEvent.objects.select_related("rule", "operator")[:100]})


@login_required
def settings_view(request): return render(request, "alerts/settings.html")


@login_required
def operator_search(request):
    term = request.GET.get("q", "").strip().lower()
    if not term: return JsonResponse({"results": []})
    try:
        # Fetch all operators (API ignores search parameter, so we filter client-side)
        payload = api_get("https://bustimes.org/api/operators/")
        all_results = payload.get("results", [])
        
        # Handle pagination if needed
        while payload.get("next"):
            payload = api_get(payload["next"])
            all_results.extend(payload.get("results", []))
        
        # Filter results by name or NOC (case-insensitive)
        filtered_results = [
            r for r in all_results 
            if term in r.get("name", "").lower() or term in r.get("noc", "").lower()
        ]
        
        # Limit to 50 results to avoid overwhelming the client
        results = filtered_results[:50]
    except Exception:
        results = []
    return JsonResponse({"results": [{"noc": r.get("noc"), "name": r.get("name"), "slug": r.get("slug")} for r in results]})


@login_required
def operator_fleet(request, noc):
    # Pull operator metadata from the public catalogue where available, then sync its selectable fleet and routes.
    operator = Operator.objects.filter(noc=noc).first()
    if not operator:
        try:
            # Fetch all operators (API ignores search parameter, so we filter client-side)
            payload = api_get("https://bustimes.org/api/operators/")
            all_results = payload.get("results", [])
            
            # Handle pagination if needed
            while payload.get("next"):
                payload = api_get(payload["next"])
                all_results.extend(payload.get("results", []))
            
            # Find the specific operator by NOC
            match = next((r for r in all_results if r.get("noc") == noc), None)
            if match: operator = upsert_operator(match)
        except Exception: pass
    if not operator: return JsonResponse({"error": "Operator was not found."}, status=404)
    try:
        vehicles, services = sync_operator_fleet(noc), sync_operator_services(noc)
    except Exception as exc: return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse({"noc": noc, "name": operator.name, "vehicles": vehicles, "services": services, "create_url": f"/rules/new/?operator={noc}"})
