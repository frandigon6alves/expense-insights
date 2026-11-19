"""Aggregate categorized transactions into a monthly report.

All arithmetic uses :class:`~decimal.Decimal`; nothing here formats or
translates — that is the renderer's job.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from expense_insights.models import Categorized, Transaction

ZERO = Decimal(0)
_NOISE = re.compile(r"\S*\d\S*|[#*/]+")


def month_of(day: date) -> date:
    """First day of the month containing ``day``."""
    return day.replace(day=1)


def previous_month(month: date) -> date:
    return month_of(month_of(month) - timedelta(days=1))


def merchant_name(description: str) -> str:
    """Group variants like ``LIDL 4411 BERLIN`` and ``Lidl #87 Berlin`` together.

    Tokens containing digits (store numbers, card suffixes, references) are
    dropped and the rest is title-cased.
    """
    cleaned = " ".join(_NOISE.sub(" ", description).split())
    return cleaned.title() if cleaned else description.strip()


def change_ratio(current: Decimal, previous: Decimal | None) -> Decimal | None:
    """Relative change in magnitude, e.g. spending 110 after 100 is ``+0.10``.

    Magnitudes are compared so that "spent more" is a positive change for
    expenses (negative amounts) and income alike. ``None`` when there is no
    previous value to compare with.
    """
    if previous is None or previous == ZERO:
        return None
    return (abs(current) - abs(previous)) / abs(previous)


@dataclass(frozen=True)
class CategoryLine:
    name: str | None  # None means "uncategorized"
    total: Decimal
    previous: Decimal | None
    change: Decimal | None
    count: int


@dataclass(frozen=True)
class MerchantLine:
    name: str
    total: Decimal
    count: int


@dataclass(frozen=True)
class MonthlyReport:
    month: date
    previous_month: date
    income: Decimal
    expenses: Decimal
    categories: tuple[CategoryLine, ...]
    merchants: tuple[MerchantLine, ...]
    uncategorized: tuple[Transaction, ...]
    transaction_count: int
    months: tuple[date, ...]

    @property
    def net(self) -> Decimal:
        return self.income + self.expenses


class EmptyReportError(ValueError):
    """There are no transactions to report on."""


def available_months(items: Iterable[Categorized]) -> tuple[date, ...]:
    return tuple(sorted({month_of(item.transaction.date) for item in items}))


def build_report(
    items: Sequence[Categorized], month: date | None = None, top: int = 5
) -> MonthlyReport:
    """Build the report for ``month`` (default: the latest month in the data)."""
    months = available_months(items)
    if not months:
        raise EmptyReportError
    target = month_of(month) if month else months[-1]
    before = previous_month(target)

    current = [i for i in items if month_of(i.transaction.date) == target]
    earlier = [i for i in items if month_of(i.transaction.date) == before]
    has_previous = bool(earlier)

    totals: dict[str | None, Decimal] = defaultdict(Decimal)
    counts: dict[str | None, int] = defaultdict(int)
    for item in current:
        totals[item.category] += item.transaction.amount
        counts[item.category] += 1
    previous_totals: dict[str | None, Decimal] = defaultdict(Decimal)
    for item in earlier:
        previous_totals[item.category] += item.transaction.amount

    lines: list[CategoryLine] = []
    for name in set(totals) | set(previous_totals):
        prev = previous_totals.get(name, ZERO) if has_previous else None
        total = totals.get(name, ZERO)
        lines.append(CategoryLine(name, total, prev, change_ratio(total, prev), counts[name]))
    # Biggest spending first, income last, "uncategorized" always at the very end.
    lines.sort(key=lambda line: (line.name is None, line.total, line.name or ""))

    amounts = [i.transaction.amount for i in current]
    return MonthlyReport(
        month=target,
        previous_month=before,
        income=sum((a for a in amounts if a > ZERO), ZERO),
        expenses=sum((a for a in amounts if a < ZERO), ZERO),
        categories=tuple(lines),
        merchants=top_merchants((i.transaction for i in current), top),
        uncategorized=tuple(i.transaction for i in current if i.category is None),
        transaction_count=len(current),
        months=months,
    )


def top_merchants(transactions: Iterable[Transaction], limit: int) -> tuple[MerchantLine, ...]:
    """The merchants where the most money went (outgoing transactions only)."""
    totals: dict[str, Decimal] = defaultdict(Decimal)
    counts: dict[str, int] = defaultdict(int)
    for tx in transactions:
        if tx.amount < ZERO:
            name = merchant_name(tx.description)
            totals[name] += tx.amount
            counts[name] += 1
    ranked = sorted(totals, key=lambda name: (totals[name], name))
    return tuple(MerchantLine(name, totals[name], counts[name]) for name in ranked[:limit])
