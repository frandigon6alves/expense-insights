from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from babel import Locale

from expense_insights.i18n import Formatter, activate
from expense_insights.models import Categorized, Transaction
from expense_insights.parsing import read_statement
from expense_insights.render import (
    OutputFormat,
    render,
    render_json,
    render_markdown,
    render_table,
)
from expense_insights.report import MonthlyReport, build_report
from expense_insights.rules import categorize, load_rules

EN = Formatter(Locale.parse("en"), "USD")


@pytest.fixture
def report(fixtures: Path) -> MonthlyReport:
    rules = load_rules(fixtures / "rules.toml").rules
    return build_report(categorize(read_statement(fixtures / "simple.csv"), rules))


def test_table_in_english(report: MonthlyReport) -> None:
    text = render_table(report, EN)
    lines = text.splitlines()
    assert lines[0] == "Expense report for March 2026"
    assert lines[1] == "=" * len(lines[0])
    assert lines[2] == "6 transactions, compared with February 2026"
    assert "Income    $2,500.00" in text
    assert "Expenses   -$393.99" in text
    assert "Net       $2,106.01" in text
    assert "Coffee               2      -$8.75      -$4.50  +94.4%" in text
    assert "Large purchases      1    -$310.00       $0.00     new" in text
    assert "Uncategorized transactions (1)" in text
    assert "Mar 11, 2026  Mystery Charge 9921  -$19.99" in text


def test_table_columns_are_aligned(report: MonthlyReport) -> None:
    lines = render_table(report, EN).splitlines()
    start = lines.index("By category") + 1
    block = lines[start : start + 2 + len(report.categories)]
    # Right-aligned numeric columns: every row ends at the same column.
    assert len({len(line) for line in block}) == 1


def test_table_in_spanish(report: MonthlyReport) -> None:
    activate("es")
    text = render_table(report, Formatter(Locale.parse("es"), "EUR"))
    assert text.startswith("Informe de gastos de marzo de 2026\n")
    assert "6 movimientos, comparados con febrero de 2026" in text
    assert "2.500,00\u00a0€" in text
    assert "+94,4\u00a0%" in text
    assert "Sin categoría" in text
    assert "nuevo" in text


def test_table_in_brazilian_portuguese(report: MonthlyReport) -> None:
    activate("pt_BR")
    text = render_table(report, Formatter(Locale.parse("pt_BR"), "BRL"))
    assert "Relatório de despesas de março de 2026" in text
    assert "R$\u00a02.500,00" in text
    assert "Principais estabelecimentos" in text
    assert "11 de mar. de 2026" in text


def test_singular_subtitle() -> None:
    one = [Categorized(Transaction(date(2026, 5, 2), "Tea", Decimal("-2")), None)]
    assert "1 transaction, compared with April 2026" in render_table(build_report(one), EN)


def test_empty_sections() -> None:
    income_only = [Categorized(Transaction(date(2026, 5, 2), "Pay", Decimal(10)), "Pay")]
    text = render_table(build_report(income_only), EN)
    assert "No spending this month." in text
    assert "Every transaction matched a rule." in text
    md = render_markdown(build_report(income_only), EN)
    assert "No spending this month." in md
    assert "Every transaction matched a rule." in md


def test_markdown(report: MonthlyReport) -> None:
    md = render_markdown(report, EN)
    assert md.startswith("# Expense report for March 2026\n\n_6 transactions")
    assert "| Category | Count | This month | Last month | Change |" in md
    assert "| :--- | ---: | ---: | ---: | ---: |" in md
    assert "| Coffee | 2 | -$8.75 | -$4.50 | +94.4% |" in md
    assert "## Uncategorized transactions (1)" in md


def test_markdown_escapes_pipes() -> None:
    items = [Categorized(Transaction(date(2026, 5, 2), "A|B shop", Decimal(-1)), None)]
    assert "A\\|B shop" in render_markdown(build_report(items), EN)


def test_json_is_locale_independent(report: MonthlyReport) -> None:
    activate("es")
    data = json.loads(render_json(report, "USD"))
    assert data["month"] == "2026-03"
    assert data["previous_month"] == "2026-02"
    assert data["summary"] == {"income": "2500.00", "expenses": "-393.99", "net": "2106.01"}
    coffee = next(c for c in data["categories"] if c["name"] == "Coffee")
    assert coffee == {
        "name": "Coffee",
        "transactions": 2,
        "total": "-8.75",
        "previous_total": "-4.50",
        "change": "0.9444",
    }
    assert data["categories"][-1]["name"] is None
    assert data["uncategorized"] == [
        {"date": "2026-03-11", "description": "Mystery Charge 9921", "amount": "-19.99"}
    ]
    assert data["top_merchants"][0] == {
        "name": "Hardware Barn, Aisle",
        "transactions": 1,
        "total": "-310.00",
    }


def test_render_dispatch(report: MonthlyReport) -> None:
    assert render(report, OutputFormat.TABLE, EN) == render_table(report, EN)
    assert render(report, OutputFormat.MARKDOWN, EN) == render_markdown(report, EN)
    assert render(report, OutputFormat.JSON, EN) == render_json(report, "USD")


def test_change_column_dash_without_history() -> None:
    items = [Categorized(Transaction(date(2026, 5, 2), "Tea", Decimal(-2)), "Tea")]
    row = next(line for line in render_table(build_report(items), EN).splitlines() if "Tea" in line)
    assert row.split()[-2:] == ["—", "—"]
