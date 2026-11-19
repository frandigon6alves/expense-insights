from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from expense_insights.i18n import activate
from expense_insights.parsing import (
    ColumnMapping,
    DecimalSeparator,
    StatementError,
    detect_date_format,
    parse_amount,
    parse_iso_month,
    read_statement,
    read_statements,
)

POINT, COMMA = DecimalSeparator.POINT, DecimalSeparator.COMMA


@pytest.mark.parametrize(
    ("text", "decimal", "expected"),
    [
        ("12.34", POINT, "12.34"),
        ("-12.34", POINT, "-12.34"),
        ("+7", POINT, "7"),
        ("1,234.50", POINT, "1234.50"),
        ("-1,234,567.89", POINT, "-1234567.89"),
        ("(89.95)", POINT, "-89.95"),
        ("45.00-", POINT, "-45.00"),
        ("\u221212.00", POINT, "-12.00"),
        ("$ 1,000.00", POINT, "1000.00"),
        ("USD -3.10", POINT, "-3.10"),
        ("1'234.50", POINT, "1234.50"),
        ("12,34", COMMA, "12.34"),
        ("-1.234,56", COMMA, "-1234.56"),
        ("1.234,56-", COMMA, "-1234.56"),
        ("R$ 4.850,00", COMMA, "4850.00"),
        ("9,99\u00a0€", COMMA, "9.99"),
        ("1 234,56", COMMA, "1234.56"),
        ("0", POINT, "0"),
    ],
)
def test_parse_amount(text: str, decimal: DecimalSeparator, expected: str) -> None:
    result = parse_amount(text, decimal)
    assert isinstance(result, Decimal)
    assert result == Decimal(expected)


def test_parse_amount_keeps_exact_cents() -> None:
    # 0.1 + 0.2 is the classic float trap; Decimal must give exactly 0.3.
    assert parse_amount("0.1") + parse_amount("0.2") == Decimal("0.3")


@pytest.mark.parametrize("text", ["", "abc", "1.2.3", "--5", "-", "1,2,3.4.5"])
def test_parse_amount_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError, match=r".*"):
        parse_amount(text, POINT)


def test_detect_date_format_uses_the_whole_column() -> None:
    # "03/04/2026" alone is ambiguous; "25/04/2026" proves the column is day-first.
    values = ["03/04/2026", "25/04/2026"]
    assert detect_date_format(values, ["%m/%d/%Y", "%d/%m/%Y"]) == "%d/%m/%Y"


def test_detect_date_format_prefers_earlier_formats_when_ambiguous() -> None:
    assert detect_date_format(["03/04/2026"], ["%m/%d/%Y", "%d/%m/%Y"]) == "%m/%d/%Y"


def test_detect_date_format_reports_the_offending_value() -> None:
    with pytest.raises(StatementError, match="'2026-13-45'"):
        detect_date_format(["2026-01-02", "2026-13-45"], ["%Y-%m-%d"])


def test_read_default_layout(fixtures: Path) -> None:
    rows = read_statement(fixtures / "simple.csv")
    assert len(rows) == 9  # the blank line is skipped
    first = rows[0]
    assert first.date == date(2026, 2, 3)
    assert first.description == "Corner Grocer 118"
    assert first.amount == Decimal("-42.10")
    assert first.line == 2
    quoted = next(r for r in rows if r.description.startswith("Hardware"))
    assert quoted.description == "Hardware Barn, aisle 4"
    assert quoted.line == 10


def test_read_semicolon_decimal_comma_layout(fixtures: Path) -> None:
    mapping = ColumnMapping(
        date="data", description="Histórico", amount="VALOR (R$)", decimal=COMMA
    )
    rows = read_statement(fixtures / "semicolon_comma.csv", mapping)
    assert [r.amount for r in rows] == [
        Decimal("-12.50"),
        Decimal("4850.00"),
        Decimal("-1234.56"),
        Decimal("-20.00"),
    ]
    assert rows[0].date == date(2026, 3, 5)
    assert rows[3].description == "Ônibus; recarga"


def test_read_tab_separated_month_first_layout(fixtures: Path) -> None:
    mapping = ColumnMapping(date="Posted", description="Memo", amount="Value")
    rows = read_statement(fixtures / "us_tabs.tsv", mapping)
    assert [(r.date, r.amount) for r in rows] == [
        (date(2026, 3, 4), Decimal("-89.95")),
        (date(2026, 3, 25), Decimal("15.00")),
    ]


def test_explicit_delimiter_and_date_format(tmp_path: Path) -> None:
    path = tmp_path / "pipe.csv"
    path.write_text("when|what|how much\n2026/07/01|Thing|1.00\n", encoding="utf-8")
    mapping = ColumnMapping(
        date="when",
        description="what",
        amount="how much",
        delimiter="|",
        date_formats=("%Y/%m/%d",),
    )
    assert read_statement(path, mapping)[0].date == date(2026, 7, 1)


def test_missing_column_lists_available_columns(fixtures: Path) -> None:
    with pytest.raises(StatementError, match=r"'Betrag' not found.*date, description, amount"):
        read_statement(fixtures / "simple.csv", ColumnMapping(amount="Betrag"))


def test_bad_amount_reports_file_and_line(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("date,description,amount\n2026-01-01,ok,1\n2026-01-02,bad,abc\n", "utf-8")
    with pytest.raises(StatementError, match=r"bad\.csv, line 3: 'abc' is not a valid amount"):
        read_statement(path)


def test_short_row_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "short.csv"
    path.write_text("date,description,amount\n2026-01-01,only two\n", "utf-8")
    with pytest.raises(StatementError, match="line 2: expected at least 3 columns"):
        read_statement(path)


def test_empty_and_header_only_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("", "utf-8")
    with pytest.raises(StatementError, match="the file is empty"):
        read_statement(empty)
    header_only = tmp_path / "header.csv"
    header_only.write_text("date,description,amount\n\n", "utf-8")
    assert read_statement(header_only) == []


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(StatementError, match="file not found"):
        read_statement(tmp_path / "nope.csv")


def test_wrong_encoding(tmp_path: Path) -> None:
    path = tmp_path / "latin1.csv"
    path.write_bytes("date,description,amount\n2026-01-01,Café,1\n".encode("latin-1"))
    with pytest.raises(StatementError, match="could not read file"):
        read_statement(path)
    rows = read_statement(path, ColumnMapping(encoding="latin-1"))
    assert rows[0].description == "Café"


def test_errors_are_translated(tmp_path: Path) -> None:
    activate("pt_BR")
    with pytest.raises(StatementError, match="arquivo não encontrado"):
        read_statement(tmp_path / "nope.csv")


def test_read_statements_merges_and_sorts(tmp_path: Path) -> None:
    a = tmp_path / "a.csv"
    b = tmp_path / "b.csv"
    a.write_text("date,description,amount\n2026-05-03,late,1\n", "utf-8")
    b.write_text("date,description,amount\n2026-05-01,early,2\n", "utf-8")
    assert [t.description for t in read_statements([a, b])] == ["early", "late"]


def test_parse_iso_month() -> None:
    assert parse_iso_month(" 2026-03 ") == date(2026, 3, 1)
    with pytest.raises(ValueError, match="2026-3x"):
        parse_iso_month("2026-3x")
