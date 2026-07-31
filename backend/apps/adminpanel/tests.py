"""
Tests for the Admin Panel.

The focus is the rules that would be expensive to get wrong: who may open the
panel at all, whether a permission code actually gates an action, and whether
destructive operations are reversible and audited.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Role, User
from apps.adminpanel.models import (
    AppRole,
    Broadcast,
    LoginEvent,
    PasswordPolicy,
    RecycleBin,
    SystemConfig,
    Team,
    UserRoleAssignment,
    UserSecurity,
)
from apps.adminpanel.permissions import SYSTEM_ROLES
from apps.core.models import AuditLog, DimPeriod, Notification
from apps.sales.models import DimEmployee, DimTeam


def make_role(code: str) -> AppRole:
    name, perms = SYSTEM_ROLES[code]
    return AppRole.objects.create(
        code=code, name_fa=name, permissions=perms, is_system=True
    )


class AdminPanelTestCase(APITestCase):
    """Shared cast: one admin, one CEO, one operator."""

    def setUp(self):
        self.super_admin_role = make_role("super_admin")
        self.auditor_role = make_role("auditor")

        self.admin = User.objects.create_user(
            "sysadmin", password="Adm1n-pass!", role=Role.ADMIN,
            display_name_fa="مدیر سیستم",
        )
        UserRoleAssignment.objects.create(user=self.admin, role=self.super_admin_role)

        self.ceo = User.objects.create_user(
            "ceo", password="Ceo-pass123!", role=Role.EXECUTIVE,
            display_name_fa="مدیرعامل",
        )
        self.operator = User.objects.create_user(
            "op", password="Op-pass1234!", role=Role.OPERATOR,
            department="sales_team",
        )

    def as_admin(self):
        self.client.force_authenticate(self.admin)

    def as_ceo(self):
        self.client.force_authenticate(self.ceo)


# ==========================================================================
class AccessControlTests(AdminPanelTestCase):
    def test_admin_can_open_panel(self):
        self.as_admin()
        response = self.client.get("/api/admin/bootstrap/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("users.delete", response.data["permissions"])

    def test_ceo_is_locked_out_of_the_panel(self):
        """The CEO has their own dashboards; the panel is not theirs."""
        self.as_ceo()
        for url in ("/api/admin/bootstrap/", "/api/admin/users/",
                    "/api/admin/dashboard/", "/api/admin/settings/"):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_ceo_can_be_granted_access_explicitly(self):
        self.ceo.admin_access = True
        self.ceo.save(update_fields=["admin_access"])
        self.as_ceo()
        self.assertEqual(self.client.get("/api/admin/bootstrap/").status_code, 200)

    def test_operator_is_locked_out(self):
        self.client.force_authenticate(self.operator)
        self.assertEqual(self.client.get("/api/admin/users/").status_code, 403)

    def test_anonymous_is_locked_out(self):
        self.assertEqual(self.client.get("/api/admin/users/").status_code, 401)

    def test_permission_code_gates_the_action(self):
        """An auditor may read everything and change nothing."""
        auditor = User.objects.create_user(
            "auditor", password="Aud-pass123!", role=Role.ADMIN
        )
        UserRoleAssignment.objects.create(user=auditor, role=self.auditor_role)
        self.client.force_authenticate(auditor)

        self.assertEqual(self.client.get("/api/admin/users/").status_code, 200)
        self.assertEqual(
            self.client.delete(f"/api/admin/users/{self.operator.id}/").status_code, 403
        )
        self.assertEqual(
            self.client.post("/api/admin/users/", {"username": "x", "password": "Zz-1234567"}).status_code,
            403,
        )


# ==========================================================================
class UserManagementTests(AdminPanelTestCase):
    def test_create_edit_delete_user(self):
        self.as_admin()
        created = self.client.post("/api/admin/users/", {
            "username": "newbie", "display_name_fa": "کاربر تازه",
            "role": "operator", "department": "production",
            "password": "Str0ng-pass!x",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        user_id = created.data["id"]

        patched = self.client.patch(
            f"/api/admin/users/{user_id}/", {"display_name_fa": "نام تازه"}, format="json"
        )
        self.assertEqual(patched.status_code, 200)
        self.assertEqual(patched.data["display_name_fa"], "نام تازه")

        self.assertEqual(
            self.client.delete(f"/api/admin/users/{user_id}/").status_code, 204
        )
        self.assertFalse(User.objects.filter(pk=user_id).exists())
        self.assertTrue(
            AuditLog.objects.filter(action="delete", model_label="accounts.User").exists()
        )

    def test_cannot_delete_or_demote_self(self):
        self.as_admin()
        self.assertEqual(
            self.client.delete(f"/api/admin/users/{self.admin.id}/").status_code, 403
        )
        response = self.client.patch(
            f"/api/admin/users/{self.admin.id}/", {"is_active": False}, format="json"
        )
        self.assertEqual(response.status_code, 403)

    def test_reset_password_returns_generated_secret_once(self):
        self.as_admin()
        response = self.client.post(
            f"/api/admin/users/{self.operator.id}/reset-password/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["password"])
        self.operator.refresh_from_db()
        self.assertTrue(self.operator.check_password(response.data["password"]))
        self.assertTrue(UserSecurity.get(self.operator).must_change_password)

    def test_own_password_reset_requires_an_explicit_password(self):
        """
        Generating a random password for your own account would show the
        plaintext once and revoke your session — one missed toast and the
        administrator is locked out of the panel. So it is refused.
        """
        self.as_admin()
        refused = self.client.post(
            f"/api/admin/users/{self.admin.id}/reset-password/", {}, format="json"
        )
        self.assertEqual(refused.status_code, 400)
        self.assertIn("password", refused.data)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("Adm1n-pass!"))

        # Naming the password explicitly is fine, and must not sign you out.
        accepted = self.client.post(
            f"/api/admin/users/{self.admin.id}/reset-password/",
            {"password": "Chosen-pass-99"}, format="json",
        )
        self.assertEqual(accepted.status_code, 200, accepted.data)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("Chosen-pass-99"))

        state = UserSecurity.get(self.admin)
        self.assertIsNone(state.tokens_valid_from)
        self.assertFalse(state.must_change_password)

    def test_resetting_someone_elses_password_still_generates_and_revokes(self):
        self.as_admin()
        response = self.client.post(
            f"/api/admin/users/{self.operator.id}/reset-password/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["password"])
        state = UserSecurity.get(self.operator)
        self.assertIsNotNone(state.tokens_valid_from)
        self.assertTrue(state.must_change_password)

    def test_lock_and_unlock(self):
        self.as_admin()
        self.client.post(
            f"/api/admin/users/{self.operator.id}/lock/",
            {"reason": "بررسی امنیتی"}, format="json",
        )
        self.assertTrue(UserSecurity.get(self.operator).is_locked)
        self.client.post(f"/api/admin/users/{self.operator.id}/unlock/")
        self.assertFalse(UserSecurity.get(self.operator).is_locked)

    def test_assign_roles_replaces_the_whole_set(self):
        self.as_admin()
        response = self.client.post(
            f"/api/admin/users/{self.operator.id}/assign-roles/",
            {"role_ids": [self.auditor_role.id]}, format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(self.operator.admin_roles.values_list("role__code", flat=True)),
            ["auditor"],
        )

    def test_bulk_update_deactivates_many(self):
        self.as_admin()
        response = self.client.patch("/api/admin/users/bulk-update/", {
            "ids": [self.operator.id], "changes": {"is_active": False},
        }, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["updated"], 1)
        self.operator.refresh_from_db()
        self.assertFalse(self.operator.is_active)

    def test_export_produces_a_spreadsheet(self):
        self.as_admin()
        response = self.client.get("/api/admin/users/export/?fmt=xlsx")
        self.assertEqual(response.status_code, 200)
        self.assertIn("spreadsheetml", response["Content-Type"])


# ==========================================================================
class RoleTests(AdminPanelTestCase):
    def test_clone_role(self):
        self.as_admin()
        response = self.client.post(
            f"/api/admin/roles/{self.auditor_role.id}/clone/",
            {"code": "auditor-plus", "name_fa": "ناظر ارشد"}, format="json",
        )
        self.assertEqual(response.status_code, 201)
        clone = AppRole.objects.get(code="auditor-plus")
        self.assertEqual(clone.permissions, self.auditor_role.permissions)
        self.assertFalse(clone.is_system)

    def test_system_roles_cannot_be_deleted(self):
        self.as_admin()
        self.assertEqual(
            self.client.delete(f"/api/admin/roles/{self.super_admin_role.id}/").status_code,
            403,
        )

    def test_unknown_permission_code_is_rejected(self):
        self.as_admin()
        response = self.client.post("/api/admin/roles/", {
            "code": "bogus", "name_fa": "نامعتبر", "permissions": ["users.launch_rocket"],
        }, format="json")
        self.assertEqual(response.status_code, 400)

    def test_permission_matrix_lists_every_role(self):
        self.as_admin()
        response = self.client.get("/api/admin/roles/matrix/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["roles"]), AppRole.objects.count())


# ==========================================================================
class TeamTests(AdminPanelTestCase):
    def test_create_team_and_manage_members(self):
        self.as_admin()
        created = self.client.post("/api/admin/teams/", {
            "code": "qa", "name_fa": "تیم کنترل کیفیت",
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        team_id = created.data["id"]

        self.client.post(f"/api/admin/teams/{team_id}/add-member/",
                         {"user_id": self.operator.id}, format="json")
        self.assertEqual(Team.objects.get(pk=team_id).member_count, 1)

        self.client.post(f"/api/admin/teams/{team_id}/remove-member/",
                         {"user_id": self.operator.id}, format="json")
        self.assertEqual(Team.objects.get(pk=team_id).member_count, 0)

    def test_hierarchy_cycle_is_rejected(self):
        self.as_admin()
        parent = Team.objects.create(code="p", name_fa="والد")
        child = Team.objects.create(code="c", name_fa="فرزند", parent=parent)
        parent.parent = child
        response = self.client.patch(
            f"/api/admin/teams/{parent.id}/", {"parent": child.id}, format="json"
        )
        self.assertEqual(response.status_code, 400)


# ==========================================================================
class DataAndRecycleBinTests(AdminPanelTestCase):
    def setUp(self):
        super().setUp()
        self.team = DimTeam.objects.create(code="t-test", name_fa="تیم آزمایشی")
        self.employee = DimEmployee.objects.create(
            code="e-test", full_name_fa="کارمند آزمایشی", team=self.team
        )

    def test_delete_goes_to_the_recycle_bin_and_restores(self):
        self.as_admin()
        response = self.client.delete(
            f"/api/admin/data/{self.employee.id}/?model=sales.DimEmployee"
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse(DimEmployee.objects.filter(pk=self.employee.id).exists())

        entry = RecycleBin.objects.get(pk=response.data["recycle_id"])
        restored = self.client.post(f"/api/admin/recycle-bin/{entry.id}/restore/")
        self.assertEqual(restored.status_code, 200, restored.data)
        self.assertTrue(DimEmployee.objects.filter(pk=self.employee.id).exists())

    def test_restoring_twice_is_refused(self):
        self.as_admin()
        response = self.client.delete(
            f"/api/admin/data/{self.employee.id}/?model=sales.DimEmployee"
        )
        entry_id = response.data["recycle_id"]
        self.client.post(f"/api/admin/recycle-bin/{entry_id}/restore/")
        second = self.client.post(f"/api/admin/recycle-bin/{entry_id}/restore/")
        self.assertEqual(second.status_code, 400)

    def test_models_outside_the_allow_list_are_unreachable(self):
        self.as_admin()
        response = self.client.get("/api/admin/data/?model=accounts.User")
        self.assertEqual(response.status_code, 400)

    def test_import_validates_before_committing(self):
        self.as_admin()
        payload = {
            "model": "sales.DimTeam",
            "mode": "validate",
            "rows": [
                {"code": "imported", "name_fa": "تیم وارداتی"},
                {"name_fa": "بدون کد"},  # missing the required slug
            ],
        }
        response = self.client.post("/api/admin/data/import/", payload, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["valid"], 1)
        self.assertEqual(response.data["invalid"], 1)
        self.assertFalse(response.data["committed"])
        self.assertFalse(DimTeam.objects.filter(code="imported").exists())

    def test_import_commit_refuses_a_partial_batch(self):
        self.as_admin()
        response = self.client.post("/api/admin/data/import/", {
            "model": "sales.DimTeam", "mode": "commit",
            "rows": [{"code": "good", "name_fa": "خوب"}, {"name_fa": "بد"}],
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertFalse(DimTeam.objects.filter(code="good").exists())

    def test_import_commit_writes_valid_rows(self):
        self.as_admin()
        response = self.client.post("/api/admin/data/import/", {
            "model": "sales.DimTeam", "mode": "commit",
            "rows": [
                {"code": "alef", "name_fa": "تیم الف"},
                {"code": "be", "name_fa": "تیم ب"},
            ],
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["committed"])
        self.assertTrue(DimTeam.objects.filter(code="alef").exists())


# ==========================================================================
class SystemAndMaintenanceTests(AdminPanelTestCase):
    def setUp(self):
        super().setUp()
        SystemConfig.objects.create(
            key="maintenance_mode", label_fa="حالت تعمیرات",
            category="maintenance", value="false",
            value_type=SystemConfig.ValueType.BOOL,
        )
        from apps.adminpanel.middleware import clear_maintenance_cache

        clear_maintenance_cache()

    def tearDown(self):
        from apps.adminpanel.middleware import clear_maintenance_cache

        clear_maintenance_cache()

    def test_maintenance_mode_blocks_users_but_not_admins(self):
        """
        Enforcement happens in middleware, before DRF authenticates, so the
        check reads the bearer token itself. The test therefore logs in for
        real rather than using force_authenticate.
        """
        DimPeriod.objects.create(jalali_year=1405, jalali_month=2)

        def token_for(username, password):
            response = self.client.post("/api/auth/token/", {
                "username": username, "password": password,
            }, format="json")
            self.assertEqual(response.status_code, 200, response.data)
            return response.data["access"]

        admin_token = token_for("sysadmin", "Adm1n-pass!")
        operator_token = token_for("op", "Op-pass1234!")

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        response = self.client.post(
            "/api/admin/maintenance/", {"enabled": True}, format="json"
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["enabled"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {operator_token}")
        self.assertEqual(self.client.get("/api/sales/periods/").status_code, 503)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {admin_token}")
        self.assertEqual(self.client.get("/api/sales/periods/").status_code, 200)

    def test_secret_settings_are_masked_and_not_overwritten_by_the_mask(self):
        secret = SystemConfig.objects.create(
            key="email_password", label_fa="رمز SMTP", category="email",
            value="hunter2", value_type=SystemConfig.ValueType.STRING, is_secret=True,
        )
        self.as_admin()
        listed = self.client.get("/api/admin/settings/?category=email")
        row = listed.data["results"][0]
        self.assertEqual(row["value"], "••••••••")

        self.client.patch(f"/api/admin/settings/{secret.id}/",
                          {"value": "••••••••"}, format="json")
        secret.refresh_from_db()
        self.assertEqual(secret.value, "hunter2")

    def test_feature_flag_toggle(self):
        from apps.adminpanel.models import FeatureFlag

        flag = FeatureFlag.objects.create(key="beta", name_fa="بتا", is_enabled=False)
        self.as_admin()
        self.client.post(f"/api/admin/feature-flags/{flag.id}/toggle/")
        flag.refresh_from_db()
        self.assertTrue(flag.is_enabled)

    def test_dashboard_reports_real_counts(self):
        self.as_admin()
        response = self.client.get("/api/admin/dashboard/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["users"]["total"], User.objects.count())


# ==========================================================================
class SecurityTests(AdminPanelTestCase):
    def test_failed_logins_are_recorded_and_lock_the_account(self):
        policy = PasswordPolicy.get()
        policy.max_failed_attempts = 3
        policy.lockout_minutes = 10
        policy.save()

        for _ in range(3):
            response = self.client.post("/api/auth/token/", {
                "username": "op", "password": "wrong",
            }, format="json")
            self.assertEqual(response.status_code, 401)

        self.assertEqual(
            LoginEvent.objects.filter(username_attempted="op", success=False).count(), 3
        )
        state = UserSecurity.get(self.operator)
        self.assertIsNotNone(state.locked_until)

        blocked = self.client.post("/api/auth/token/", {
            "username": "op", "password": "Op-pass1234!",
        }, format="json")
        self.assertEqual(blocked.status_code, 400)

    def test_successful_login_is_recorded_and_clears_the_counter(self):
        response = self.client.post("/api/auth/token/", {
            "username": "op", "password": "Op-pass1234!",
        }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn("access", response.data)
        self.assertFalse(response.data["is_admin_panel_user"])
        self.assertTrue(
            LoginEvent.objects.filter(username_attempted="op", success=True).exists()
        )

    def test_force_logout_invalidates_existing_tokens(self):
        login = self.client.post("/api/auth/token/", {
            "username": "op", "password": "Op-pass1234!",
        }, format="json")
        token = login.data["access"]

        state = UserSecurity.get(self.operator)
        state.tokens_valid_from = timezone.now() + timedelta(seconds=5)
        state.save(update_fields=["tokens_valid_from"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 401)

    def test_locked_account_cannot_use_a_valid_token(self):
        login = self.client.post("/api/auth/token/", {
            "username": "op", "password": "Op-pass1234!",
        }, format="json")
        state = UserSecurity.get(self.operator)
        state.is_locked = True
        state.save(update_fields=["is_locked"])

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def test_password_policy_is_enforced_on_user_creation(self):
        policy = PasswordPolicy.get()
        policy.min_length = 12
        policy.require_symbol = True
        policy.save()

        self.as_admin()
        response = self.client.post("/api/admin/users/", {
            "username": "weak", "password": "short1", "role": "viewer",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.data)

    def test_api_token_plaintext_is_shown_once_only(self):
        self.as_admin()
        created = self.client.post("/api/admin/api-tokens/", {
            "name": "ETL", "user": self.admin.id,
        }, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        raw = created.data["token"]
        self.assertTrue(raw)

        listed = self.client.get("/api/admin/api-tokens/")
        self.assertNotIn("token", listed.data["results"][0])

        verified = self.client.post(
            "/api/admin/api-tokens/verify/", {"token": raw}, format="json"
        )
        self.assertTrue(verified.data["valid"])

    def test_ip_rules_block_a_denied_address(self):
        from apps.adminpanel.models import IPRule

        policy = PasswordPolicy.get()
        policy.enforce_ip_rules = True
        policy.save()
        IPRule.objects.create(mode="deny", cidr="127.0.0.0/8")

        response = self.client.post("/api/auth/token/", {
            "username": "op", "password": "Op-pass1234!",
        }, format="json", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(response.status_code, 403)


# ==========================================================================
class NotificationAndContentTests(AdminPanelTestCase):
    def test_broadcast_fans_out_to_recipients(self):
        self.as_admin()
        response = self.client.post("/api/admin/broadcasts/", {
            "title": "به‌روزرسانی سامانه",
            "body": "امشب ساعت ۲۲ سامانه به‌روزرسانی می‌شود.",
            "audience": Broadcast.Audience.ROLE,
            "audience_value": ["operator"],
            "level": "warning",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["recipient_count"], 1)
        self.assertTrue(
            Notification.objects.filter(recipient=self.operator).exists()
        )

    def test_broadcast_preview_counts_without_sending(self):
        self.as_admin()
        response = self.client.post("/api/admin/broadcasts/preview/", {
            "audience": "all",
        }, format="json")
        self.assertEqual(response.data["count"], User.objects.filter(is_active=True).count())
        self.assertEqual(Notification.objects.count(), 0)

    def test_live_announcements_are_visible_to_ordinary_users(self):
        from apps.adminpanel.models import Announcement

        Announcement.objects.create(
            title="اطلاعیه", body="متن", is_published=True
        )
        Announcement.objects.create(title="پیش‌نویس", body="", is_published=False)

        self.client.force_authenticate(self.operator)
        response = self.client.get("/api/announcements/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)


# ==========================================================================
class OpsTests(AdminPanelTestCase):
    def test_backup_create_and_download(self):
        self.as_admin()
        created = self.client.post(
            "/api/admin/backups/", {"scope": "adminpanel", "note": "تست"}, format="json"
        )
        self.assertEqual(created.status_code, 201, created.data)
        self.assertGreater(created.data["size_bytes"], 0)

        download = self.client.get(f"/api/admin/backups/{created.data['id']}/download/")
        self.assertEqual(download.status_code, 200)

        # Cleanup: the file lives outside the test database.
        self.client.delete(f"/api/admin/backups/{created.data['id']}/")

    def test_restore_requires_explicit_confirmation(self):
        self.as_admin()
        created = self.client.post(
            "/api/admin/backups/", {"scope": "adminpanel"}, format="json"
        )
        response = self.client.post(
            f"/api/admin/backups/{created.data['id']}/restore/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.client.delete(f"/api/admin/backups/{created.data['id']}/")

    def test_report_preview_and_export(self):
        self.as_admin()
        preview = self.client.get("/api/admin/reports/preview/?kind=users")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.data["total"], User.objects.count())

        csv_export = self.client.get("/api/admin/reports/run/?kind=users&fmt=csv")
        self.assertEqual(csv_export.status_code, 200)
        self.assertIn("text/csv", csv_export["Content-Type"])

        pdf_export = self.client.get("/api/admin/reports/run/?kind=logins&fmt=pdf")
        self.assertEqual(pdf_export.status_code, 200)
        self.assertIn("text/html", pdf_export["Content-Type"])

    def test_monitoring_reports_honestly_when_no_worker_exists(self):
        self.as_admin()
        response = self.client.get("/api/admin/monitoring/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("available", response.data["queues"])
        self.assertTrue(response.data["api"]["ok"])

    def test_cleanup_dry_run_then_execute(self):
        AuditLog.objects.create(
            user=self.admin, action="update", model_label="x", object_id="1"
        )
        AuditLog.objects.all().update(created_at=timezone.now() - timedelta(days=400))

        self.as_admin()
        dry = self.client.get("/api/admin/database/maintenance/?days=365")
        self.assertEqual(dry.status_code, 200)
        self.assertGreaterEqual(dry.data["candidates"]["purge_audit"], 1)

        run = self.client.post("/api/admin/database/maintenance/", {
            "job": "purge_audit", "days": 365,
        }, format="json")
        self.assertEqual(run.status_code, 200)
        self.assertGreaterEqual(run.data["removed"], 1)

    def test_workflow_overview_and_restart(self):
        from apps.sales.models import ApprovalStatus, FactSalesMonthly

        period = DimPeriod.objects.create(jalali_year=1405, jalali_month=3)
        team = DimTeam.objects.create(code="wf", name_fa="تیم")
        employee = DimEmployee.objects.create(
            code="wf-emp", full_name_fa="کارمند", team=team
        )
        row = FactSalesMonthly.objects.create(
            period=period, employee=employee, channel="team",
            status=ApprovalStatus.SUBMITTED,
        )

        self.as_admin()
        overview = self.client.get("/api/admin/workflow/")
        self.assertEqual(overview.status_code, 200)
        sales = next(d for d in overview.data["domains"] if d["key"] == "sales")
        self.assertEqual(sales["total"], 1)

        restarted = self.client.post("/api/admin/workflow/", {
            "domain": "sales", "ids": [row.id], "action": "restart",
        }, format="json")
        self.assertEqual(restarted.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.status, ApprovalStatus.DRAFT)

    def test_audit_log_is_searchable_and_exportable(self):
        self.as_admin()
        self.client.post("/api/admin/teams/", {"code": "t1", "name_fa": "تیم"}, format="json")

        listed = self.client.get("/api/admin/audit-logs/?search=تیم")
        self.assertEqual(listed.status_code, 200)
        self.assertGreaterEqual(listed.data["count"], 1)

        exported = self.client.get("/api/admin/audit-logs/export/?fmt=csv")
        self.assertEqual(exported.status_code, 200)
