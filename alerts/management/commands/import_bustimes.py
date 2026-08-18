from django.core.management.base import BaseCommand
from alerts.services import paged, upsert_livery, upsert_operator, upsert_type
from alerts.models import Service

class Command(BaseCommand):
    help = "Import Bustimes vehicle types, liveries, operators and services."
    def add_arguments(self, parser): parser.add_argument("--catalogue-only", action="store_true")
    def handle(self, *args, **options):
        for endpoint, func in [("vehicletypes/", upsert_type), ("liveries/", upsert_livery), ("operators/", upsert_operator)]:
            n = 0
            for row in paged(endpoint): func(row); n += 1
            self.stdout.write(f"Imported {n} {endpoint}")
        if not options["catalogue_only"]:
            n = 0
            for row in paged("services/"):
                operator = None
                if row.get("operator"):
                    operator = __import__("alerts.models", fromlist=["Operator"]).Operator.objects.filter(noc=row["operator"][0]).first()
                Service.objects.update_or_create(bustimes_id=row["id"], defaults={"slug": row.get("slug", ""), "line_name": row.get("line_name", ""), "description": row.get("description", ""), "operator": operator, "mode": row.get("mode", ""), "raw_data": row}); n += 1
            self.stdout.write(f"Imported {n} services")
