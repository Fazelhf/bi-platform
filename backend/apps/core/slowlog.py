"""
Write slow API requests to the log, with their query count.

The server is the only place with the real data, and nobody can profile it by
hand: a page that is quick on a laptop can be slow there for reasons only its
data has. So every /api/ request that takes longer than SLOW_REQUEST_MS is
logged (and Passenger puts the log in backend/stderr.log) as

    SLOW 2412ms 318q GET /api/executive/overview/?period=12

which is enough to tell a missing index (few queries, long time) from a
query-per-row loop (hundreds of queries).
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.db import connection

log = logging.getLogger("apps.slow")


class SlowRequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.threshold = getattr(settings, "SLOW_REQUEST_MS", 1000)

    def __call__(self, request):
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        queries = 0

        def count(execute, sql, params, many, context):
            nonlocal queries
            queries += 1
            return execute(sql, params, many, context)

        start = time.monotonic()
        with connection.execute_wrapper(count):
            response = self.get_response(request)
        ms = (time.monotonic() - start) * 1000
        if ms >= self.threshold:
            log.warning(
                "SLOW %dms %dq %s %s %s",
                ms, queries, request.method, request.get_full_path(), response.status_code,
            )
        return response
