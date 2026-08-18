"""Bustimes API client and rule matching helpers."""
import hashlib
import json
import logging
from collections import defaultdict
import requests
from django.utils import timezone
from .models import AlertEvent, Livery, Operator, Rule, Service, Vehicle, VehicleType

LOG = logging.getLogger(__name__)
BASE_URL = "https://bustimes.org/api"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Controller bus-alerts/1.0"})


def api_get(url, params=None):
    response = SESSION.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def paged(endpoint, params=None):
    url, query = f"{BASE_URL}/{endpoint.lstrip('/')}", params or {}
    while url:
        payload = api_get(url, query)
        yield from payload.get("results", [])
        url, query = payload.get("next"), None


def upsert_type(data):
    if not data: return None
    obj, _ = VehicleType.objects.update_or_create(bustimes_id=data["id"], defaults={
        "name": data.get("name", "Unknown"), "fuel": data.get("fuel", ""), "style": data.get("style", ""),
        "double_decker": data.get("double_decker", False), "coach": data.get("coach", False), "electric": data.get("electric", False),
    })
    return obj


def upsert_livery(data):
    if not data: return None
    obj, _ = Livery.objects.update_or_create(bustimes_id=data["id"], defaults={
        "name": data.get("name", "Unknown"), "left_css": data.get("left_css", data.get("left", "")), "right_css": data.get("right_css", data.get("right", "")),
    })
    return obj


def upsert_operator(data):
    noc = data.get("noc") or data.get("id")
    return Operator.objects.update_or_create(noc=noc, defaults={"name": data.get("name", noc), "slug": data.get("slug", ""), "region_id": data.get("region_id") or "", "vehicle_mode": data.get("vehicle_mode", "bus"), "raw_data": data})[0]


def sync_operator_fleet(noc):
    operator = Operator.objects.get(noc=noc)
    rows = list(paged("vehicles/", {"withdrawn": "false", "operator": noc}))
    ids = []
    for data in rows:
        vehicle_type, livery = upsert_type(data.get("vehicle_type")), upsert_livery(data.get("livery"))
        Vehicle.objects.update_or_create(bustimes_id=data["id"], defaults={
            "slug": data.get("slug", ""), "operator": operator, "fleet_number": str(data.get("fleet_number") or ""), "fleet_code": str(data.get("fleet_code") or ""),
            "reg": data.get("reg", ""), "vehicle_type": vehicle_type, "livery": livery, "branding": data.get("branding", ""),
            "garage_name": (data.get("garage") or {}).get("name", ""), "withdrawn": data.get("withdrawn", False), "raw_data": data,
        })
        ids.append(data["id"])
    if ids: Vehicle.objects.filter(operator=operator).exclude(bustimes_id__in=ids).update(withdrawn=True)
    return len(rows)


def sync_operator_services(noc):
    operator = Operator.objects.get(noc=noc)
    rows = list(paged("services/", {"operator": noc}))
    for data in rows:
        # Operator is returned as a NOC list; preserve services whose primary operator is this NOC.
        Service.objects.update_or_create(bustimes_id=data["id"], defaults={"slug": data.get("slug", ""), "line_name": data.get("line_name", ""), "description": data.get("description", ""), "operator": operator, "mode": data.get("mode", ""), "raw_data": data})
    return len(rows)


def snapshot(rows):
    return {str(row["id"]): hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest() for row in rows}


def rule_matches_tracking(rule, item):
    vehicle_url = ((item.get("vehicle") or {}).get("url") or "").rstrip("/")
    vehicle_slug = vehicle_url.split("/")[-1]
    vehicle = Vehicle.objects.filter(operator=rule.operator, slug=vehicle_slug).select_related("vehicle_type", "livery").first()
    if not vehicle: return False
    if rule.vehicles.exists() and not rule.vehicles.filter(pk=vehicle.pk).exists(): return False
    if rule.vehicle_types.exists() and not rule.vehicle_types.filter(pk=vehicle.vehicle_type_id).exists(): return False
    if rule.liveries.exists() and not rule.liveries.filter(pk=vehicle.livery_id).exists(): return False
    if rule.fuels and (not vehicle.vehicle_type or vehicle.vehicle_type.fuel not in rule.fuels): return False
    line = (item.get("service") or {}).get("line_name", "")
    service_url = ((item.get("service") or {}).get("url") or "").rstrip("/")
    service_slug = service_url.split("/")[-1]
    if rule.services.exists() or rule.custom_lines:
        saved_service_matches = rule.services.filter(slug=service_slug).exists()
        custom_line_matches = line in rule.custom_lines
        if not (saved_service_matches or custom_line_matches): return False
    return True


def emit(rule, event_type, title, detail, payload):
    AlertEvent.objects.create(rule=rule, operator=rule.operator, severity=rule.severity, event_type=event_type, title=title, detail=detail, payload=payload)
    if rule.discord_alert and rule.discord_webhook:
        try: SESSION.post(rule.discord_webhook, json={"content": f"**{title}**\n{detail}"}, timeout=15).raise_for_status()
        except requests.RequestException: LOG.exception("Discord webhook failed for rule %s", rule.pk)
    if rule.alert_once:
        rule.active = False; rule.save(update_fields=["active", "updated_at"])


def process_tracking(operator, items):
    for rule in Rule.objects.filter(operator=operator, active=True):
        for item in items:
            if rule_matches_tracking(rule, item):
                service = item.get("service") or {}
                vehicle = item.get("vehicle") or {}
                emit(rule, "tracking", f"{vehicle.get('name', 'Vehicle')} on {service.get('line_name', 'service')}", f"Destination: {item.get('destination') or 'Unknown'}", item)


def process_inventory_changes(operator, old_vehicles, new_vehicles, old_services, new_services):
    added_vehicles = set(new_vehicles) - set(old_vehicles)
    changed_vehicles = {pk for pk, value in new_vehicles.items() if pk in old_vehicles and old_vehicles[pk] != value}
    added_services = set(new_services) - set(old_services)
    for rule in Rule.objects.filter(operator=operator, active=True):
        if rule.new_vehicle:
            for pk in added_vehicles: emit(rule, "new_vehicle", "New vehicle recorded", "A vehicle has been added to the operator fleet.", {"vehicle_id": pk})
        if rule.vehicle_change:
            for pk in changed_vehicles: emit(rule, "vehicle_change", "Vehicle details changed", "A vehicle record has changed in Bustimes.", {"vehicle_id": pk})
        if rule.new_service:
            for pk in added_services: emit(rule, "new_service", "New service recorded", "A service has been added for this operator.", {"service_id": pk})
