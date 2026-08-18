from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from alerts import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", views.rule_list, name="rule_list"),
    path("rules/new/", views.rule_create, name="rule_create"),
    path("rules/<int:pk>/edit/", views.rule_edit, name="rule_edit"),
    path("rules/<int:pk>/toggle/", views.rule_toggle, name="rule_toggle"),
    path("rules/<int:pk>/activity/", views.rule_activity, name="rule_activity"),
    path("operators/", views.operator_list, name="operator_list"),
    path("operators/<str:noc>/", views.operator_detail, name="operator_detail"),
    path("activity/", views.activity, name="activity"),
    path("settings/", views.settings_view, name="settings"),
    path("api/operators/search/", views.operator_search, name="operator_search"),
    path("api/operators/<str:noc>/fleet/", views.operator_fleet, name="operator_fleet"),
]
