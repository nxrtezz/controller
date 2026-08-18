from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from .models import Operator, Rule, Vehicle, VehicleType


class ControllerViewsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("controller", password="test-pass")
        self.operator = Operator.objects.create(noc="ZSIN", name="Z & S Transport")
        self.vehicle_type = VehicleType.objects.create(bustimes_id=124, name="Volvo B9TL", fuel="diesel")
        self.vehicle = Vehicle.objects.create(bustimes_id=244521, slug="fsrv-bj11eac", operator=self.operator, reg="BJ11EAC", vehicle_type=self.vehicle_type)
        self.rule = Rule.objects.create(name="Double decker on 22", operator=self.operator)

    def test_login_is_required(self):
        response = self.client.get(reverse("rule_list"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('rule_list')}")

    def test_rule_list_and_toggle(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("rule_list"))
        self.assertContains(response, "Double decker on 22")
        self.client.post(reverse("rule_toggle", args=[self.rule.pk]))
        self.rule.refresh_from_db()
        self.assertFalse(self.rule.active)

    def test_operator_page_includes_vehicle(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("operator_detail", args=["ZSIN"]) + "?tab=vehicles")
        self.assertContains(response, "BJ11EAC")
