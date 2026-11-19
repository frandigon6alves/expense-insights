# expense-insights

[![CI](https://github.com/frandigon6alves/expense-insights/actions/workflows/ci.yml/badge.svg)](https://github.com/frandigon6alves/expense-insights/actions/workflows/ci.yml)

A small command-line tool that reads the CSV export from your bank, sorts every
transaction into categories using rules **you** write in a TOML file, and prints
a monthly report: totals per category, change from the previous month, top
merchants and the transactions no rule matched.

It runs locally on files you already have: no accounts, no network, no database.
It speaks English, Spanish and Brazilian Portuguese, and formats money, numbers
and dates the way your locale expects.

## Features

- **Any CSV layout**: pick the date, description and amount columns by name,
  use a decimal point or a decimal comma, and let the tool work out the delimiter
  and date format (`2026-03-04`, `04/03/2026`, `03/04/2026`, `04.03.2026`, ...).
  The date format is chosen per file by checking the whole column, so
  `03/04/2026` is read correctly as soon as one row such as `25/04/2026` shows
  the file is day-first.
- **Rules you control**: keywords (case- and accent-insensitive), regular
  expressions and amount ranges, tried top to bottom, first match wins.
- **Monthly report**: income, expenses and net; per-category totals with the
  previous month and the relative change; top merchants (store numbers and
  references are stripped so `CAFE AURORA #12` and `CAFE AURORA #15` count as one);
  every uncategorized transaction, so you know which rule to add next.
- **Three output formats**: an aligned terminal table (default), Markdown (paste it
  into notes or an issue) and JSON (for scripts).
- **Exact money**: amounts are parsed into `decimal.Decimal` and never touch
  `float`.
- **Translated**: every message, help text and error goes through gettext, with
  catalogues for `en`, `es` and `pt_BR`; numbers, currencies and dates are
  formatted with [Babel](https://babel.pocoo.org/).

## Install

Python 3.12 or newer. From a clone of this repository:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install .
expense-insights --help
```

The only runtime dependency is Babel.

## Usage

```text
expense-insights STATEMENT.csv [STATEMENT.csv ...] [--rules FILE] [options]
```

| Option | What it does |
| --- | --- |
| `-r, --rules FILE` | Rules file (categories, CSV layout, currency). Optional: without it everything is uncategorized. |
| `-m, --month YYYY-MM` | Month to report on. Default: the latest month in the data. |
| `-f, --format table\|markdown\|json` | Output format. Default: `table`. |
| `-n, --top N` | How many top merchants to list. Default: 5. |
| `--currency CODE` | ISO 4217 code of the amounts. Default: from the rules file, else `USD`. |
| `--lang LANG` | Language and formatting locale, e.g. `en`, `es`, `pt_BR`, `es_MX`. Default: `$LC_ALL`, `$LC_MESSAGES`, then `$LANG`. |
| `--date-col`, `--description-col`, `--amount-col NAME` | Column names (matched case-insensitively). Defaults: `date`, `description`, `amount`. |
| `--decimal point\|comma` | Decimal separator in amounts. Default: `point`. |
| `--date-format FORMAT` | `strftime` format; repeat it to try several. Default: a list of common formats. |
| `--delimiter CHAR` | Field delimiter (`tab` is accepted). Default: detected. |
| `--encoding NAME` | File encoding. Default: `utf-8` (a BOM is fine). |

Several files can be passed at once (for example, two accounts, or one export
per month); their transactions are merged before the report is built. Amounts
are signed: money leaving the account is negative. Amounts like `1,234.50`,
`(12.00)`, `45.00-`, `€ 9,99` and `R$ 4.850,00` are understood.

Exit codes: `0` success, `1` the data or rules could not be read, `2` invalid
command-line usage.

### Example

Everything in [`examples/`](examples/) is invented, so you can reproduce this
output exactly:

```console
$ expense-insights examples/statement.csv --rules examples/rules.toml
Expense report for October 2026
===============================
20 transactions, compared with September 2026

Income     €3,212.50
Expenses  -€2,150.77
Net        €1,061.73

By category
Category       Count  This month  Last month   Change
-------------  -----  ----------  ----------  -------
Housing            2  -€1,238.45  -€1,221.20    +1.4%
Groceries          5    -€369.03    -€345.46    +6.8%
Big purchases      1    -€249.00       €0.00      new
Eating out         4     -€83.20     -€64.70   +28.6%
Transport          2     -€80.00     -€40.00  +100.0%
Subscriptions      2     -€47.99     -€47.99    +0.0%
Health             1     -€23.70     -€18.25   +29.9%
Transfers          0       €0.00     €200.00  -100.0%
Salary             1   €3,200.00   €3,200.00    +0.0%
Uncategorized      2     -€46.90       €0.00      new

Top merchants
#  Merchant                    Count       Spent
-  --------------------------  -----  ----------
1  Oak Street Apartments Rent      1  -€1,150.00
2  Greenleaf Market                4    -€381.53
3  Electro Hub Online Order        1    -€249.00
4  Lumen Energy Bill               1     -€88.45
5  Metro Transit Card Topup        2     -€80.00

Uncategorized transactions (2)
Date          Description        Amount
------------  ----------------  -------
Oct 7, 2026   BOOKWORM STORE    -€32.90
Oct 26, 2026  PIXEL PRINT SHOP  -€14.00
```

**Change** compares magnitudes: `+6.8%` on Groceries means 6.8% *more* was
spent than last month, and the same sign convention applies to income. It shows
`new` when there was nothing in that category last month, and `—` when the data
does not cover the previous month at all.

The same rules on a differently shaped export (semicolons, decimal comma,
`dd.mm.yyyy` dates, German column names), reported in Spanish:

```console
$ expense-insights examples/statement-eu.csv -r examples/rules.toml \
    --date-col Buchungstag --description-col Verwendungszweck --amount-col "Betrag (EUR)" \
    --decimal comma --date-format %d.%m.%Y --lang es --top 3
Informe de gastos de octubre de 2026
====================================
6 movimientos, comparados con septiembre de 2026

Ingresos     3.200,00 €
Gastos      -1.515,80 €
Saldo neto   1.684,20 €

Por categoría
Categoría      Mov.     Este mes  Mes anterior  Variación
-------------  ----  -----------  ------------  ---------
Housing           1  -1.150,00 €             —          —
Big purchases     1    -249,00 €             —          —
Groceries         1     -95,60 €             —          —
Eating out        1      -7,20 €             —          —
Salary            1   3.200,00 €             —          —
Sin categoría     1     -14,00 €             —          —

Comercios principales
#  Comercio                    Mov.      Gastado
-  --------------------------  ----  -----------
1  Oak Street Apartments Rent     1  -1.150,00 €
2  Electro Hub Online Order       1    -249,00 €
3  Greenleaf Market               1     -95,60 €

Movimientos sin categoría (1)
Fecha        Descripción        Importe
-----------  ----------------  --------
26 oct 2026  PIXEL PRINT SHOP  -14,00 €
```

Category names come from your rules file, so they are shown as you wrote them.

### Markdown and JSON

`--format markdown` prints the same report as Markdown tables, translated like
the terminal table. `--format json` is meant for other programs and is the same
in every language: ISO dates, `YYYY-MM` months, amounts as decimal strings (to
keep them exact), changes as ratios (`"0.0682"` = +6.82%) and `null` for the
uncategorized bucket and for missing comparisons:

```console
$ expense-insights examples/statement.csv -r examples/rules.toml -f json | head -12
{
  "month": "2026-10",
  "previous_month": "2026-09",
  "currency": "EUR",
  "transactions": 20,
  "summary": {
    "income": "3212.50",
    "expenses": "-2150.77",
    "net": "1061.73"
  },
  "categories": [
    {
```

## Rules file

A rules file is TOML with three optional parts: a `currency`, a `[csv]` table
describing the export layout, and any number of `[[category]]` blocks.

```toml
currency = "EUR"            # ISO 4217 code used to format amounts

[csv]                       # all keys optional; command-line flags override them
date = "Date"               # column names (case-insensitive)
description = "Description"
amount = "Amount"
decimal = "point"           # or "comma"
date_formats = ["%Y-%m-%d"] # tried in order; the first that fits every row wins
delimiter = ","             # detected when omitted
encoding = "utf-8"

[[category]]
name = "Salary"
keywords = ["payroll"]      # substring match, ignores case and accents
min_amount = 0              # only money coming in

[[category]]
name = "Transfers"
patterns = ['^TRANSFER (FROM|TO) ']   # Python regular expressions, case-insensitive

[[category]]
name = "Big purchases"
max_amount = -200           # no text condition: any outgoing payment of 200 or more
```

How a `[[category]]` block matches a transaction:

- If it has `keywords` and/or `patterns`, the description must contain one of
  the keywords **or** match one of the patterns.
- If it has `min_amount` and/or `max_amount`, the signed amount must be inside
  that inclusive range. Spending is negative, so "between 10 and 80 spent" is
  `min_amount = -80`, `max_amount = -10`.
- Both conditions must hold when both are given. A block needs at least one of
  them.
- Blocks are tried from top to bottom and the first match wins, so put specific
  rules before broad ones. The same `name` may appear in several blocks.

Amounts can be written as TOML numbers or strings; decimals are read exactly.
Mistakes such as unknown keys, invalid regular expressions or
`min_amount > max_amount` are reported with the file name and block number.
See [`examples/rules.toml`](examples/rules.toml) for a complete file.

## Internationalization

All text the CLI prints (report labels, help, errors) is marked with
`_()`/`ngettext()` and translated with the standard library's `gettext`. The
language is taken from `--lang`, else from `LC_ALL`, `LC_MESSAGES` or `LANG`.
Region variants fall back to the matching catalogue while keeping their own
formatting: `LANG=es_MX.UTF-8` uses the Spanish texts with Mexican number and
date conventions. Unsupported languages fall back to English.

| Code | Language |
| --- | --- |
| `en` | English (default, also the source language) |
| `es` | Spanish |
| `pt_BR` | Brazilian Portuguese |

Catalogues live in `src/expense_insights/locales/`:

```text
locales/
├── expense_insights.pot              # template extracted from the source
└── <lang>/LC_MESSAGES/
    ├── expense_insights.po           # translations (edit these)
    └── expense_insights.mo           # compiled, loaded at run time
```

**The compiled `.mo` files are committed** alongside the `.po` sources. That keeps
the build a plain Hatchling build with no compile step, so installing from a
clone or an sdist needs nothing beyond pip. The test suite keeps them honest:
it fails if the template is out of date with the source, if any catalogue is
missing a message or has an empty or fuzzy one, if a translation drops or renames
a `{placeholder}`, or if a `.mo` file does not match its `.po`.

### Adding a language

With the dev environment active (see below), for example for French:

```sh
pybabel init -D expense_insights -i src/expense_insights/locales/expense_insights.pot \
    -d src/expense_insights/locales -l fr
# translate every msgstr in src/expense_insights/locales/fr/LC_MESSAGES/expense_insights.po
./scripts/update-translations.sh          # merges and compiles the .mo
```

Then add `"fr"` to `SUPPORTED_LANGUAGES` in `src/expense_insights/i18n.py`; the
catalogue tests run for every entry in that tuple. After changing any
user-facing string in the code, run `./scripts/update-translations.sh`, fill in
the new entries and run it again.

Known limits: a few parse errors produced inside Python's `argparse` (such as
"expected one argument") are not part of this project's catalogue and stay in
English. Category and merchant names are your data and are never translated.

## Development

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

ruff check .              # lint
ruff format --check .     # formatting (drop --check to apply)
mypy --strict             # type checking (src and tests)
pytest                    # tests, with a coverage report
```

The layout is small on purpose:

| Module | Responsibility |
| --- | --- |
| `parsing.py` | CSV layouts, amount and date parsing |
| `rules.py` | loading and validating the TOML rules, matching |
| `report.py` | monthly aggregation (pure `Decimal` arithmetic) |
| `render.py` | table, Markdown and JSON output |
| `i18n.py` | locale resolution, gettext catalogues, Babel formatting |
| `cli.py` | argument parsing and wiring |

Test fixtures in `tests/fixtures/` cover a plain CSV, a semicolon/decimal-comma
export with accented headers, and a tab-separated file with month-first dates
and parenthesized negatives. All data in them is invented. CI runs the same four
checks on Python 3.12 and 3.13.

## License

[MIT](LICENSE)
