from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from babel import Locale
from babel.messages.catalog import Catalog, Message
from babel.messages.extract import extract_from_dir
from babel.messages.mofile import read_mo
from babel.messages.pofile import read_po

import expense_insights
from expense_insights.i18n import (
    DOMAIN,
    LOCALE_DIR,
    SUPPORTED_LANGUAGES,
    Formatter,
    _,
    activate,
    match_language,
    ngettext,
    resolve_locale,
)

SOURCE_DIR = Path(expense_insights.__file__).parent
PLACEHOLDER = re.compile(r"\{[^{}]*\}")


def _read_po(language: str) -> Catalog:
    with (LOCALE_DIR / language / "LC_MESSAGES" / f"{DOMAIN}.po").open("rb") as handle:
        return read_po(handle, locale=language)


def _template_ids() -> set[str]:
    with (LOCALE_DIR / f"{DOMAIN}.pot").open("rb") as handle:
        return {_key(m) for m in read_po(handle) if m.id}


def _key(message: Message) -> str:
    return message.id if isinstance(message.id, str) else message.id[0]


def _strings(message: Message) -> list[str]:
    value = message.string
    if value is None:
        return [""]
    return [value] if isinstance(value, str) else [s or "" for s in value]


def test_template_is_in_sync_with_the_source() -> None:
    extracted = {
        msg if isinstance(msg, str) else msg[0]
        for _file, _line, msg, _comments, _context in extract_from_dir(str(SOURCE_DIR))
    }
    assert extracted == _template_ids(), "run scripts/update-translations.sh"


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_catalogue_covers_every_message(language: str) -> None:
    catalog = _read_po(language)
    translated = {_key(m): m for m in catalog if m.id}
    missing = _template_ids() - translated.keys()
    assert not missing, f"{language} is missing: {sorted(missing)}"
    for msgid in _template_ids():
        message = translated[msgid]
        assert not message.fuzzy, f"{language}: fuzzy translation for {msgid!r}"
        assert all(_strings(message)), f"{language}: empty translation for {msgid!r}"


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_translations_keep_placeholders(language: str) -> None:
    for message in _read_po(language):
        if not message.id:
            continue
        expected = sorted(PLACEHOLDER.findall(_key(message)))
        for string in _strings(message):
            assert sorted(PLACEHOLDER.findall(string)) == expected, (language, message.id)


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_compiled_catalogue_matches_source(language: str) -> None:
    with (LOCALE_DIR / language / "LC_MESSAGES" / f"{DOMAIN}.mo").open("rb") as handle:
        compiled = {_key(m): _strings(m) for m in read_mo(handle) if m.id}
    source = {_key(m): _strings(m) for m in _read_po(language) if m.id}
    assert compiled == source, "run scripts/update-translations.sh to recompile the .mo files"


def test_activate_switches_language() -> None:
    assert _("Income") == "Income"
    activate("es")
    assert _("Income") == "Ingresos"
    activate("pt_BR")
    assert _("Income") == "Receitas"
    activate("xx")
    assert _("Income") == "Income"


def test_plural_forms() -> None:
    template = (
        "{count} transaction, compared with {previous}",
        "{count} transactions, compared with {previous}",
    )
    activate("pt_BR")
    assert ngettext(*template, 1).startswith("{count} transação")
    assert ngettext(*template, 0).startswith("{count} transação")  # pt_BR: 0 is singular
    assert ngettext(*template, 2).startswith("{count} transações")
    activate("es")
    assert ngettext(*template, 0).startswith("{count} movimientos")


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("es", "es"),
        ("es_MX.UTF-8", "es"),
        ("pt-br", "pt_BR"),
        ("pt_PT", "pt_BR"),
        ("en_GB@euro", "en"),
        ("de_DE", None),
        ("C", None),
        ("POSIX", None),
        ("", None),
    ],
)
def test_match_language(tag: str, expected: str | None) -> None:
    assert match_language(tag) == expected


def test_resolve_locale_precedence() -> None:
    env = {"LANG": "pt_BR.UTF-8", "LC_ALL": "es_ES.UTF-8"}
    assert resolve_locale("en", env).language == "en"
    assert resolve_locale(None, env).language == "es"
    assert resolve_locale(None, {"LANG": "pt_BR.UTF-8"}).language == "pt_BR"
    assert resolve_locale(None, {}).language == "en"


def test_resolve_locale_keeps_regional_formatting() -> None:
    choice = resolve_locale("es_MX")
    assert choice.language == "es"
    assert str(choice.formatting) == "es_MX"


def test_resolve_locale_falls_back_for_unsupported_languages() -> None:
    choice = resolve_locale(None, {"LANG": "de_DE.UTF-8"})
    assert (choice.language, str(choice.formatting)) == ("en", "en")
    assert str(resolve_locale("zz_ZZ").formatting) == "en"
    assert resolve_locale("es_ZZ").formatting.language == "es"


@pytest.mark.parametrize(
    ("locale", "currency", "money", "percent", "day", "month"),
    [
        ("en", "USD", "-$1,234.50", "+12.5%", "Mar 9, 2026", "March 2026"),
        ("es", "EUR", "-1.234,50\u00a0€", "+12,5\u00a0%", "9 mar 2026", "marzo de 2026"),
        ("pt_BR", "BRL", "-R$\u00a01.234,50", "+12,5%", "9 de mar. de 2026", "março de 2026"),
    ],
)
def test_formatter(
    locale: str, currency: str, money: str, percent: str, day: str, month: str
) -> None:
    fmt = Formatter(Locale.parse(locale), currency)
    assert fmt.money(Decimal("-1234.50")) == money
    assert fmt.percent(Decimal("0.125")) == percent
    assert fmt.day(date(2026, 3, 9)) == day
    assert fmt.month(date(2026, 3, 9)) == month


def test_formatter_negative_percent_and_integers() -> None:
    fmt = Formatter(Locale.parse("pt_BR"), "BRL")
    assert fmt.percent(Decimal("-0.5")) == "-50,0%"
    assert fmt.integer(12345) == "12.345"
