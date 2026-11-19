from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from expense_insights import __version__
from expense_insights.cli import _lang_from_argv, main


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        code = main(list(args))
    except SystemExit as exc:  # --help, --version and usage errors exit through argparse
        code = int(exc.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


def test_example_report(capsys: pytest.CaptureFixture[str], examples: Path) -> None:
    code, out, err = run(
        capsys, str(examples / "statement.csv"), "-r", str(examples / "rules.toml")
    )
    assert (code, err) == (0, "")
    assert out.startswith("Expense report for October 2026\n")
    assert "Groceries          5    -€369.03    -€345.46    +6.8%" in out
    assert "BOOKWORM STORE" in out


def test_json_output(capsys: pytest.CaptureFixture[str], examples: Path) -> None:
    code, out, _err = run(
        capsys,
        str(examples / "statement.csv"),
        "--rules",
        str(examples / "rules.toml"),
        "--format",
        "JSON",
        "--month",
        "2026-09",
        "--top",
        "2",
    )
    data = json.loads(out)
    assert code == 0
    assert data["month"] == "2026-09"
    assert data["currency"] == "EUR"
    assert len(data["top_merchants"]) == 2
    assert data["uncategorized"] == []


def test_lang_flag(capsys: pytest.CaptureFixture[str], examples: Path) -> None:
    code, out, _err = run(
        capsys, str(examples / "statement.csv"), "-r", str(examples / "rules.toml"), "--lang", "es"
    )
    assert code == 0
    assert out.startswith("Informe de gastos de octubre de 2026\n")
    assert "-2.150,77\u00a0€" in out


def test_lang_from_environment(
    capsys: pytest.CaptureFixture[str], examples: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    code, out, _err = run(
        capsys, str(examples / "statement.csv"), "-f", "markdown", "--currency", "brl"
    )
    assert code == 0
    assert out.startswith("# Relatório de despesas de outubro de 2026")
    assert "R$\u00a03.200,00" in out
    assert "| Sem categoria |" in out


def test_column_mapping_options(capsys: pytest.CaptureFixture[str], examples: Path) -> None:
    code, out, err = run(
        capsys,
        str(examples / "statement-eu.csv"),
        "--date-col",
        "Buchungstag",
        "--description-col",
        "Verwendungszweck",
        "--amount-col",
        "Betrag (EUR)",
        "--decimal",
        "comma",
        "--date-format",
        "%d.%m.%Y",
        "--delimiter",
        ";",
        "--encoding",
        "utf-8",
        "--currency",
        "EUR",
        "--format",
        "json",
    )
    assert (code, err) == (0, "")
    assert json.loads(out)["summary"]["expenses"] == "-1515.80"


def test_tab_delimiter_alias(capsys: pytest.CaptureFixture[str], fixtures: Path) -> None:
    code, out, _err = run(
        capsys,
        str(fixtures / "us_tabs.tsv"),
        "--date-col=Posted",
        "--description-col=Memo",
        "--amount-col=Value",
        "--delimiter=tab",
        "-f",
        "json",
    )
    assert code == 0
    assert json.loads(out)["summary"]["net"] == "-74.95"


def test_help_is_translated(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _err = run(capsys, "--lang=pt_BR", "--help")
    assert code == 0
    assert out.startswith("uso: expense-insights")
    assert "mostra esta ajuda e sai" in out
    assert "Formato do CSV:" in out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert run(capsys, "--version") == (0, f"expense-insights {__version__}\n", "")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ([], "give at least one statement CSV file"),
        (["x.csv", "--top", "0"], "argument -n/--top: expected a positive whole number"),
        (["x.csv", "--month", "March"], "expected a month like 2026-03"),
        (["x.csv", "--format", "xml"], "choose one of: table, markdown, json"),
        (["x.csv", "--decimal", "dot"], 'use "point" or "comma"'),
        (["x.csv", "--currency", "euro"], "three-letter currency code"),
        (["x.csv", "--delimiter", ";;"], "single character"),
        (["x.csv", "--frobnicate"], "unrecognized arguments: --frobnicate"),
    ],
)
def test_usage_errors(capsys: pytest.CaptureFixture[str], args: list[str], message: str) -> None:
    code, _out, err = run(capsys, *args)
    assert code == 2
    assert err.startswith("usage: expense-insights")
    assert message in err


def test_usage_errors_are_translated(capsys: pytest.CaptureFixture[str]) -> None:
    code, _out, err = run(capsys, "--lang", "es", "x.csv", "--top", "-3")
    assert code == 2
    assert "error: argumento -n/--top: se esperaba un número entero positivo" in err


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["missing.csv"], "missing.csv: file not found."),
        (["{examples}/statement.csv", "-r", "nope.toml"], "Rules file not found: nope.toml"),
        (["{examples}/statement.csv", "-m", "2025-01"], "No transactions in 2025-01."),
        (["{fixtures}/us_tabs.tsv"], "column 'date' not found"),
    ],
)
def test_data_errors(
    capsys: pytest.CaptureFixture[str],
    examples: Path,
    fixtures: Path,
    args: list[str],
    message: str,
) -> None:
    resolved = [a.format(examples=examples, fixtures=fixtures) for a in args]
    code, out, err = run(capsys, *resolved)
    assert (code, out) == (1, "")
    assert err.startswith("expense-insights: error: ")
    assert message in err


def test_header_only_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("date,description,amount\n", "utf-8")
    code, _out, err = run(capsys, str(path))
    assert code == 1
    assert "No transactions found." in err


def test_python_dash_m() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "expense_insights", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"expense-insights {__version__}"


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["a.csv", "--lang", "es"], "es"),
        (["--lang=pt_BR", "a.csv"], "pt_BR"),
        (["a.csv", "--lang"], None),
        (["--", "--lang", "es"], None),
        (["a.csv"], None),
    ],
)
def test_lang_is_found_before_parsing(argv: list[str], expected: str | None) -> None:
    assert _lang_from_argv(argv) == expected
