from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from expense_insights.models import Categorized, Transaction
from expense_insights.parsing import read_statement
from expense_insights.report import (
    EmptyReportError,
    MonthlyReport,
    build_report,
    change_ratio,
    merchant_name,
    month_of,
    previous_month,
    top_merchants,
)
from expense_insights.rules import categorize, load_rules


@pytest.fixture
def items(fixtures: Path) -> list[Categorized]:
    rules = load_rules(fixtures / "rules.toml").rules
    return categorize(read_statement(fixtures / "simple.csv"), rules)


@pytest.fixture
def march(items: list[Categorized]) -> MonthlyReport:
    return build_report(items)


def test_month_helpers() -> None:
    assert month_of(date(2026, 3, 31)) == date(2026, 3, 1)
    assert previous_month(date(2026, 3, 15)) == date(2026, 2, 1)
    assert previous_month(date(2026, 1, 1)) == date(2025, 12, 1)


@pytest.mark.parametrize(
    ("description", "expected"),
    [
        ("LIDL 4411 BERLIN", "Lidl Berlin"),
        ("Corner Grocer 118", "Corner Grocer"),
        ("CAFE AURORA #12", "Cafe Aurora"),
        ("Card *1234 STREAMBOX", "Card Streambox"),
        ("12345", "12345"),
    ],
)
def test_merchant_name(description: str, expected: str) -> None:
    assert merchant_name(description) == expected


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        ("-110", "-100", Decimal("0.1")),
        ("-50", "-100", Decimal("-0.5")),
        ("3000", "2500", Decimal("0.2")),
        ("0", "-40", Decimal("-1")),
    ],
)
def test_change_ratio_compares_magnitudes(current: str, previous: str, expected: Decimal) -> None:
    assert change_ratio(Decimal(current), Decimal(previous)) == expected


def test_change_ratio_without_baseline() -> None:
    assert change_ratio(Decimal(-5), None) is None
    assert change_ratio(Decimal(-5), Decimal(0)) is None


def test_defaults_to_latest_month(march: MonthlyReport) -> None:
    assert march.month == date(2026, 3, 1)
    assert march.previous_month == date(2026, 2, 1)
    assert march.months == (date(2026, 2, 1), date(2026, 3, 1))
    assert march.transaction_count == 6


def test_summary_totals(march: MonthlyReport) -> None:
    assert march.income == Decimal("2500.00")
    assert march.expenses == Decimal("-393.99")
    assert march.net == Decimal("2106.01")


def test_category_lines(march: MonthlyReport) -> None:
    lines = {line.name: line for line in march.categories}
    assert [line.name for line in march.categories] == [
        "Large purchases",
        "Groceries",
        "Coffee",
        "Income",
        None,  # uncategorized is always last
    ]
    coffee = lines["Coffee"]
    assert (coffee.total, coffee.previous, coffee.count) == (Decimal("-8.75"), Decimal("-4.50"), 2)
    assert coffee.change is not None
    assert round(coffee.change, 4) == Decimal("0.9444")
    assert lines["Income"].change == Decimal(0)
    assert lines["Large purchases"].previous == Decimal(0)
    assert lines["Large purchases"].change is None


def test_uncategorized_and_merchants(march: MonthlyReport) -> None:
    assert [t.description for t in march.uncategorized] == ["Mystery Charge 9921"]
    assert [(m.name, m.count, m.total) for m in march.merchants] == [
        ("Hardware Barn, Aisle", 1, Decimal("-310.00")),
        ("Corner Grocer", 1, Decimal("-55.25")),
        ("Mystery Charge", 1, Decimal("-19.99")),
        ("Blue Bean Coffee", 2, Decimal("-8.75")),
    ]


def test_first_month_has_no_comparison(items: list[Categorized]) -> None:
    february = build_report(items, month=date(2026, 2, 14))
    assert february.month == date(2026, 2, 1)
    assert all(line.previous is None and line.change is None for line in february.categories)


def test_category_that_disappeared_is_listed() -> None:
    items = [
        Categorized(Transaction(date(2026, 1, 5), "Gym", Decimal(-30)), "Sport"),
        Categorized(Transaction(date(2026, 2, 5), "Shop", Decimal(-10)), None),
    ]
    sport = next(line for line in build_report(items).categories if line.name == "Sport")
    assert (sport.total, sport.previous, sport.change, sport.count) == (
        Decimal(0),
        Decimal(-30),
        Decimal(-1),
        0,
    )


def test_month_without_data_gives_an_empty_report(items: list[Categorized]) -> None:
    report = build_report(items, month=date(2025, 1, 1))
    assert report.transaction_count == 0
    assert report.categories == ()


def test_top_merchants_limit_and_income_ignored() -> None:
    txs = [
        Transaction(date(2026, 1, 1), "A", Decimal(-1)),
        Transaction(date(2026, 1, 1), "B", Decimal(-2)),
        Transaction(date(2026, 1, 1), "C", Decimal(100)),
    ]
    assert [m.name for m in top_merchants(txs, 1)] == ["B"]


def test_no_data() -> None:
    with pytest.raises(EmptyReportError):
        build_report([])
