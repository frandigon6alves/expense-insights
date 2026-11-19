"""Turn a :class:`MonthlyReport` into text: a terminal table, Markdown or JSON.

The table and Markdown outputs are translated and locale-formatted. JSON is
meant for other programs, so it is locale-independent: ISO dates, amounts as
decimal strings and English keys.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Any

from expense_insights.i18n import Formatter, _, ngettext
from expense_insights.report import CategoryLine, MonthlyReport

DASH = "—"


class OutputFormat(StrEnum):
    TABLE = "table"
    MARKDOWN = "markdown"
    JSON = "json"


def render(report: MonthlyReport, output: OutputFormat, fmt: Formatter) -> str:
    if output is OutputFormat.JSON:
        return render_json(report, fmt.currency)
    if output is OutputFormat.MARKDOWN:
        return render_markdown(report, fmt)
    return render_table(report, fmt)


# --- shared pieces -----------------------------------------------------------------


def _category_name(line: CategoryLine) -> str:
    return line.name if line.name is not None else _("Uncategorized")


def _change(line: CategoryLine, fmt: Formatter) -> str:
    if line.change is not None:
        return fmt.percent(line.change)
    if line.previous is None:
        return DASH
    return _("new") if line.total else DASH


def _title(report: MonthlyReport, fmt: Formatter) -> str:
    return _("Expense report for {month}").format(month=fmt.month(report.month))


def _subtitle(report: MonthlyReport, fmt: Formatter) -> str:
    return ngettext(
        "{count} transaction, compared with {previous}",
        "{count} transactions, compared with {previous}",
        report.transaction_count,
    ).format(count=fmt.integer(report.transaction_count), previous=fmt.month(report.previous_month))


def _summary_rows(report: MonthlyReport, fmt: Formatter) -> list[list[str]]:
    return [
        [_("Income"), fmt.money(report.income)],
        [_("Expenses"), fmt.money(report.expenses)],
        [_("Net"), fmt.money(report.net)],
    ]


def _category_rows(report: MonthlyReport, fmt: Formatter) -> list[list[str]]:
    return [
        [
            _category_name(line),
            fmt.integer(line.count),
            fmt.money(line.total),
            fmt.money(line.previous) if line.previous is not None else DASH,
            _change(line, fmt),
        ]
        for line in report.categories
    ]


def _category_header() -> list[str]:
    return [_("Category"), _("Count"), _("This month"), _("Last month"), _("Change")]


def _merchant_rows(report: MonthlyReport, fmt: Formatter) -> list[list[str]]:
    return [
        [fmt.integer(rank), m.name, fmt.integer(m.count), fmt.money(m.total)]
        for rank, m in enumerate(report.merchants, start=1)
    ]


def _merchant_header() -> list[str]:
    return ["#", _("Merchant"), _("Count"), _("Spent")]


def _uncategorized_rows(report: MonthlyReport, fmt: Formatter) -> list[list[str]]:
    return [[fmt.day(t.date), t.description, fmt.money(t.amount)] for t in report.uncategorized]


def _uncategorized_header() -> list[str]:
    return [_("Date"), _("Description"), _("Amount")]


def _uncategorized_title(report: MonthlyReport, fmt: Formatter) -> str:
    count = len(report.uncategorized)
    return _("Uncategorized transactions ({count})").format(count=fmt.integer(count))


# --- terminal table ----------------------------------------------------------------


def _grid(header: Sequence[str], rows: Sequence[Sequence[str]], right: set[int]) -> list[str]:
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]

    def line(cells: Sequence[str]) -> str:
        parts = [
            cell.rjust(widths[i]) if i in right else cell.ljust(widths[i])
            for i, cell in enumerate(cells)
        ]
        return "  ".join(parts).rstrip()

    return [line(header), "  ".join("-" * w for w in widths), *(line(r) for r in rows)]


def render_table(report: MonthlyReport, fmt: Formatter) -> str:
    title = _title(report, fmt)
    out = [title, "=" * len(title), _subtitle(report, fmt), ""]

    summary = _summary_rows(report, fmt)
    label_width = max(len(label) for label, _value in summary)
    value_width = max(len(value) for _label, value in summary)
    out += [f"{label.ljust(label_width)}  {value.rjust(value_width)}" for label, value in summary]

    out += [
        "",
        _("By category"),
        *_grid(_category_header(), _category_rows(report, fmt), {1, 2, 3, 4}),
    ]

    out += ["", _("Top merchants")]
    if report.merchants:
        out += _grid(_merchant_header(), _merchant_rows(report, fmt), {0, 2, 3})
    else:
        out.append(_("No spending this month."))

    out += ["", _uncategorized_title(report, fmt)]
    if report.uncategorized:
        out += _grid(_uncategorized_header(), _uncategorized_rows(report, fmt), {2})
    else:
        out.append(_("Every transaction matched a rule."))
    return "\n".join(out) + "\n"


# --- Markdown ----------------------------------------------------------------------


def _md_escape(cell: str) -> str:
    return cell.replace("\\", "\\\\").replace("|", "\\|")


def _md_table(header: Sequence[str], rows: Sequence[Sequence[str]], right: set[int]) -> list[str]:
    align = ["---:" if i in right else ":---" for i in range(len(header))]
    return [
        "| " + " | ".join(_md_escape(c) for c in header) + " |",
        "| " + " | ".join(align) + " |",
        *("| " + " | ".join(_md_escape(c) for c in row) + " |" for row in rows),
    ]


def render_markdown(report: MonthlyReport, fmt: Formatter) -> str:
    out = [f"# {_title(report, fmt)}", "", f"_{_subtitle(report, fmt)}_", ""]
    out += _md_table([_("Summary"), _("Amount")], _summary_rows(report, fmt), {1})
    out += ["", f"## {_('By category')}", ""]
    out += _md_table(_category_header(), _category_rows(report, fmt), {1, 2, 3, 4})
    out += ["", f"## {_('Top merchants')}", ""]
    if report.merchants:
        out += _md_table(_merchant_header(), _merchant_rows(report, fmt), {0, 2, 3})
    else:
        out.append(_("No spending this month."))
    out += ["", f"## {_uncategorized_title(report, fmt)}", ""]
    if report.uncategorized:
        out += _md_table(_uncategorized_header(), _uncategorized_rows(report, fmt), {2})
    else:
        out.append(_("Every transaction matched a rule."))
    return "\n".join(out) + "\n"


# --- JSON --------------------------------------------------------------------------


def _money(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _ratio(value: Decimal | None) -> str | None:
    return None if value is None else str(value.quantize(Decimal("0.0001")))


def report_to_dict(report: MonthlyReport, currency: str) -> dict[str, Any]:
    return {
        "month": report.month.strftime("%Y-%m"),
        "previous_month": report.previous_month.strftime("%Y-%m"),
        "currency": currency,
        "transactions": report.transaction_count,
        "summary": {
            "income": _money(report.income),
            "expenses": _money(report.expenses),
            "net": _money(report.net),
        },
        "categories": [
            {
                "name": line.name,
                "transactions": line.count,
                "total": _money(line.total),
                "previous_total": _money(line.previous),
                "change": _ratio(line.change),
            }
            for line in report.categories
        ],
        "top_merchants": [
            {"name": m.name, "transactions": m.count, "total": _money(m.total)}
            for m in report.merchants
        ],
        "uncategorized": [
            {"date": t.date.isoformat(), "description": t.description, "amount": _money(t.amount)}
            for t in report.uncategorized
        ],
    }


def render_json(report: MonthlyReport, currency: str) -> str:
    return json.dumps(report_to_dict(report, currency), indent=2, ensure_ascii=False) + "\n"
