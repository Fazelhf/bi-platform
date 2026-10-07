"""
پیشرفت پروژه — counted per module, then averaged.

* A module's progress is the plain average of its activities' progress (a
  done activity is 100). Plain, not weighted by days: «تحویل کدینگ» taking
  five weeks does not make it worth five times «راه‌اندازی ماژول شعبه», and
  a milestone dated to one day must not count for nothing.
* A module with no activities yet is 0٪ — it is in the charter's scope, so
  leaving it out would make the project look further along than it is.
* The project is the average of the modules marked «در پیشرفت کل» — the
  charter's twelve plus any added since. Work under no module («عمومی»:
  server, site setup) is shown but not averaged in: it is the ground the
  modules stand on, not one of the things being delivered.
* «طبق برنامه» for a module is how far today is through its window: from
  the earlier of its first activity and its charter workshop month, to its
  last activity's deadline — or the charter's go-live when it has none.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from .models import LogEntry, Meeting, Module, Task

GENERAL = "general"

STATUS_LABELS = dict(Task.Status.choices)


def _pct(task: Task) -> int:
    return 100 if task.status == Task.Status.DONE else min(task.progress, 100)


def _planned(start: date, end: date, today: date) -> float:
    if end <= start:
        return 100.0 if today >= end else 0.0
    return round(min(max((today - start).days / (end - start).days, 0), 1) * 100, 1)


def _status(tasks: list[Task]) -> str:
    if not tasks:
        return Task.Status.TODO
    if all(t.status == Task.Status.DONE for t in tasks):
        return Task.Status.DONE
    if any(t.status == Task.Status.BLOCKED for t in tasks):
        return Task.Status.BLOCKED
    if any(t.status == Task.Status.DOING or _pct(t) > 0 for t in tasks):
        return Task.Status.DOING
    return Task.Status.TODO


def report(today: date | None = None) -> dict:
    today = today or date.today()
    mods = list(Module.objects.all())
    tasks: dict = defaultdict(list)
    for t in Task.objects.all():
        tasks[t.module_id or GENERAL].append(t)
    meetings: dict = defaultdict(list)
    for m in Meeting.objects.all():
        meetings[m.module_id or GENERAL].append(m)
    issues: dict = defaultdict(int)
    for log in LogEntry.objects.filter(kind=LogEntry.Kind.ISSUE, resolved=False).select_related("task"):
        issues[(log.task.module_id if log.task else None) or GENERAL] += 1

    def card(key, label, owner="", specialist="", start=None, end=None, in_scope=False, keywords=""):
        ts, ms = tasks.get(key, []), meetings.get(key, [])
        held = [m for m in ms if m.status == Meeting.Status.HELD]
        rated = [m.rating for m in held if m.rating]
        open_ts = [t for t in ts if t.status != Task.Status.DONE]
        if ts:
            start = min([t.start_on for t in ts] + ([start] if start else []))
            end = max(t.end_on for t in ts)
        nxt = min((t for t in open_ts if t.end_on >= today), key=lambda t: t.end_on, default=None)
        status = _status(ts)
        last = max([m.held_at.date() for m in held] + [t.updated_at.date() for t in ts], default=None)
        return {
            "key": key, "label": label, "owner": owner, "specialist": specialist,
            "in_scope": in_scope, "keywords": keywords,
            "progress": round(sum(_pct(t) for t in ts) / len(ts), 1) if ts else 0.0,
            "planned": _planned(start, end, today) if start and end else 0.0,
            "status": status, "status_label": STATUS_LABELS[status],
            "start_on": start.isoformat() if start else None,
            "end_on": end.isoformat() if end else None,
            "task_count": len(ts),
            "done_count": sum(1 for t in ts if t.status == Task.Status.DONE),
            "blocked_count": sum(1 for t in ts if t.status == Task.Status.BLOCKED),
            "overdue_count": sum(1 for t in open_ts if t.end_on < today),
            "next_deadline": {"id": nxt.id, "title": nxt.title, "end_on": nxt.end_on.isoformat()} if nxt else None,
            "meetings_held": len(held),
            "meeting_minutes": sum(m.duration_min for m in held),
            "avg_rating": round(sum(rated) / len(rated), 2) if rated else None,
            "open_issues": issues.get(key, 0),
            "last_activity": last.isoformat() if last else None,
        }

    cards = [card(m.id, m.title, m.owner, m.specialist, m.starts_on, m.ends_on, m.in_scope, m.keywords)
             for m in mods]
    general = None
    if tasks.get(GENERAL) or meetings.get(GENERAL):
        general = card(GENERAL, "عمومی / زیرساخت")
    scope = [c for c in cards if c["in_scope"]]
    n = len(scope) or 1
    return {
        "progress": round(sum(c["progress"] for c in scope) / n, 1),
        "planned_progress": round(sum(c["planned"] for c in scope) / n, 1),
        "modules": cards,
        "general": general,
        "in_scope": len(scope),
        "live": sum(1 for c in scope if c["task_count"] and c["status"] == Task.Status.DONE),
        "started": sum(1 for c in scope if c["task_count"] and c["progress"] > 0),
    }
