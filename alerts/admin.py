from django.contrib import admin
from .models import AlertEvent, Livery, Operator, PollState, Rule, Service, Vehicle, VehicleType

admin.site.register([Operator, VehicleType, Livery, Service, Vehicle, Rule, AlertEvent, PollState])
