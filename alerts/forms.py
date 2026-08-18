from django import forms
import json
from .models import Operator, Rule, Service, Vehicle, VehicleType, Livery


class RuleForm(forms.ModelForm):
    custom_lines_text = forms.CharField(required=False, label="Custom line names", help_text="Comma-separated; use when a route is not in the service list.")
    fuels = forms.JSONField(required=False, widget=forms.CheckboxSelectMultiple())
    
    class Meta:
        model = Rule
        fields = ["name", "operator", "vehicles", "vehicle_types", "liveries", "fuels", "services", "new_vehicle", "vehicle_change", "new_service", "website_alert", "severity", "discord_alert", "discord_webhook", "quietly_log", "alert_once"]
        widgets = {
            "vehicles": forms.SelectMultiple(attrs={"size": 7}), "vehicle_types": forms.SelectMultiple(attrs={"size": 7}),
            "liveries": forms.SelectMultiple(attrs={"size": 7}), "services": forms.SelectMultiple(attrs={"size": 7}),
            "discord_webhook": forms.URLInput(attrs={"placeholder": "https://discord.com/api/webhooks/..."}),
        }

    def __init__(self, *args, **kwargs):
        catalogue_all = kwargs.pop("catalogue_all", False)
        super().__init__(*args, **kwargs)
        operator = self.instance.operator if self.instance and self.instance.pk else None
        # If we have initial operator data, try to get the operator object
        if not operator and self.initial.get("operator"):
            try:
                operator = Operator.objects.get(pk=self.initial.get("operator"))
            except (Operator.DoesNotExist, ValueError, TypeError):
                operator = None
        if operator:
            self.fields["vehicles"].queryset = Vehicle.objects.filter(operator=operator, withdrawn=False)
            self.fields["vehicle_types"].queryset = VehicleType.objects.all() if catalogue_all else VehicleType.objects.filter(vehicle__operator=operator).distinct()
            self.fields["liveries"].queryset = Livery.objects.all() if catalogue_all else Livery.objects.filter(vehicle__operator=operator).distinct()
            self.fields["services"].queryset = Service.objects.filter(operator=operator)
            fuel_types = VehicleType.objects.all() if catalogue_all else VehicleType.objects.filter(vehicle__operator=operator)
            self.fields["fuels"].choices = [(f, f.title()) for f in fuel_types.exclude(fuel="").values_list("fuel", flat=True).distinct()]
        else:
            self.fields["vehicles"].queryset = Vehicle.objects.none(); self.fields["vehicle_types"].queryset = VehicleType.objects.none(); self.fields["liveries"].queryset = Livery.objects.none(); self.fields["services"].queryset = Service.objects.none()
        if self.instance and self.instance.pk: self.fields["custom_lines_text"].initial = ", ".join(self.instance.custom_lines)

    def clean_fuels(self):
        # Handle when fuels comes as a list from CheckboxSelectMultiple
        fuels = self.cleaned_data.get('fuels')
        if isinstance(fuels, list):
            return fuels
        elif isinstance(fuels, str):
            try:
                return json.loads(fuels)
            except json.JSONDecodeError:
                return []
        return fuels

    def clean_custom_lines_text(self): return [s.strip() for s in self.cleaned_data["custom_lines_text"].split(",") if s.strip()]

    def save(self, commit=True):
        rule = super().save(commit=False)
        rule.custom_lines = self.cleaned_data["custom_lines_text"]
        if commit: rule.save(); self.save_m2m()
        return rule
