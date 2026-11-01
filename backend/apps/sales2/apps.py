from django.apps import AppConfig


class Sales2Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.sales2"
    label = "sales2"
    verbose_name = "Sales 2 (فروش ۲)"

    def ready(self):
        from apps.crm.arpa_import import arpa_imported

        arpa_imported.connect(_sync_after_arpa, dispatch_uid="sales2-sync-after-arpa")


def _sync_after_arpa(sender, **kwargs):
    """A committed آرپا import: copy what is new into فروش ۲ (see `cutover.sync`)."""
    from apps.sales2 import cutover

    report = cutover.sync()
    if report is None:
        return None
    return {"sales2": {
        "invoices": report.invoices, "returns": report.returns,
        "receipts": report.receipts, "receipts_updated": report.receipts_updated,
        "unmatched": len(report.unmatched),
    }}
