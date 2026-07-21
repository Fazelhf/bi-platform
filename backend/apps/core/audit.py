"""Audit helpers — call these at every mutation point in the API views."""
from django.forms.models import model_to_dict

from apps.core.models import AuditLog


def _snapshot(instance) -> dict:
    return {k: str(v) for k, v in model_to_dict(instance).items()}


def diff(before: dict, after: dict) -> dict:
    """{field: {before, after}} for changed fields only."""
    return {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in after
        if before.get(key) != after.get(key)
    }


def log(user, instance, action: str, changes: dict | None = None) -> AuditLog:
    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        action=action,
        model_label=f"{instance._meta.app_label}.{instance._meta.object_name}",
        object_id=str(instance.pk),
        object_repr=str(instance)[:200],
        changes=changes or {},
    )


class AuditedUpdateMixin:
    """Drop-in for ModelViewSets: records create/update/delete with diffs.
    Views that override perform_update should snapshot manually instead."""

    def perform_create(self, serializer):
        instance = serializer.save()
        log(self.request.user, instance, AuditLog.Action.CREATE)

    def perform_update(self, serializer):
        before = _snapshot(serializer.instance)
        instance = serializer.save()
        log(
            self.request.user, instance, AuditLog.Action.UPDATE,
            diff(before, _snapshot(instance)),
        )

    def perform_destroy(self, instance):
        log(self.request.user, instance, AuditLog.Action.DELETE, _snapshot(instance))
        instance.delete()


# Re-export for views that snapshot manually around custom perform_update.
snapshot = _snapshot
