"""Translation and locale-aware formatting.

User-facing strings are marked with :func:`_` / :func:`ngettext` and looked up in
the gettext catalogues shipped in ``expense_insights/locales``. Numbers, money and
dates are formatted with Babel so that they follow the conventions of the active
locale (decimal separator, currency symbol position, month names, ...).
"""

from __future__ import annotations

import gettext
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from babel import Locale, UnknownLocaleError
from babel.dates import format_date, format_skeleton
from babel.numbers import format_currency, format_decimal, format_percent

DOMAIN = "expense_insights"
LOCALE_DIR = Path(__file__).parent / "locales"
DEFAULT_LANGUAGE = "en"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "es", "pt_BR")

_translations: gettext.NullTranslations = gettext.NullTranslations()


def _(message: str) -> str:
    """Translate ``message`` using the active catalogue."""
    return _translations.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Translate a message that depends on a count."""
    return _translations.ngettext(singular, plural, n)


def _normalize(tag: str) -> str:
    """Turn ``es_ES.UTF-8`` / ``pt-br`` / ``de_DE@euro`` into ``es_ES`` / ``pt_BR`` / ``de_DE``."""
    tag = tag.split(".", 1)[0].split("@", 1)[0].replace("-", "_")
    language, _sep, territory = tag.partition("_")
    return f"{language.lower()}_{territory.upper()}" if territory else language.lower()


def match_language(tag: str) -> str | None:
    """Return the supported catalogue that best matches a locale tag, if any."""
    normalized = _normalize(tag)
    if not normalized or normalized in {"c", "posix"}:
        return None
    if normalized in SUPPORTED_LANGUAGES:
        return normalized
    language = normalized.split("_", 1)[0]
    for supported in SUPPORTED_LANGUAGES:
        if supported.split("_", 1)[0] == language:
            return supported
    return None


def _env_locale(environ: Mapping[str, str]) -> str | None:
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG"):
        value = environ.get(variable)
        if value:
            return value
    return None


@dataclass(frozen=True)
class LocaleChoice:
    """The catalogue used for messages and the Babel locale used for formatting.

    They usually coincide, but ``LANG=es_MX.UTF-8`` uses the ``es`` catalogue while
    still formatting numbers and dates the Mexican way.
    """

    language: str
    formatting: Locale


def resolve_locale(cli_lang: str | None, environ: Mapping[str, str] | None = None) -> LocaleChoice:
    """Pick the locale from ``--lang`` first, then ``LC_ALL``/``LC_MESSAGES``/``LANG``."""
    env = os.environ if environ is None else environ
    requested = cli_lang or _env_locale(env) or DEFAULT_LANGUAGE
    language = match_language(requested) or DEFAULT_LANGUAGE
    try:
        formatting = Locale.parse(_normalize(requested))
    except (ValueError, UnknownLocaleError):
        formatting = Locale.parse(language)
    if formatting.language != Locale.parse(language).language:
        formatting = Locale.parse(language)
    return LocaleChoice(language=language, formatting=formatting)


def activate(language: str) -> None:
    """Load the catalogue for ``language`` (falls back to the source strings)."""
    global _translations  # noqa: PLW0603 - the active catalogue is process-wide by design
    _translations = gettext.translation(
        DOMAIN, localedir=LOCALE_DIR, languages=[language], fallback=True
    )


@dataclass(frozen=True)
class Formatter:
    """Locale-aware presentation of money, percentages and dates."""

    locale: Locale
    currency: str

    def money(self, amount: Decimal) -> str:
        return format_currency(amount, self.currency, locale=self.locale)

    def percent(self, ratio: Decimal) -> str:
        # Keep the locale's own layout (e.g. "12,5 %" in Spanish) but always show the
        # sign and one decimal place.
        base = self.locale.percent_formats[None].pattern.split(";", 1)[0]
        last_digit = base.rfind("0") + 1
        base = f"{base[:last_digit]}.0{base[last_digit:]}"
        return format_percent(ratio, f"+{base};-{base}", locale=self.locale)

    def day(self, value: date) -> str:
        return format_date(value, format="medium", locale=self.locale)

    def month(self, value: date) -> str:
        return format_skeleton("yMMMM", value, locale=self.locale)

    def integer(self, value: int) -> str:
        return format_decimal(value, locale=self.locale)
