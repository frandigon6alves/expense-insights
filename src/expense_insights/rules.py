"""User-defined categorization rules, loaded from a TOML file.

Example::

    currency = "EUR"

    [csv]
    date = "Booking date"
    decimal = "comma"

    [[category]]
    name = "Groceries"
    keywords = ["supermarket", "mercado"]
    patterns = ['^LIDL\\b']
    max_amount = 0

Rules are tried in file order and the first match wins.
"""

from __future__ import annotations

import re
import tomllib
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from expense_insights.i18n import _
from expense_insights.models import Categorized, Transaction
from expense_insights.parsing import ColumnMapping, DecimalSeparator

_CSV_STRING_KEYS = ("date", "description", "amount", "delimiter", "encoding")
_CATEGORY_KEYS = frozenset({"name", "keywords", "patterns", "min_amount", "max_amount"})


class RulesError(Exception):
    """The rules file is missing or invalid; the message is already translated."""


def fold(text: str) -> str:
    """Case- and accent-insensitive form of ``text`` used for keyword matching."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@dataclass(frozen=True)
class Rule:
    """One ``[[category]]`` block.

    A rule matches when the description contains any keyword *or* matches any
    pattern (if keywords/patterns are given) *and* the amount lies within
    ``[min_amount, max_amount]`` (if bounds are given).
    """

    category: str
    keywords: tuple[str, ...] = ()
    patterns: tuple[re.Pattern[str], ...] = ()
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    _folded_keywords: tuple[str, ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_folded_keywords", tuple(fold(k) for k in self.keywords))

    def matches(self, transaction: Transaction) -> bool:
        if self.min_amount is not None and transaction.amount < self.min_amount:
            return False
        if self.max_amount is not None and transaction.amount > self.max_amount:
            return False
        if not self.keywords and not self.patterns:
            return True
        folded = fold(transaction.description)
        return any(k in folded for k in self._folded_keywords) or any(
            p.search(transaction.description) for p in self.patterns
        )


@dataclass(frozen=True)
class RulesConfig:
    """Everything a rules file can configure."""

    rules: tuple[Rule, ...] = ()
    currency: str | None = None
    csv: Mapping[str, Any] = field(default_factory=dict)

    def column_mapping(self, overrides: Mapping[str, Any] | None = None) -> ColumnMapping:
        """Combine the ``[csv]`` section with command-line ``overrides`` (which win)."""
        values: dict[str, Any] = dict(self.csv)
        values.update({k: v for k, v in (overrides or {}).items() if v is not None})
        return ColumnMapping(**values)


def categorize(transactions: Iterable[Transaction], rules: Iterable[Rule]) -> list[Categorized]:
    """Assign each transaction the category of the first matching rule."""
    rule_list = list(rules)
    return [
        Categorized(tx, next((r.category for r in rule_list if r.matches(tx)), None))
        for tx in transactions
    ]


def load_rules(path: Path) -> RulesConfig:
    """Load and validate a rules file."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle, parse_float=Decimal)
    except FileNotFoundError:
        raise RulesError(_("Rules file not found: {path}").format(path=path)) from None
    except tomllib.TOMLDecodeError as exc:
        raise RulesError(
            _("{path}: invalid TOML ({error}).").format(path=path, error=exc)
        ) from None
    return parse_rules(data, source=str(path))


def parse_rules(data: Mapping[str, Any], source: str = "rules") -> RulesConfig:
    """Validate the decoded TOML document and build a :class:`RulesConfig`."""
    currency = data.get("currency")
    if currency is not None and not (isinstance(currency, str) and len(currency) == 3):
        raise RulesError(
            _("{source}: 'currency' must be a three-letter code such as \"EUR\".").format(
                source=source
            )
        )
    blocks = data.get("category", [])
    if not isinstance(blocks, list):
        raise RulesError(
            _("{source}: use [[category]] blocks to define categories.").format(source=source)
        )
    rules = tuple(_parse_rule(block, index, source) for index, block in enumerate(blocks, 1))
    return RulesConfig(
        rules=rules,
        currency=currency.upper() if currency else None,
        csv=_parse_csv_section(data.get("csv", {}), source),
    )


def _parse_csv_section(section: Any, source: str) -> dict[str, Any]:
    if not isinstance(section, dict):
        raise RulesError(_("{source}: [csv] must be a table.").format(source=source))
    unknown = set(section) - {*_CSV_STRING_KEYS, "decimal", "date_formats"}
    if unknown:
        raise RulesError(
            _("{source}: unknown key(s) in [csv]: {keys}.").format(
                source=source, keys=", ".join(sorted(unknown))
            )
        )
    values: dict[str, Any] = {}
    for key in _CSV_STRING_KEYS:
        if key in section:
            if not isinstance(section[key], str) or not section[key]:
                raise RulesError(
                    _("{source}: [csv] {key} must be a non-empty string.").format(
                        source=source, key=key
                    )
                )
            values[key] = section[key]
    if "decimal" in section:
        try:
            values["decimal"] = DecimalSeparator(section["decimal"])
        except ValueError:
            raise RulesError(
                _('{source}: [csv] decimal must be "point" or "comma".').format(source=source)
            ) from None
    if "date_formats" in section:
        formats = section["date_formats"]
        if not (isinstance(formats, list) and formats and all(isinstance(f, str) for f in formats)):
            raise RulesError(
                _("{source}: [csv] date_formats must be a list of strings.").format(source=source)
            )
        values["date_formats"] = tuple(formats)
    return values


def _parse_rule(block: Any, index: int, source: str) -> Rule:
    if not isinstance(block, dict):  # pragma: no cover - TOML arrays of tables are always dicts
        raise RulesError(
            _("{source}: category #{index} is not a table.").format(source=source, index=index)
        )
    where = _("{source}: category #{index}").format(source=source, index=index)
    unknown = set(block) - _CATEGORY_KEYS
    if unknown:
        raise RulesError(
            _("{where}: unknown key(s): {keys}.").format(
                where=where, keys=", ".join(sorted(unknown))
            )
        )
    name = block.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RulesError(_("{where}: 'name' is required.").format(where=where))

    keywords = _string_list(block, "keywords", where)
    patterns: list[re.Pattern[str]] = []
    for pattern in _string_list(block, "patterns", where):
        try:
            patterns.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise RulesError(
                _("{where}: invalid pattern {pattern!r} ({error}).").format(
                    where=where, pattern=pattern, error=exc
                )
            ) from None

    min_amount = _amount(block, "min_amount", where)
    max_amount = _amount(block, "max_amount", where)
    if min_amount is not None and max_amount is not None and min_amount > max_amount:
        raise RulesError(_("{where}: min_amount is greater than max_amount.").format(where=where))
    if not keywords and not patterns and min_amount is None and max_amount is None:
        raise RulesError(
            _("{where}: add keywords, patterns or an amount range.").format(where=where)
        )
    return Rule(
        category=name.strip(),
        keywords=tuple(keywords),
        patterns=tuple(patterns),
        min_amount=min_amount,
        max_amount=max_amount,
    )


def _string_list(block: Mapping[str, Any], key: str, where: str) -> list[str]:
    value = block.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        raise RulesError(
            _("{where}: '{key}' must be a list of non-empty strings.").format(where=where, key=key)
        )
    return value


def _amount(block: Mapping[str, Any], key: str, where: str) -> Decimal | None:
    value = block.get(key)
    if value is None:
        return None
    amount: Decimal | None = None
    if isinstance(value, int | Decimal) and not isinstance(value, bool):
        amount = Decimal(value)
    elif isinstance(value, str):
        try:
            amount = Decimal(value.strip())
        except ArithmeticError:
            amount = None
    if amount is not None and amount.is_finite():
        return amount
    raise RulesError(_("{where}: '{key}' must be a number.").format(where=where, key=key))
