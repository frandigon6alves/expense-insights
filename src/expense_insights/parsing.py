"""Reading bank-statement CSV exports into :class:`Transaction` objects.

Banks disagree on almost everything: column names, delimiters, decimal
separators and date formats. :class:`ColumnMapping` describes one layout; the
defaults match a plain ``date,description,amount`` file.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path

from expense_insights.i18n import _
from expense_insights.models import Transaction

DEFAULT_DATE_FORMATS: tuple[str, ...] = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d.%m.%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
)

_SNIFF_DELIMITERS = ",;\t|"
_NUMBER = re.compile(r"\d+(\.\d+)?")
_NEGATIVE_MARKERS = ("-", "\u2212")  # ASCII hyphen-minus and the Unicode minus sign


class DecimalSeparator(StrEnum):
    POINT = "point"
    COMMA = "comma"


class StatementError(Exception):
    """A statement file could not be read; the message is already translated."""


@dataclass(frozen=True)
class ColumnMapping:
    """Where to find each field in a CSV export and how to read it."""

    date: str = "date"
    description: str = "description"
    amount: str = "amount"
    decimal: DecimalSeparator = DecimalSeparator.POINT
    date_formats: tuple[str, ...] = DEFAULT_DATE_FORMATS
    delimiter: str | None = None
    encoding: str = "utf-8-sig"


def parse_amount(text: str, decimal: DecimalSeparator = DecimalSeparator.POINT) -> Decimal:
    """Parse a money amount such as ``-1,234.50``, ``1.234,50-``, ``(12.00)`` or ``€ 9,99``.

    Raises :class:`ValueError` if the text is not a number.
    """
    raw = text.strip()
    negative = False
    if raw.startswith("(") and raw.endswith(")"):
        negative, raw = True, raw[1:-1].strip()
    # Drop currency symbols/codes and any kind of whitespace, keep digits, separators and signs.
    raw = "".join(ch for ch in raw if ch.isdigit() or ch in ".,'+" or ch in _NEGATIVE_MARKERS)
    if raw.startswith(_NEGATIVE_MARKERS):
        negative, raw = not negative, raw[1:]
    elif raw.endswith(_NEGATIVE_MARKERS):
        negative, raw = not negative, raw[:-1]
    raw = raw.removeprefix("+").replace("'", "")
    if decimal is DecimalSeparator.COMMA:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", "")
    if not _NUMBER.fullmatch(raw):
        raise ValueError(text)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:  # pragma: no cover - guarded by the regex above
        raise ValueError(text) from exc
    return -value if negative else value


def detect_date_format(values: Sequence[str], formats: Sequence[str]) -> str:
    """Return the first format that parses *every* value.

    Checking the whole column (instead of row by row) resolves ``03/04/2026``
    correctly as soon as one row such as ``25/04/2026`` rules out month-first.
    """
    for fmt in formats:
        try:
            for value in values:
                datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
        return fmt
    sample = next(
        (v for v in values if not any(_parses(v, f) for f in formats)), values[0] if values else ""
    )
    raise StatementError(
        _("Could not understand the date {value!r}. Tried formats: {formats}.").format(
            value=sample, formats=", ".join(formats)
        )
    )


def _parses(value: str, fmt: str) -> bool:
    try:
        datetime.strptime(value.strip(), fmt)
    except ValueError:
        return False
    return True


def _find_column(header: Sequence[str], wanted: str, path: Path) -> int:
    normalized = [name.strip().casefold() for name in header]
    try:
        return normalized.index(wanted.strip().casefold())
    except ValueError:
        raise StatementError(
            _("{path}: column {column!r} not found. Available columns: {available}.").format(
                path=path, column=wanted, available=", ".join(h.strip() for h in header)
            )
        ) from None


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=_SNIFF_DELIMITERS).delimiter
    except csv.Error:
        return ","


def read_statement(path: Path, mapping: ColumnMapping | None = None) -> list[Transaction]:
    """Read one CSV export. Blank lines are skipped; any other bad row is an error."""
    mapping = mapping or ColumnMapping()
    try:
        text = path.read_text(encoding=mapping.encoding)
    except FileNotFoundError:
        raise StatementError(_("{path}: file not found.").format(path=path)) from None
    except (OSError, UnicodeDecodeError) as exc:
        raise StatementError(
            _("{path}: could not read file ({error}).").format(path=path, error=exc)
        ) from None

    delimiter = mapping.delimiter or _sniff_delimiter(text[:4096])
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    header = next(reader, None)
    if header is None:
        raise StatementError(_("{path}: the file is empty.").format(path=path))
    date_col = _find_column(header, mapping.date, path)
    desc_col = _find_column(header, mapping.description, path)
    amount_col = _find_column(header, mapping.amount, path)
    width = max(date_col, desc_col, amount_col) + 1

    records: list[tuple[int, list[str]]] = []
    for row in reader:
        line_no = reader.line_num
        if not any(cell.strip() for cell in row):
            continue
        if len(row) < width:
            raise StatementError(
                _("{path}, line {line}: expected at least {count} columns.").format(
                    path=path, line=line_no, count=width
                )
            )
        records.append((line_no, row))

    if not records:
        return []

    date_format = detect_date_format([row[date_col] for _n, row in records], mapping.date_formats)
    transactions: list[Transaction] = []
    for line_no, row in records:
        try:
            amount = parse_amount(row[amount_col], mapping.decimal)
        except ValueError:
            raise StatementError(
                _("{path}, line {line}: {value!r} is not a valid amount.").format(
                    path=path, line=line_no, value=row[amount_col]
                )
            ) from None
        transactions.append(
            Transaction(
                date=datetime.strptime(row[date_col].strip(), date_format).date(),
                description=" ".join(row[desc_col].split()),
                amount=amount,
                source=str(path),
                line=line_no,
            )
        )
    return transactions


def read_statements(
    paths: Iterable[Path], mapping: ColumnMapping | None = None
) -> list[Transaction]:
    """Read several exports and return their transactions sorted by date."""
    transactions = [tx for path in paths for tx in read_statement(path, mapping)]
    return sorted(transactions, key=lambda tx: (tx.date, tx.source, tx.line))


def parse_iso_month(value: str) -> date:
    """Parse ``YYYY-MM`` into the first day of that month."""
    try:
        return datetime.strptime(value.strip(), "%Y-%m").date()
    except ValueError:
        raise ValueError(value) from None
