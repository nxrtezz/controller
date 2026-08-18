from django.db import models
from django.utils import timezone


class Operator(models.Model):
    noc = models.CharField(max_length=16, primary_key=True)
    slug = models.SlugField(max_length=120, blank=True)
    name = models.CharField(max_length=255)
    region_id = models.CharField(max_length=12, blank=True, null=True)
    vehicle_mode = models.CharField(max_length=20, default="bus")
    raw_data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self): return f"{self.name} ({self.noc})"


class VehicleType(models.Model):
    bustimes_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    fuel = models.CharField(max_length=40, blank=True)
    style = models.CharField(max_length=80, blank=True)
    double_decker = models.BooleanField(default=False)
    coach = models.BooleanField(default=False)
    electric = models.BooleanField(default=False)
    class Meta: ordering = ["name"]
    def __str__(self): return self.name


class Livery(models.Model):
    bustimes_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    left_css = models.TextField(blank=True)
    right_css = models.TextField(blank=True)
    class Meta: ordering = ["name"]
    def __str__(self): return self.name


class Service(models.Model):
    bustimes_id = models.PositiveIntegerField(unique=True)
    slug = models.SlugField(max_length=255)
    line_name = models.CharField(max_length=80)
    description = models.CharField(max_length=500, blank=True)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="services", null=True, blank=True)
    mode = models.CharField(max_length=30, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["line_name", "description"]
    def __str__(self): return f"{self.line_name} — {self.description}"


class Vehicle(models.Model):
    bustimes_id = models.PositiveIntegerField(unique=True)
    slug = models.SlugField(max_length=255)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="vehicles")
    fleet_number = models.CharField(max_length=80, blank=True)
    fleet_code = models.CharField(max_length=80, blank=True)
    reg = models.CharField(max_length=32, blank=True)
    vehicle_type = models.ForeignKey(VehicleType, null=True, blank=True, on_delete=models.SET_NULL)
    livery = models.ForeignKey(Livery, null=True, blank=True, on_delete=models.SET_NULL)
    branding = models.CharField(max_length=255, blank=True)
    garage_name = models.CharField(max_length=255, blank=True)
    withdrawn = models.BooleanField(default=False)
    raw_data = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["fleet_number", "reg"]
    def __str__(self): return f"{self.fleet_number or self.reg} — {self.reg}"


class Rule(models.Model):
    class Severity(models.TextChoices): INFO = "info", "Info"; WARNING = "warning", "Warning"; URGENT = "urgent", "Urgent"
    name = models.CharField(max_length=160)
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="rules")
    active = models.BooleanField(default=True)
    vehicles = models.ManyToManyField(Vehicle, blank=True)
    vehicle_types = models.ManyToManyField(VehicleType, blank=True)
    liveries = models.ManyToManyField(Livery, blank=True)
    fuels = models.JSONField(default=list, blank=True)
    services = models.ManyToManyField(Service, blank=True)
    custom_lines = models.JSONField(default=list, blank=True)
    new_vehicle = models.BooleanField(default=False)
    vehicle_change = models.BooleanField(default=False)
    new_service = models.BooleanField(default=False)
    website_alert = models.BooleanField(default=True)
    severity = models.CharField(max_length=12, choices=Severity.choices, default=Severity.INFO)
    discord_alert = models.BooleanField(default=False)
    discord_webhook = models.URLField(blank=True)
    quietly_log = models.BooleanField(default=False)
    alert_once = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta: ordering = ["-active", "name"]
    def __str__(self): return self.name

    @property
    def condition_summary(self):
        bits = []
        if self.vehicles.exists(): bits.append(f"{self.vehicles.count()} vehicle(s)")
        if self.vehicle_types.exists(): bits.append(f"{self.vehicle_types.count()} type(s)")
        if self.liveries.exists(): bits.append(f"{self.liveries.count()} livery/liveries")
        if self.fuels: bits.append(", ".join(self.fuels))
        if self.services.exists() or self.custom_lines: bits.append("specific service")
        if self.new_vehicle: bits.append("new vehicle")
        if self.vehicle_change: bits.append("vehicle changes")
        if self.new_service: bits.append("new service")
        return " • ".join(bits) or "Any tracked journey"


class AlertEvent(models.Model):
    rule = models.ForeignKey(Rule, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    operator = models.ForeignKey(Operator, on_delete=models.CASCADE, related_name="events")
    severity = models.CharField(max_length=12, default="info")
    event_type = models.CharField(max_length=40)
    title = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    class Meta: ordering = ["-created_at"]


class PollState(models.Model):
    operator = models.OneToOneField(Operator, on_delete=models.CASCADE, related_name="poll_state")
    vehicles_snapshot = models.JSONField(default=dict, blank=True)
    services_snapshot = models.JSONField(default=dict, blank=True)
    last_fleet_poll = models.DateTimeField(null=True, blank=True)
    last_tracking_poll = models.DateTimeField(null=True, blank=True)
