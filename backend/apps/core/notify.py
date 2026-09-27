"""Notification helpers for the approval workflow."""
from django.contrib.auth import get_user_model

from apps.core.models import Notification

User = get_user_model()

VERB_MESSAGES = {
    "submitted": "اطلاعات جدید ثبت شده است. آیا تایید می‌کنید؟",
    "approved": "اطلاعات شما تایید شد و وارد داشبورد گردید.",
    "rejected": "اطلاعات شما رد شد.",
    "revision": "اطلاعات شما برای اصلاح بازگردانده شد.",
}


def _notify(recipients, actor, verb: str, detail: str, instance) -> int:
    rows = [
        Notification(
            recipient=r,
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            verb=verb,
            message=f"{detail} — {VERB_MESSAGES.get(verb, verb)}",
            target_label=f"{instance._meta.app_label}.{instance._meta.object_name}",
            target_id=str(instance.pk),
        )
        for r in recipients
        if r.pk != getattr(actor, "pk", None)  # never notify yourself
    ]
    Notification.objects.bulk_create(rows)
    return len(rows)


def notify_submitted(actor, instance, department: str, detail: str) -> int:
    """New pending record: tell the manager of the department it belongs to."""
    approvers = User.objects.filter(is_active=True).filter(
        models_q_approvers(department)
    ).distinct()
    return _notify(approvers, actor, "submitted", detail, instance)


def notify_decision(actor, instance, verb: str, detail: str) -> int:
    """Approve/reject/revision: tell whoever submitted the record."""
    submitter = getattr(instance, "submitted_by", None)
    if submitter is None:
        return 0
    return _notify([submitter], actor, verb, detail, instance)


def models_q_approvers(department: str):
    from django.db.models import Q

    # The department's own manager approves. Only when the department has no
    # active manager does the submission go up to the CEO, so it never sits
    # in a کارتابل nobody reads.
    managers = Q(role="manager", department=department)
    if department and User.objects.filter(managers, is_active=True).exists():
        return managers
    return Q(role="executive") | Q(is_superuser=True)
