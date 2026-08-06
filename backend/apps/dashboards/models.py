"""
Saved boards.

A board is a manager's own arrangement of a section's numbers: which figures,
drawn how, in what order. The data itself is untouched — a widget only ever
holds a *question* (a spec from ``query.py``) and a *position*, never a copy of
an answer. That is what lets a board built in خرداد keep answering in مهر.
"""
from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel
from apps.dashboards.catalog import SECTIONS, WIDGET_KINDS

SECTION_CHOICES = [(s.key, s.label) for s in SECTIONS]
KIND_CHOICES = [(k["key"], k["label"]) for k in WIDGET_KINDS]

#: The canvas is 12 columns wide at every breakpoint; `w`/`h` are in grid
#: units, and one row is a fixed pixel height on the frontend. Keeping the
#: geometry this coarse is deliberate — a manager drags cards onto a grid,
#: they do not lay out pixels.
GRID_COLUMNS = 12


class Dashboard(TimeStampedModel):
    """One arrangement of one section. A section may hold several."""

    section = models.CharField(max_length=20, choices=SECTION_CHOICES, db_index=True)
    title = models.CharField(max_length=120)
    subtitle = models.CharField(max_length=250, blank=True)

    #: The one a visitor to the section sees. Exactly one per section is kept
    #: default by :meth:`save`; the others are alternates the manager switches
    #: between (a board for the board meeting, a board for the daily check).
    is_default = models.BooleanField(default=False)

    #: An unpublished board is a draft only its owner and other editors see —
    #: it lets a manager build next quarter's report without anyone landing
    #: on a half-finished page in the meantime.
    is_published = models.BooleanField(default=True)

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="dashboards",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("section", "sort_order", "id")
        verbose_name = "داشبورد"
        verbose_name_plural = "داشبوردها"
        indexes = [models.Index(fields=["section", "is_default"])]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.is_default:
            # Two defaults in one section means the page picks arbitrarily —
            # demote the others rather than let that happen.
            Dashboard.objects.filter(section=self.section, is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)

    def __str__(self) -> str:
        return f"{self.title} ({self.get_section_display()})"


class Widget(TimeStampedModel):
    """
    One card on a board: what to draw, from what, and where.

    ``config`` is the query spec — validated against the catalog by
    :func:`apps.dashboards.serializers.validate_widget_config` on every write,
    so a stored widget is always answerable. Display-only choices (colour,
    whether to show the legend, the text of a note) live in ``options``, which
    is free-form because nothing in it can reach the database.
    """

    dashboard = models.ForeignKey(
        Dashboard, on_delete=models.CASCADE, related_name="widgets"
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    title = models.CharField(max_length=150, blank=True)
    subtitle = models.CharField(max_length=250, blank=True)

    # Grid position, in columns/rows. Validation lives in the serializer.
    x = models.PositiveSmallIntegerField(default=0)
    y = models.PositiveSmallIntegerField(default=0)
    w = models.PositiveSmallIntegerField(default=4)
    h = models.PositiveSmallIntegerField(default=4)

    config = models.JSONField(default=dict, blank=True)
    options = models.JSONField(default=dict, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ("dashboard", "y", "x", "sort_order", "id")
        verbose_name = "ویجت"
        verbose_name_plural = "ویجت‌ها"

    def __str__(self) -> str:
        return f"{self.title or self.get_kind_display()} · {self.dashboard.title}"
