"""Tests for the financial year normalizer."""

import pytest

from compliance_engine.financial import (
    FinancialYear,
    normalize_financial_year,
)
from compliance_engine.financial.years import CANONICAL_YEAR_PATTERN


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2023-24", "2023-24"),
        ("2023-2024", "2023-24"),
        ("FY2023-24", "2023-24"),
        ("FY 2023-24", "2023-24"),
        ("fy 2023-24", "2023-24"),
        ("FY2023-2024", "2023-24"),
        ("2023/24", "2023-24"),
        ("2023 - 24", "2023-24"),
        ("  2023-24  ", "2023-24"),
    ],
)
def test_normalize_financial_year_accepts_supported_forms(raw, expected):
    assert normalize_financial_year(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        True,
        False,
        2023,
        2023.5,
        "2023",
        "2023-25",     # wrong two-digit end
        "2023-2025",   # wrong four-digit end
        "FY",
        "abc-def",
        "2023 24",
    ],
)
def test_normalize_financial_year_rejects_ambiguous_inputs(raw):
    assert normalize_financial_year(raw) is None


def test_canonical_year_pattern_is_doc():
    assert CANONICAL_YEAR_PATTERN == r"^\d{4}-\d{2}$"


def test_financial_year_parse_round_trip():
    fy = FinancialYear.parse("FY 2023-24")
    assert fy is not None
    assert fy.canonical == "2023-24"
    assert fy.start_year == 2023
    assert fy.end_year == 2024


def test_financial_year_parse_unparseable_returns_none():
    assert FinancialYear.parse("nope") is None
    assert FinancialYear.parse(None) is None
    assert FinancialYear.parse(2023) is None


def test_financial_year_is_frozen():
    fy = FinancialYear.parse("2023-24")
    with pytest.raises(Exception):
        fy.canonical = "2099-99"  # type: ignore[misc]


def test_financial_year_rejects_extra_fields():
    import pydantic
    with pytest.raises(pydantic.ValidationError):
        FinancialYear(canonical="2023-24", extra="x")  # type: ignore[call-arg]
