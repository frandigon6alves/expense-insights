from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from expense_insights.i18n import activate

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture(autouse=True)
def english_by_default(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Isolate tests from the developer's locale and reset the active catalogue."""
    for variable in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
        monkeypatch.delenv(variable, raising=False)
    activate("en")
    yield
    activate("en")


@pytest.fixture
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture
def examples() -> Path:
    return EXAMPLES
