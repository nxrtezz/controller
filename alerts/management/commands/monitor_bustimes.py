import time
from django.core.management.base import BaseCommand
from django.utils import timezone
from alerts.models import Operator, PollState
from alerts.services import api_get, process_inventory_changes, process_tracking, snapshot, sync_operator_fleet, sync_operator_services

class Command(BaseCommand):
    help = "Continuously poll watched operators: live tracking every 2 minutes, inventories every 10."
    def handle(self, *args, **options):
        self.stdout.write("Controller monitor started")
        while True:
            now = timezone.now()
            for operator in Operator.objects.filter(rules__active=True).distinct():
                state, _ = PollState.objects.get_or_create(operator=operator)
                try:
                    if not state.last_tracking_poll or (now - state.last_tracking_poll).total_seconds() >= 120:
                        process_tracking(operator, api_get("https://bustimes.org/vehicles.json", {"operator": operator.noc}))
                        state.last_tracking_poll = now
                    if not state.last_fleet_poll or (now - state.last_fleet_poll).total_seconds() >= 600:
                        old_v, old_s = state.vehicles_snapshot, state.services_snapshot
                        sync_operator_fleet(operator.noc); sync_operator_services(operator.noc)
                        new_v = snapshot([v.raw_data for v in operator.vehicles.all()]); new_s = snapshot([s.raw_data for s in operator.services.all()])
                        if old_v or old_s: process_inventory_changes(operator, old_v, new_v, old_s, new_s)
                        state.vehicles_snapshot, state.services_snapshot, state.last_fleet_poll = new_v, new_s, now
                    state.save()
                except Exception as exc: self.stderr.write(f"{operator.noc}: {exc}")
            time.sleep(30)
