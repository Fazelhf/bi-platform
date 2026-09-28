"""
The site's version: «1.<number of the last merged pull request>» — 1.42 after
PR #42 is merged and deployed.

Read from the git history of the folder the site runs from, because that is
the one place that knows which PR is live: the frontend bundle is built on the
branch *before* its PR is merged and numbered, so it cannot know its own.
Computed once per process — a deploy restarts the app, which is exactly when
it changes.
"""
from __future__ import annotations

import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path

from django.conf import settings

MAJOR = 1
_PR = re.compile(r"Merge pull request #(\d+)")


@lru_cache(maxsize=1)
def app_version() -> str:
    # An explicit value wins — for a host whose deploy has no .git to read.
    override = os.environ.get("APP_VERSION", "").strip()
    if override:
        return override
    repo = Path(settings.BASE_DIR).parent
    try:
        subject = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--merges",
             "--grep=Merge pull request #", "--format=%s"],
            capture_output=True, text=True, timeout=5, check=False,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        subject = ""
    match = _PR.search(subject or "")
    return f"{MAJOR}.{match.group(1)}" if match else f"{MAJOR}.0"
