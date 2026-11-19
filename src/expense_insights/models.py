"""Core data types shared by the parser, the rules engine and the report."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Transaction:
    """One row of a bank statement.

    ``amount`` is signed: money leaving the account is negative, money coming in
    is positive.
    """

    date: date
    description: str
    amount: Decimal
    source: str = ""
    line: int = 0


@dataclass(frozen=True, slots=True)
class Categorized:
    """A transaction together with the category its rules assigned (``None`` if none did)."""

    transaction: Transaction
    category: str | None
