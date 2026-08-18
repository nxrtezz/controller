from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import AlertEvent, Livery, Operator, Rule, Service, Vehicle, VehicleType
from .services import process_inventory_changes, process_tracking, rule_matches_tracking


class ControllerTestCase(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("controller", password="test-pass")
        self.operator = Operator.objects.create(noc="ZSIN", name="Z & S Transport")
        self.vehicle_type = VehicleType.objects.create(bustimes_id=124, name="Volvo B9TL", fuel="diesel")
        self.other_type = VehicleType.objects.create(bustimes_id=125, name="Volvo B5LH", fuel="hybrid")
        self.livery = Livery.objects.create(bustimes_id=164, name="White")
        self.service = Service.objects.create(bustimes_id=56767, slug="22-highbury", line_name="22", description="Highbury", operator=self.operator)
        self.vehicle = Vehicle.objects.create(bustimes_id=244521, slug="fsrv-bj11eac", operator=self.operator, fleet_number="292", reg="BJ11EAC", vehicle_type=self.vehicle_type, livery=self.livery)
        self.tracking_item = {"id": 20540, "journey_id": 923349953, "destination": "Highbury", "service": {"url": "/services/22-highbury", "line_name": "22"}, "vehicle": {"url": "/vehicles/fsrv-bj11eac", "name": "292 - BJ11EAC"}}
        self.client.force_login(self.user)


class RuleBuilderTests(ControllerTestCase):
    def create_payload(self, **overrides):
        payload = {"name": "White Volvo on 22", "operator": self.operator.pk, "vehicles": [self.vehicle.pk], "vehicle_types": [self.vehicle_type.pk], "liveries": [self.livery.pk], "fuels": ["diesel"], "services": [self.service.pk], "custom_lines_text": "22A, X22", "website_alert": "on", "severity": "warning"}
        payload.update(overrides)
        return payload

    def test_login_is_required(self):
        self.client.logout()
        response = self.client.get(reverse("rule_list"))
        self.assertRedirects(response, f"{reverse('login')}?next={reverse('rule_list')}")

    def test_rule_can_be_created_with_all_criteria_and_actions(self):
        response = self.client.post(reverse("rule_create"), self.create_payload(discord_alert="on", discord_webhook="https://discord.com/api/webhooks/123/abc", quietly_log="on", alert_once="on", new_vehicle="on", vehicle_change="on", new_service="on"))
        self.assertRedirects(response, reverse("rule_list"))
        rule = Rule.objects.get(name="White Volvo on 22")
        self.assertEqual(list(rule.vehicles.all()), [self.vehicle]); self.assertEqual(list(rule.vehicle_types.all()), [self.vehicle_type])
        self.assertEqual(list(rule.liveries.all()), [self.livery]); self.assertEqual(list(rule.services.all()), [self.service])
        self.assertEqual(rule.fuels, ["diesel"]); self.assertEqual(rule.custom_lines, ["22A", "X22"])
        self.assertTrue(rule.new_vehicle and rule.vehicle_change and rule.new_service)
        self.assertTrue(rule.website_alert and rule.discord_alert and rule.quietly_log and rule.alert_once)
        self.assertEqual(rule.severity, "warning")

    def test_rule_can_be_edited_without_losing_conditions(self):
        rule = Rule.objects.create(name="Original", operator=self.operator, severity="info", fuels=["diesel"], custom_lines=["22A"])
        rule.vehicles.add(self.vehicle); rule.vehicle_types.add(self.vehicle_type); rule.liveries.add(self.livery); rule.services.add(self.service)
        response = self.client.post(reverse("rule_edit", args=[rule.pk]), self.create_payload(name="Edited", severity="urgent", custom_lines_text="X22"))
        self.assertRedirects(response, reverse("rule_list"))
        rule.refresh_from_db()
        self.assertEqual((rule.name, rule.severity, rule.custom_lines), ("Edited", "urgent", ["X22"]))
        self.assertEqual(list(rule.vehicles.all()), [self.vehicle])

    def test_rule_toggle_and_activity_pages(self):
        rule = Rule.objects.create(name="Double decker on 22", operator=self.operator)
        AlertEvent.objects.create(rule=rule, operator=self.operator, event_type="tracking", title="Match")
        self.assertContains(self.client.get(reverse("rule_list")), "Double decker on 22")
        self.client.post(reverse("rule_toggle", args=[rule.pk])); rule.refresh_from_db(); self.assertFalse(rule.active)
        response = self.client.get(reverse("rule_activity", args=[rule.pk]))
        self.assertContains(response, "24 hours"); self.assertContains(response, "All time")


class RuleMatchingTests(ControllerTestCase):
    def test_each_tracking_criterion_is_enforced(self):
        rule = Rule.objects.create(name="Specific", operator=self.operator, fuels=["diesel"], custom_lines=["22"])
        rule.vehicles.add(self.vehicle); rule.vehicle_types.add(self.vehicle_type); rule.liveries.add(self.livery); rule.services.add(self.service)
        self.assertTrue(rule_matches_tracking(rule, self.tracking_item))
        rule.fuels = ["electric"]; rule.save(); self.assertFalse(rule_matches_tracking(rule, self.tracking_item))
        rule.fuels = ["diesel"]; rule.custom_lines = ["99"]; rule.save(); self.assertTrue(rule_matches_tracking(rule, self.tracking_item))
        rule.services.clear(); self.assertFalse(rule_matches_tracking(rule, self.tracking_item))
        rule.custom_lines = ["22"]; rule.save(); self.assertTrue(rule_matches_tracking(rule, self.tracking_item))
        rule.vehicle_types.set([self.other_type]); self.assertFalse(rule_matches_tracking(rule, self.tracking_item))

    def test_tracking_creates_event_only_for_active_matching_rule(self):
        active = Rule.objects.create(name="Active", operator=self.operator)
        inactive = Rule.objects.create(name="Inactive", operator=self.operator, active=False)
        process_tracking(self.operator, [self.tracking_item])
        self.assertEqual(AlertEvent.objects.filter(rule=active, event_type="tracking").count(), 1)
        self.assertFalse(AlertEvent.objects.filter(rule=inactive).exists())

    def test_alert_once_deactivates_rule_and_discord_posts(self):
        rule = Rule.objects.create(name="One shot", operator=self.operator, alert_once=True, discord_alert=True, discord_webhook="https://discord.com/api/webhooks/123/abc")
        response = Mock(); response.raise_for_status.return_value = None
        with patch("alerts.services.SESSION.post", return_value=response) as post: process_tracking(self.operator, [self.tracking_item])
        rule.refresh_from_db(); self.assertFalse(rule.active); self.assertEqual(AlertEvent.objects.filter(rule=rule).count(), 1); post.assert_called_once()

    def test_inventory_conditions_emit_only_selected_events(self):
        rule = Rule.objects.create(name="Inventory", operator=self.operator, new_vehicle=True, vehicle_change=True, new_service=True)
        process_inventory_changes(self.operator, {"1": "old", "2": "same"}, {"2": "same", "3": "new", "1": "changed"}, {"10": "old"}, {"10": "old", "11": "new"})
        self.assertEqual(AlertEvent.objects.filter(rule=rule, event_type="new_vehicle").count(), 1)
        self.assertEqual(AlertEvent.objects.filter(rule=rule, event_type="vehicle_change").count(), 1)
        self.assertEqual(AlertEvent.objects.filter(rule=rule, event_type="new_service").count(), 1)


class NavigationAndActivityTests(ControllerTestCase):
    def test_operator_routes_and_overall_activity_render(self):
        rule = Rule.objects.create(name="Route watch", operator=self.operator)
        AlertEvent.objects.create(rule=rule, operator=self.operator, event_type="tracking", title="Tracked", payload=self.tracking_item)
        self.assertContains(self.client.get(reverse("operator_detail", args=[self.operator.noc]) + "?tab=vehicles"), "BJ11EAC")
        self.assertContains(self.client.get(reverse("operator_detail", args=[self.operator.noc]) + "?tab=routes"), "Highbury")
        self.assertContains(self.client.get(reverse("activity")), "Tracked operators")
        self.assertContains(self.client.get(reverse("settings")), "Data polling")

    def test_operator_search_results_are_rendered_without_javascript(self):
        with patch("alerts.views.api_get", return_value={"results": [{"noc": "ZSIN", "name": "Z & S Transport"}], "next": None}) as api_get:
            response = self.client.get(reverse("rule_create") + "?search=Z%20%26%20S")
        self.assertContains(response, "Z &amp; S Transport")
        self.assertContains(response, reverse("operator_select", args=["ZSIN"])); api_get.assert_called_once()
