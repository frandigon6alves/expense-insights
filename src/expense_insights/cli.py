"""Command-line entry point: ``expense-insights``."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path
from typing import NoReturn, TextIO

from babel import Locale

from expense_insights import __version__
from expense_insights.i18n import Formatter, _, activate, resolve_locale
from expense_insights.parsing import (
    DecimalSeparator,
    StatementError,
    parse_iso_month,
    read_statements,
)
from expense_insights.render import OutputFormat, render
from expense_insights.report import build_report
from expense_insights.rules import RulesConfig, RulesError, categorize, load_rules

PROG = "expense-insights"
DEFAULT_CURRENCY = "USD"
EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    def add_usage(
        self,
        usage: str | None,
        actions: Iterable[argparse.Action],
        groups: Iterable[argparse._MutuallyExclusiveGroup],
        prefix: str | None = None,
    ) -> None:
        super().add_usage(usage, actions, groups, prefix or _("usage: "))


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(
            EXIT_USAGE, _("{prog}: error: {message}").format(prog=self.prog, message=message) + "\n"
        )


def _lang_from_argv(argv: Sequence[str]) -> str | None:
    """Find ``--lang`` before the real parser exists, so that its help text is translated."""
    for index, arg in enumerate(argv):
        if arg == "--":
            break
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
        if arg == "--lang" and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _output_format(value: str) -> OutputFormat:
    try:
        return OutputFormat(value.lower())
    except ValueError:
        raise argparse.ArgumentTypeError(
            _("choose one of: {choices}").format(choices=", ".join(f.value for f in OutputFormat))
        ) from None


def _decimal_separator(value: str) -> DecimalSeparator:
    try:
        return DecimalSeparator(value.lower())
    except ValueError:
        raise argparse.ArgumentTypeError(_('use "point" or "comma"')) from None


def _month(value: str) -> date:
    try:
        return parse_iso_month(value)
    except ValueError:
        raise argparse.ArgumentTypeError(_("expected a month like 2026-03")) from None


def _positive_int(value: str) -> int:
    if value.isdigit() and int(value) > 0:
        return int(value)
    raise argparse.ArgumentTypeError(_("expected a positive whole number"))


def _currency(value: str) -> str:
    if len(value) == 3 and value.isalpha():
        return value.upper()
    raise argparse.ArgumentTypeError(_("expected a three-letter currency code such as EUR"))


def _delimiter(value: str) -> str:
    value = "\t" if value in {"\\t", "tab", "TAB"} else value
    if len(value) == 1:
        return value
    raise argparse.ArgumentTypeError(_("the delimiter must be a single character"))


def build_parser() -> argparse.ArgumentParser:
    """Build the parser. Call after :func:`activate` so the help text is translated."""
    parser = _Parser(
        prog=PROG,
        add_help=False,
        exit_on_error=False,
        formatter_class=_HelpFormatter,
        description=_(
            "Categorize bank-statement CSV exports with your own rules and print a "
            "monthly report: totals per category, change from the previous month, "
            "top merchants and uncategorized transactions."
        ),
        epilog=_("Example:\n  {prog} statement.csv --rules rules.toml --month 2026-03").format(
            prog=PROG
        ),
    )
    inputs = parser.add_argument_group(_("Input"))
    inputs.add_argument(
        "statements",
        nargs="*",
        type=Path,
        metavar=_("STATEMENT.csv"),
        help=_("one or more CSV exports from your bank"),
    )
    inputs.add_argument(
        "-r",
        "--rules",
        type=Path,
        metavar=_("FILE"),
        help=_("TOML file with categories, matching rules and CSV settings"),
    )

    report = parser.add_argument_group(_("Report"))
    report.add_argument(
        "-m",
        "--month",
        type=_month,
        metavar=_("YYYY-MM"),
        help=_("month to report on (default: the latest month in the data)"),
    )
    report.add_argument(
        "-f",
        "--format",
        type=_output_format,
        default=OutputFormat.TABLE,
        metavar="{table,markdown,json}",
        help=_("output format (default: table)"),
    )
    report.add_argument(
        "-n",
        "--top",
        type=_positive_int,
        default=5,
        metavar=_("N"),
        help=_("how many top merchants to list (default: 5)"),
    )
    report.add_argument(
        "--currency",
        type=_currency,
        metavar=_("CODE"),
        help=_("ISO 4217 currency of the amounts (default: from the rules file, else USD)"),
    )
    report.add_argument(
        "--lang",
        metavar=_("LANG"),
        help=_("language and number/date format, e.g. en, es, pt_BR (default: $LANG)"),
    )

    columns = parser.add_argument_group(
        _("CSV layout"), _("These options override the [csv] section of the rules file.")
    )
    columns.add_argument(
        "--date-col", dest="date", metavar=_("NAME"), help=_("date column (default: date)")
    )
    columns.add_argument(
        "--description-col",
        dest="description",
        metavar=_("NAME"),
        help=_("description column (default: description)"),
    )
    columns.add_argument(
        "--amount-col", dest="amount", metavar=_("NAME"), help=_("amount column (default: amount)")
    )
    columns.add_argument(
        "--decimal",
        type=_decimal_separator,
        metavar="{point,comma}",
        help=_("decimal separator used in amounts (default: point)"),
    )
    columns.add_argument(
        "--date-format",
        dest="date_formats",
        action="append",
        metavar=_("FORMAT"),
        help=_("strftime date format, may be repeated (default: try common formats)"),
    )
    columns.add_argument(
        "--delimiter",
        type=_delimiter,
        metavar=_("CHAR"),
        help=_("field delimiter (default: detected)"),
    )
    columns.add_argument("--encoding", metavar=_("NAME"), help=_("file encoding (default: utf-8)"))

    misc = parser.add_argument_group(_("Other"))
    misc.add_argument("-h", "--help", action="help", help=_("show this help and exit"))
    misc.add_argument(
        "--version",
        action="version",
        version=f"{PROG} {__version__}",
        help=_("show the version and exit"),
    )
    return parser


def run(args: argparse.Namespace, formatter_locale: Locale, stdout: TextIO) -> int:
    config = load_rules(args.rules) if args.rules else RulesConfig()
    overrides = {
        key: getattr(args, key)
        for key in ("date", "description", "amount", "decimal", "delimiter", "encoding")
    }
    overrides["date_formats"] = tuple(args.date_formats) if args.date_formats else None
    transactions = read_statements(args.statements, config.column_mapping(overrides))
    if not transactions:
        raise StatementError(_("No transactions found."))
    items = categorize(transactions, config.rules)

    report = build_report(items, month=args.month, top=args.top)
    if report.transaction_count == 0:
        raise StatementError(
            _("No transactions in {month}. Months in the data: {months}.").format(
                month=report.month.strftime("%Y-%m"),
                months=", ".join(m.strftime("%Y-%m") for m in report.months),
            )
        )
    currency = args.currency or config.currency or DEFAULT_CURRENCY
    fmt = Formatter(locale=formatter_locale, currency=currency)
    stdout.write(render(report, args.format, fmt))
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    choice = resolve_locale(_lang_from_argv(arguments))
    activate(choice.language)

    parser = build_parser()
    try:
        args, unknown = parser.parse_known_args(arguments)
    except argparse.ArgumentError as exc:
        # exit_on_error=False lets us translate the "argument --x: ..." prefix ourselves.
        parser.error(
            _("argument {name}: {message}").format(name=exc.argument_name, message=exc.message)
            if exc.argument_name
            else exc.message
        )
    if unknown:
        parser.error(_("unrecognized arguments: {args}").format(args=" ".join(unknown)))
    if not args.statements:
        parser.error(_("give at least one statement CSV file"))
    try:
        return run(args, choice.formatting, sys.stdout)
    except (StatementError, RulesError) as exc:
        print(_("{prog}: error: {message}").format(prog=PROG, message=exc), file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
