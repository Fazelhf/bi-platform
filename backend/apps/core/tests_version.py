"""The site version: «1.<last merged PR>», from the git history of the live folder."""
import subprocess
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from apps.core import version


class VersionTests(SimpleTestCase):
    def setUp(self):
        version.app_version.cache_clear()
        self.addCleanup(version.app_version.cache_clear)

    def run_git(self, subject):
        return mock.patch.object(
            subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, stdout=subject, stderr=""),
        )

    def test_it_is_one_dot_the_last_merged_pr(self):
        with self.run_git("Merge pull request #41 from Fazelhf/some-branch\n"):
            self.assertEqual(version.app_version(), "1.41")

    def test_no_git_history_falls_back(self):
        with mock.patch.object(subprocess, "run", side_effect=OSError):
            self.assertEqual(version.app_version(), "1.0")

    def test_an_explicit_value_wins(self):
        with mock.patch.dict("os.environ", {"APP_VERSION": "1.99"}):
            self.assertEqual(version.app_version(), "1.99")


class VersionInSettingsTests(APITestCase):
    def test_site_settings_carry_the_version(self):
        user = get_user_model().objects.create_user("v_user", password="x")
        self.client.force_authenticate(user)
        with mock.patch("apps.core.views.app_version", return_value="1.42"):
            res = self.client.get("/api/executive/site-settings/")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data["version"], "1.42")
