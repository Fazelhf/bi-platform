"""
منابع انسانی — who works here, and where they sit.

The rest of the site used to keep its own lists of people. Each sales
department typed its کارشناسان into its own roster, the entry sheet created a
new person for any name typed into it, and the CRM import added more. So the
same person existed twice under two spellings, people who had left were still
on the sheet, and nobody could say who actually worked in which team.

This app is the one place that answers that, and everything else reads it:

* **The person** is `sales.DimEmployee`. It is not a new table, because every
  sales figure, target and CRM record already points at that row.
* **The chart** is `OrgUnit` (a tree: هیئت‌مدیره → مدیریت عامل → واحد → زیرواحد)
  and `Position` (a سمت inside a unit, held by one person or vacant).
* **A sales roster** is derived: a unit that says which sales channel it is
  puts the people holding its positions on that channel's entry sheet. See
  `services.rosters`.
"""
from django.db import models

from apps.core.models import TimeStampedModel
from apps.sales.models import DimEmployee, SalesChannel


class OrgUnit(TimeStampedModel):
    """A box on the chart: a department, a section inside one, or the top."""

    class Kind(models.TextChoices):
        BOARD = "board", "هیئت‌مدیره"
        EXECUTIVE = "executive", "مدیریت عامل"
        STAFF = "staff", "واحد ستادی"
        DEPARTMENT = "department", "واحد"
        SECTION = "section", "زیرواحد"

    name_fa = models.CharField(max_length=150)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.SECTION)
    #: PROTECT: deleting a department must not silently take its sections.
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="children"
    )
    color = models.CharField(max_length=7, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    #: Set on the unit whose people fill one sales channel's entry sheet.
    #: Inherited by its sections unless one of them names its own.
    sales_channel = models.CharField(
        max_length=16, choices=SalesChannel.choices, blank=True
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "id")
        verbose_name = "واحد سازمانی"

    def __str__(self) -> str:
        return self.name_fa


class Position(TimeStampedModel):
    """
    One سمت. Vacant when `holder` is empty — the chart's «نامشخص».

    One person may hold several (the chart has سارا مسگرچیان in four), which
    is why the person is a field here rather than the position a field on the
    person.
    """

    unit = models.ForeignKey(OrgUnit, on_delete=models.CASCADE, related_name="positions")
    title_fa = models.CharField(max_length=150)
    holder = models.ForeignKey(
        DimEmployee, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="positions",
    )
    #: مدیر / سرپرست / مسئول of the unit — drawn first and highlighted.
    is_head = models.BooleanField(default=False)
    #: Whether this seat puts its holder on the unit's sales entry sheet. A
    #: سرپرست who supervises but does not sell is off by default.
    on_sales_sheet = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("-is_head", "sort_order", "id")
        verbose_name = "سمت"

    def __str__(self) -> str:
        return f"{self.unit} · {self.title_fa}"
