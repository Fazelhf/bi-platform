import urllib.parse
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework.throttling import ScopedRateThrottle

from apps.accounts import otp
from apps.accounts.models import Department, OtpChallenge, Role, User
from apps.accounts.sms import SmsError, is_configured, normalize_phone, send_otp
from apps.core.models import DimPeriod
from apps.sales.models import DimEmployee, FactSalesMonthly, SalesChannel


class DepartmentPermissionTests(APITestCase):
    def setUp(self):
        self.period = DimPeriod.objects.create(jalali_year=1405, jalali_month=2)
        self.emp = DimEmployee.objects.create(code="e1", full_name_fa="آزمون")
        self.team_row = FactSalesMonthly.objects.create(
            period=self.period, employee=self.emp,
            channel=SalesChannel.TEAM, revenue_rial=Decimal("100"),
        )
        self.org_row = FactSalesMonthly.objects.create(
            period=self.period, employee=self.emp,
            channel=SalesChannel.ORGANIZATIONAL, revenue_rial=Decimal("200"),
        )

        def mk(username, role, dept):
            u = User.objects.create(username=username, role=role, department=dept)
            u.set_password("x")
            u.save()
            return u

        self.ceo = mk("ceo", Role.EXECUTIVE, Department.NONE)
        self.team_mgr = mk("team", Role.MANAGER, Department.SALES_TEAM)
        self.org_mgr = mk("org", Role.MANAGER, Department.SALES_ORG)
        self.prod_mgr = mk("prod", Role.MANAGER, Department.PRODUCTION)

    def _patch(self, user, row, value):
        self.client.force_authenticate(user)
        return self.client.patch(
            f"/api/sales/sales-monthly/{row.id}/", {"revenue_rial": value}, format="json"
        )

    def test_ceo_can_read_but_not_write(self):
        self.client.force_authenticate(self.ceo)
        self.assertEqual(self.client.get("/api/sales/sales-monthly/").status_code, 200)
        self.assertEqual(self._patch(self.ceo, self.team_row, 999).status_code, 403)

    def test_team_manager_edits_only_team_channel(self):
        self.assertEqual(self._patch(self.team_mgr, self.team_row, 111).status_code, 200)
        self.assertEqual(self._patch(self.team_mgr, self.org_row, 111).status_code, 403)

    def test_org_manager_edits_only_org_channel(self):
        self.assertEqual(self._patch(self.org_mgr, self.org_row, 222).status_code, 200)
        self.assertEqual(self._patch(self.org_mgr, self.team_row, 222).status_code, 403)

    def test_production_manager_cannot_touch_sales(self):
        self.assertEqual(self._patch(self.prod_mgr, self.team_row, 333).status_code, 403)
        self.assertEqual(self._patch(self.prod_mgr, self.org_row, 333).status_code, 403)

    def test_me_endpoint_reports_capabilities(self):
        self.client.force_authenticate(self.org_mgr)
        r = self.client.get("/api/auth/me/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["department"], "sales_org")
        self.assertTrue(r.data["can_enter_data"])


# SMS_MODE is pinned, not inherited: a developer with a real gateway in their
# own .env would otherwise run these against the wrong endpoint.
@override_settings(
    SMS_MODE="otp", SMS_USERNAME="u", SMS_PASSWORD="k", SMS_FROM="5000", SMS_BODY_ID="77"
)
class SmsGatewayTests(APITestCase):
    """The wire format of a send, and how the panel's replies are read."""

    def send(self, reply: str):
        """Run send_otp against a canned gateway reply; return the request."""
        opened = {}

        class FakeResponse:
            def read(self_inner):
                return reply.encode()

            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *_):
                return False

        def fake_urlopen(request, timeout=None):
            opened["url"] = request.full_url
            opened["body"] = dict(urllib.parse.parse_qsl(request.data.decode()))
            return FakeResponse()

        with patch("apps.accounts.sms.urllib.request.urlopen", fake_urlopen):
            opened["result"] = send_otp("09121112233", "123456")
        return opened

    def test_dedicated_line_posts_sendotp_with_the_sender(self):
        sent = self.send('{"Value":"9876543210123456","RetStatus":1,"StrRetStatus":"Ok"}')
        self.assertTrue(sent["url"].endswith("/SendOtp"))
        self.assertEqual(sent["body"]["from"], "5000")
        self.assertEqual(sent["body"]["code"], "123456")
        self.assertEqual(sent["body"]["to"], "09121112233")
        self.assertEqual(sent["result"], "9876543210123456")

    @override_settings(SMS_MODE="shared")
    def test_shared_line_posts_the_template_id_and_no_sender(self):
        sent = self.send('{"Value":"9876543210123456","RetStatus":1,"StrRetStatus":"Ok"}')
        self.assertTrue(sent["url"].endswith("/BaseServiceNumber"))
        self.assertEqual(sent["body"]["bodyId"], "77")
        self.assertEqual(sent["body"]["text"], "123456")
        self.assertNotIn("from", sent["body"])

    def test_error_reply_becomes_a_persian_message(self):
        with self.assertRaises(SmsError) as caught:
            self.send('{"Value":"-111","RetStatus":35,"StrRetStatus":"InvalidData"}')
        self.assertIn("آی‌پی", caught.exception.detail)
        self.assertEqual(caught.exception.code, "-111")

    @override_settings(SMS_MODE="shared")
    def test_the_same_code_reads_differently_per_endpoint(self):
        # -4 is "template not approved" on the shared line; SendOtp has no such
        # code, which is why the two maps are not merged.
        with self.assertRaises(SmsError) as caught:
            self.send('{"Value":"-4","RetStatus":35,"StrRetStatus":"InvalidData"}')
        self.assertIn("الگو", caught.exception.detail)

    def test_soap_style_string_reply_is_understood(self):
        sent = self.send('<string xmlns="http://tempuri.org/">9876543210123456</string>')
        self.assertEqual(sent["result"], "9876543210123456")

    def test_a_short_undocumented_reply_is_not_taken_for_success(self):
        # The panel answers a bare "100" to SendOtp with no sender line. It is
        # in no error table, but it is not a recId either.
        with self.assertRaises(SmsError):
            self.send('<string xmlns="http://tempuri.org/">100</string>')

    @override_settings(SMS_MODE="shared", SMS_BODY_ID="")
    def test_shared_mode_without_a_template_id_is_not_configured(self):
        self.assertFalse(is_configured())

    @override_settings(SMS_MODE="otp", SMS_FROM="")
    def test_dedicated_mode_without_a_sender_is_not_configured(self):
        self.assertFalse(is_configured())


class PhoneNormalisationTests(APITestCase):
    def test_accepts_the_shapes_people_type(self):
        for raw in ["09123456789", "+989123456789", "0098 912 345 6789",
                    "989123456789", "9123456789", "0912-345-6789",
                    "۰۹۱۲۳۴۵۶۷۸۹"]:
            self.assertEqual(normalize_phone(raw), "09123456789", raw)

    def test_rejects_what_is_not_a_mobile_number(self):
        for raw in ["", "0212345678", "0812345678", "091234567", "abc"]:
            self.assertEqual(normalize_phone(raw), "", raw)


# The endpoints under test are throttled per minute, and the throttle counter
# lives in a process-wide cache — so a suite that exercises them thoroughly
# would start failing on rate limits rather than on behaviour. The per-challenge
# caps (attempts, resends, cooldown) are the limits these tests care about, and
# those are enforced in the database, not here.
#
# Patching the class attribute rather than overriding REST_FRAMEWORK: DRF binds
# THROTTLE_RATES onto SimpleRateThrottle when the module is imported, so a
# settings override arrives too late to be seen. A rate of None means "no
# limit" to parse_rate().
no_throttle = patch.object(
    ScopedRateThrottle, "THROTTLE_RATES", {"login": None, "otp": None}
)


@no_throttle
class TwoFactorLoginTests(APITestCase):
    """The two-step login, with the SMS gateway stubbed out."""

    def setUp(self):
        self.user = User.objects.create(
            username="mgr", role=Role.MANAGER, department=Department.SALES_TEAM,
            phone="09123456789", two_factor_enabled=True,
        )
        self.user.set_password("secret-pass")
        self.user.save()

        self.plain = User.objects.create(username="plain", role=Role.VIEWER)
        self.plain.set_password("secret-pass")
        self.plain.save()

        # Capture the code the gateway would have delivered.
        self.sent = []
        patcher = patch(
            "apps.accounts.otp.send_otp",
            side_effect=lambda phone, code: self.sent.append((phone, code)) or "rec-1",
        )
        self.send = patcher.start()
        self.addCleanup(patcher.stop)
        # Throttle state lives in the process cache and would leak between
        # tests; every call here is a fresh scope-free client.
        self.client.credentials()

    def login(self, username="mgr", password="secret-pass"):
        return self.client.post(
            "/api/auth/token/", {"username": username, "password": password},
            format="json",
        )

    # --- step 1 -----------------------------------------------------------
    def test_password_alone_does_not_return_tokens(self):
        r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["otp_required"])
        self.assertNotIn("access", r.data)
        self.assertEqual(r.data["phone_masked"], "0912***6789")
        self.assertEqual(len(self.sent), 1)

    def test_account_without_two_factor_still_gets_tokens(self):
        r = self.login("plain")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        self.assertEqual(self.sent, [])

    def test_wrong_password_sends_no_sms(self):
        self.assertEqual(self.login(password="nope").status_code, 401)
        self.assertEqual(self.sent, [])

    def test_enabled_without_a_phone_falls_back_to_one_step(self):
        # Half-configured must not mean locked out.
        self.user.phone = ""
        self.user.save(update_fields=["phone"])
        r = self.login()
        self.assertIn("access", r.data)

    # --- step 2 -----------------------------------------------------------
    def verify(self, challenge, code):
        return self.client.post(
            "/api/auth/2fa/verify/", {"challenge": challenge, "code": code},
            format="json",
        )

    def test_right_code_returns_tokens(self):
        challenge = self.login().data["challenge"]
        r = self.verify(challenge, self.sent[-1][1])
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        self.assertIn("refresh", r.data)

    def test_persian_digits_in_the_code_are_accepted(self):
        challenge = self.login().data["challenge"]
        code = self.sent[-1][1].translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        self.assertEqual(self.verify(challenge, code).status_code, 200)

    def test_code_cannot_be_replayed(self):
        challenge = self.login().data["challenge"]
        code = self.sent[-1][1]
        self.assertEqual(self.verify(challenge, code).status_code, 200)
        self.assertEqual(self.verify(challenge, code).status_code, 410)

    def test_expired_code_is_refused(self):
        challenge = self.login().data["challenge"]
        row = OtpChallenge.objects.get(token=challenge)
        row.expires_at = timezone.now() - timedelta(seconds=1)
        row.save(update_fields=["expires_at"])
        self.assertEqual(self.verify(challenge, self.sent[-1][1]).status_code, 410)

    def test_wrong_code_dies_after_the_attempt_cap(self):
        challenge = self.login().data["challenge"]
        good = self.sent[-1][1]
        bad = "000000" if good != "000000" else "111111"
        for _ in range(4):
            self.assertEqual(self.verify(challenge, bad).status_code, 400)
        self.assertEqual(self.verify(challenge, bad).status_code, 429)
        # …and the correct code no longer helps.
        self.assertEqual(self.verify(challenge, good).status_code, 410)

    def test_a_new_login_kills_the_previous_code(self):
        first = self.login().data["challenge"]
        first_code = self.sent[-1][1]
        self.login()
        self.assertEqual(self.verify(first, first_code).status_code, 410)

    def test_challenge_from_enrolment_is_not_a_login(self):
        self.client.force_authenticate(self.user)
        started = self.client.post(
            "/api/auth/2fa/start/",
            {"password": "secret-pass", "phone": "09120000000"}, format="json",
        )
        self.client.force_authenticate(None)
        self.assertEqual(
            self.verify(started.data["challenge"], self.sent[-1][1]).status_code, 400
        )

    # --- resend -----------------------------------------------------------
    def test_resend_is_rate_limited_then_allowed(self):
        challenge = self.login().data["challenge"]
        r = self.client.post("/api/auth/2fa/resend/", {"challenge": challenge},
                             format="json")
        self.assertEqual(r.status_code, 429)  # inside the cooldown

        row = OtpChallenge.objects.get(token=challenge)
        row.last_sent_at = timezone.now() - timedelta(seconds=120)
        row.save(update_fields=["last_sent_at"])
        r = self.client.post("/api/auth/2fa/resend/", {"challenge": challenge},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.sent), 2)
        # The new code replaces the old one.
        self.assertEqual(self.verify(challenge, self.sent[-1][1]).status_code, 200)

    def test_send_failure_leaves_no_dangling_challenge(self):
        from apps.accounts.sms import SmsError

        self.send.side_effect = SmsError("اعتبار پنل پیامک کافی نیست.")
        r = self.login()
        self.assertEqual(r.status_code, 503)
        self.assertFalse(
            OtpChallenge.objects.filter(consumed_at__isnull=True).exists()
        )


@no_throttle
class TwoFactorEnrolmentTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create(username="u1", role=Role.MANAGER)
        self.user.set_password("secret-pass")
        self.user.save()
        self.admin = User.objects.create(
            username="boss", role=Role.EXECUTIVE, is_superuser=True
        )

        self.sent = []
        patcher = patch(
            "apps.accounts.otp.send_otp",
            side_effect=lambda phone, code: self.sent.append((phone, code)) or "rec-1",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client.force_authenticate(self.user)

    def start(self, phone="09121112233", password="secret-pass"):
        return self.client.post(
            "/api/auth/2fa/start/", {"phone": phone, "password": password},
            format="json",
        )

    def test_enrolment_needs_the_account_password(self):
        self.assertEqual(self.start(password="wrong").status_code, 400)
        self.assertEqual(self.sent, [])

    def test_enrolment_rejects_a_non_mobile_number(self):
        self.assertEqual(self.start(phone="02112345678").status_code, 400)

    def test_enrolment_completes_only_after_the_code(self):
        challenge = self.start().data["challenge"]
        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)  # not yet

        r = self.client.post(
            "/api/auth/2fa/confirm/",
            {"challenge": challenge, "code": self.sent[-1][1]}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.two_factor_enabled)
        self.assertEqual(self.user.phone, "09121112233")

    def test_another_users_challenge_cannot_be_confirmed(self):
        challenge = self.start().data["challenge"]
        other = User.objects.create(username="u2")
        self.client.force_authenticate(other)
        r = self.client.post(
            "/api/auth/2fa/confirm/",
            {"challenge": challenge, "code": self.sent[-1][1]}, format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_disable_needs_the_password(self):
        self.user.two_factor_enabled = True
        self.user.phone = "09121112233"
        self.user.save()
        self.assertEqual(
            self.client.post("/api/auth/2fa/disable/", {"password": "wrong"},
                             format="json").status_code, 400,
        )
        r = self.client.post("/api/auth/2fa/disable/", {"password": "secret-pass"},
                             format="json")
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)

    def test_admin_may_switch_it_off_but_not_on(self):
        self.client.force_authenticate(self.admin)
        r = self.client.patch(
            f"/api/auth/users/{self.user.id}/", {"two_factor_enabled": True},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

        self.user.two_factor_enabled = True
        self.user.phone = "09121112233"
        self.user.save()
        r = self.client.patch(
            f"/api/auth/users/{self.user.id}/", {"two_factor_enabled": False},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)


@no_throttle
class SmsRecoveryTests(APITestCase):
    """ورود با کد پیامکی and فراموشی رمز — getting in via the phone."""

    def setUp(self):
        self.user = User.objects.create(
            username="ali", role=Role.MANAGER, department=Department.SALES_TEAM,
            phone="09121112233",
        )
        self.user.set_password("old-Password-1")
        self.user.save()

        self.sent = []
        patcher = patch(
            "apps.accounts.otp.send_otp",
            side_effect=lambda phone, code: self.sent.append((phone, code)) or "rec-1",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, url, **data):
        return self.client.post(url, data, format="json")

    # --- passwordless login ----------------------------------------------
    def test_login_by_code_works_from_username_or_phone(self):
        for identifier in ["ali", "ALI", "09121112233", "+989121112233"]:
            started = self.post("/api/auth/otp-login/start/", identifier=identifier)
            self.assertEqual(started.status_code, 200, identifier)
            r = self.post(
                "/api/auth/otp-login/verify/",
                challenge=started.data["challenge"], code=self.sent[-1][1],
            )
            self.assertEqual(r.status_code, 200, identifier)
            self.assertIn("access", r.data)

    def test_unknown_identifier_sends_nothing(self):
        r = self.post("/api/auth/otp-login/start/", identifier="nobody")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.sent, [])

    def test_account_without_a_phone_is_refused(self):
        self.user.phone = ""
        self.user.save(update_fields=["phone"])
        self.assertEqual(
            self.post("/api/auth/otp-login/start/", identifier="ali").status_code, 400
        )

    def test_two_factor_accounts_keep_their_second_factor(self):
        self.user.two_factor_enabled = True
        self.user.save(update_fields=["two_factor_enabled"])
        r = self.post("/api/auth/otp-login/start/", identifier="ali")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.sent, [])

    @override_settings(OTP_LOGIN_ENABLED=False)
    def test_can_be_switched_off_platform_wide(self):
        r = self.post("/api/auth/otp-login/start/", identifier="ali")
        self.assertEqual(r.status_code, 403)

    def test_a_login_code_cannot_reset_the_password(self):
        started = self.post("/api/auth/otp-login/start/", identifier="ali")
        r = self.post(
            "/api/auth/password-reset/verify/",
            challenge=started.data["challenge"], code=self.sent[-1][1],
        )
        self.assertEqual(r.status_code, 400)

    # --- password reset ---------------------------------------------------
    def reset_to(self, password):
        started = self.post("/api/auth/password-reset/start/", identifier="ali")
        verified = self.post(
            "/api/auth/password-reset/verify/",
            challenge=started.data["challenge"], code=self.sent[-1][1],
        )
        self.assertEqual(verified.status_code, 200)
        return self.post(
            "/api/auth/password-reset/confirm/",
            reset_token=verified.data["reset_token"], password=password,
        )

    def test_reset_sets_the_password_and_signs_in(self):
        r = self.reset_to("brand-New-Pass-9")
        self.assertEqual(r.status_code, 200)
        self.assertIn("access", r.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("brand-New-Pass-9"))
        # …and the old password is gone.
        self.assertEqual(
            self.post("/api/auth/token/", username="ali", password="old-Password-1")
            .status_code, 401,
        )

    def test_weak_password_is_rejected(self):
        r = self.reset_to("1234")
        self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("old-Password-1"))

    def test_permit_cannot_be_replayed(self):
        started = self.post("/api/auth/password-reset/start/", identifier="ali")
        verified = self.post(
            "/api/auth/password-reset/verify/",
            challenge=started.data["challenge"], code=self.sent[-1][1],
        )
        token = verified.data["reset_token"]
        self.assertEqual(
            self.post("/api/auth/password-reset/confirm/",
                      reset_token=token, password="brand-New-Pass-9").status_code, 200,
        )
        # The hash it was minted against is gone, so the permit is too.
        self.assertEqual(
            self.post("/api/auth/password-reset/confirm/",
                      reset_token=token, password="another-New-Pass-9").status_code, 400,
        )

    def test_forged_permit_is_refused(self):
        r = self.post("/api/auth/password-reset/confirm/",
                      reset_token="not-a-real-token", password="brand-New-Pass-9")
        self.assertEqual(r.status_code, 400)

    def test_wrong_code_yields_no_permit(self):
        started = self.post("/api/auth/password-reset/start/", identifier="ali")
        good = self.sent[-1][1]
        r = self.post(
            "/api/auth/password-reset/verify/",
            challenge=started.data["challenge"],
            code="000000" if good != "000000" else "111111",
        )
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("reset_token", r.data)


class OtpCodeTests(APITestCase):
    def test_code_is_six_digits_and_stored_hashed(self):
        user = User.objects.create(username="h1", phone="09123456789")
        with patch("apps.accounts.otp.send_otp") as send:
            challenge = otp.start(user, OtpChallenge.Purpose.LOGIN, user.phone)
        code = send.call_args.args[1]
        self.assertRegex(code, r"^\d{6}$")
        self.assertNotIn(code, challenge.code_hash)
        self.assertEqual(challenge.code_hash, otp.hash_code(challenge.token, code))
