from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from expense_insights.models import Transaction
from expense_insights.parsing import DecimalSeparator
from expense_insights.rules import (
    Rule,
    RulesConfig,
    RulesError,
    categorize,
    fold,
    load_rules,
    parse_rules,
)


def tx(description: str, amount: str) -> Transaction:
    return Transaction(date(2026, 3, 1), description, Decimal(amount))


def test_fold_ignores_case_and_accents() -> None:
    assert fold("PADARIA São JOÃO") == "padaria sao joao"
    assert fold("Straße") == "strasse"


def test_keyword_match_is_case_and_accent_insensitive() -> None:
    rule = Rule("Bakery", keywords=("padaria sao joao",))
    assert rule.matches(tx("PADARIA SÃO JOÃO 12", "-3.00"))
    assert not rule.matches(tx("Padaria Central", "-3.00"))


def test_pattern_match() -> None:
    rule = Rule("Coffee", patterns=(re.compile(r"\bbean\b", re.IGNORECASE),))
    assert rule.matches(tx("Blue BEAN Coffee", "-4"))
    assert not rule.matches(tx("Beanstalk", "-4"))


def test_amount_range_is_inclusive_and_combined_with_text() -> None:
    rule = Rule("Fuel", keywords=("gas",), min_amount=Decimal(-80), max_amount=Decimal(-10))
    assert rule.matches(tx("Gas station", "-80"))
    assert rule.matches(tx("Gas station", "-10"))
    assert not rule.matches(tx("Gas station", "-80.01"))
    assert not rule.matches(tx("Gas station", "-9.99"))
    assert not rule.matches(tx("Bakery", "-20"))


def test_amount_only_rule_matches_any_description() -> None:
    rule = Rule("Large", max_amount=Decimal(-100))
    assert rule.matches(tx("Anything", "-150"))
    assert not rule.matches(tx("Anything", "-50"))


def test_first_matching_rule_wins() -> None:
    rules = [Rule("Groceries", keywords=("market",)), Rule("Large", max_amount=Decimal(-100))]
    result = categorize([tx("Market", "-150"), tx("TV shop", "-500"), tx("Kiosk", "-2")], rules)
    assert [item.category for item in result] == ["Groceries", "Large", None]


def test_load_example_rules(examples: Path) -> None:
    config = load_rules(examples / "rules.toml")
    assert config.currency == "EUR"
    assert [r.category for r in config.rules][:3] == ["Salary", "Transfers", "Housing"]
    salary = config.rules[0]
    assert salary.min_amount == Decimal(0)
    big = config.rules[-1]
    assert big.max_amount == Decimal(-200)
    assert config.column_mapping().date == "Date"


def test_float_amounts_are_read_as_decimal(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text('[[category]]\nname = "Small"\nmin_amount = -0.1\nmax_amount = "0.10"\n')
    rule = load_rules(path).rules[0]
    assert rule.min_amount == Decimal("-0.1")
    assert rule.max_amount == Decimal("0.10")


def test_column_mapping_overrides_win() -> None:
    config = parse_rules(
        {"csv": {"date": "Booking", "decimal": "comma", "date_formats": ["%d.%m.%Y"]}}
    )
    mapping = config.column_mapping({"date": "Posted", "amount": None})
    assert mapping.date == "Posted"
    assert mapping.amount == "amount"
    assert mapping.decimal is DecimalSeparator.COMMA
    assert mapping.date_formats == ("%d.%m.%Y",)


def test_empty_config_is_valid() -> None:
    assert parse_rules({}) == RulesConfig()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"currency": "euro"}, "three-letter code"),
        ({"category": {"name": "x"}}, r"use \[\[category\]\] blocks"),
        ({"category": [{"name": "x", "keyword": ["a"]}]}, r"unknown key\(s\): keyword"),
        ({"category": [{"keywords": ["a"]}]}, "'name' is required"),
        ({"category": [{"name": "  "}]}, "'name' is required"),
        ({"category": [{"name": "x"}]}, "add keywords, patterns or an amount range"),
        ({"category": [{"name": "x", "keywords": "a"}]}, "'keywords' must be a list"),
        ({"category": [{"name": "x", "patterns": [""]}]}, "'patterns' must be a list"),
        ({"category": [{"name": "x", "patterns": ["("]}]}, "invalid pattern '\\('"),
        ({"category": [{"name": "x", "min_amount": "abc"}]}, "'min_amount' must be a number"),
        ({"category": [{"name": "x", "max_amount": True}]}, "'max_amount' must be a number"),
        ({"category": [{"name": "x", "max_amount": "NaN"}]}, "'max_amount' must be a number"),
        (
            {"category": [{"name": "x", "min_amount": 5, "max_amount": 1}]},
            "min_amount is greater than max_amount",
        ),
        ({"csv": []}, r"\[csv\] must be a table"),
        ({"csv": {"colour": "x"}}, r"unknown key\(s\) in \[csv\]: colour"),
        ({"csv": {"date": ""}}, r"\[csv\] date must be a non-empty string"),
        ({"csv": {"decimal": "dot"}}, r"\[csv\] decimal must be"),
        ({"csv": {"date_formats": "%Y"}}, r"\[csv\] date_formats must be a list"),
    ],
)
def test_invalid_rules(data: dict[str, Any], message: str) -> None:
    with pytest.raises(RulesError, match=message):
        parse_rules(data)


def test_error_mentions_the_category_position() -> None:
    with pytest.raises(RulesError, match=r"my\.toml: category #2"):
        parse_rules({"category": [{"name": "a", "keywords": ["a"]}, {"name": "b"}]}, "my.toml")


def test_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "broken.toml"
    path.write_text("[[category]\n")
    with pytest.raises(RulesError, match="invalid TOML"):
        load_rules(path)


def test_missing_rules_file(tmp_path: Path) -> None:
    with pytest.raises(RulesError, match="Rules file not found"):
        load_rules(tmp_path / "missing.toml")
