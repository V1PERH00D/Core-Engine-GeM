"""Tests for per-dimension normalization."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from ai_verification.cross_document.normalization import (
    ADDRESS_NORMALIZATION_RULES,
    ADDRESS_NORMALIZATION_VERSION,
    DATE_NORMALIZATION_RULES,
    DATE_NORMALIZATION_VERSION,
    IDENTIFIER_NORMALIZATION_RULES,
    IDENTIFIER_NORMALIZATION_VERSION,
    MANUFACTURER_NORMALIZATION_VERSION,
    PRODUCT_NORMALIZATION_RULES,
    PRODUCT_NORMALIZATION_VERSION,
    normalize_address,
    normalize_date,
    normalize_identifier,
    normalize_manufacturer,
    normalize_product,
    parse_iso_date,
)


# -----------------------------------------------------------------------
# Identifier normalization
# -----------------------------------------------------------------------


def test_identifier_version_is_stable_string() -> None:
    assert isinstance(IDENTIFIER_NORMALIZATION_VERSION, str)
    assert IDENTIFIER_NORMALIZATION_VERSION
    assert IDENTIFIER_NORMALIZATION_VERSION == "cross-document-identifier-v1"


def test_identifier_rules_are_documented() -> None:
    joined = "\n".join(IDENTIFIER_NORMALIZATION_RULES)
    assert "NFKC" in joined
    assert "uppercase" in joined.lower() or "ASCII" in joined


def test_identifier_none_returns_none() -> None:
    assert normalize_identifier(None) is None


def test_identifier_empty_returns_none() -> None:
    assert normalize_identifier("") is None
    assert normalize_identifier("   ") is None


def test_identifier_exact_match_normalizes_identically() -> None:
    assert normalize_identifier("27AAACI1234F1Z5") == (
        normalize_identifier("27AAACI1234F1Z5")
    )


def test_identifier_uppercased() -> None:
    assert normalize_identifier("27aaaci1234f1z5") == "27AAACI1234F1Z5"


def test_identifier_whitespace_collapsed() -> None:
    assert normalize_identifier("  27 AAACI 1234 F1Z5  ") == "27 AAACI 1234 F1Z5"


def test_identifier_edge_punctuation_stripped() -> None:
    assert normalize_identifier("27AAACI1234F1Z5.") == "27AAACI1234F1Z5"
    assert normalize_identifier("27AAACI1234F1Z5,") == "27AAACI1234F1Z5"


def test_identifier_unicode_nfkc() -> None:
    # Full-width digits normalized via NFKC.
    assert normalize_identifier("\uFF12\uFF17AAACI1234F1Z5") == "27AAACI1234F1Z5"


def test_identifier_non_string_coerced() -> None:
    # Numeric identifiers coerce safely.
    assert normalize_identifier(123456) == "123456"


def test_identifier_bool_returns_none() -> None:
    assert normalize_identifier(True) is None
    assert normalize_identifier(False) is None


# -----------------------------------------------------------------------
# Address normalization
# -----------------------------------------------------------------------


def test_address_version_is_stable_string() -> None:
    assert ADDRESS_NORMALIZATION_VERSION == "cross-document-address-v1"


def test_address_rules_documented() -> None:
    joined = "\n".join(ADDRESS_NORMALIZATION_RULES)
    assert "line break" in joined.lower() or "line-break" in joined.lower()
    assert "comma" in joined.lower()


def test_address_none_returns_none() -> None:
    assert normalize_address(None) is None


def test_address_empty_returns_none() -> None:
    assert normalize_address("") is None
    assert normalize_address("   \n  ") is None


def test_address_non_string_returns_none() -> None:
    assert normalize_address(12345) is None


def test_address_exact_match_normalizes_identically() -> None:
    text = "Plot 42, Hinjawadi Phase 1, Pune"
    assert normalize_address(text) == normalize_address(text)


def test_address_case_difference_normalizes_away() -> None:
    a = normalize_address("Plot 42, Hinjawadi")
    b = normalize_address("PLOT 42, HINJAWADI")
    assert a == b


def test_address_whitespace_collapse() -> None:
    assert (
        normalize_address("Plot   42,   Hinjawadi")
        == normalize_address("Plot 42, Hinjawadi")
    )


def test_address_line_break_normalization() -> None:
    assert normalize_address("Plot 42\r\nHinjawadi") == (
        normalize_address("Plot 42\nHinjawadi")
    )


def test_address_drop_empty_lines() -> None:
    assert (
        normalize_address("Plot 42\n\n\nHinjawadi")
        == normalize_address("Plot 42\nHinjawadi")
    )


def test_address_edge_punctuation_normalization() -> None:
    assert normalize_address("Plot 42,,") == normalize_address("Plot 42")
    assert normalize_address(",,Plot 42,") == normalize_address("Plot 42")


def test_address_no_fuzzy_match() -> None:
    # Two different cities remain distinct.
    a = normalize_address("Plot 42, Pune")
    b = normalize_address("Plot 42, Delhi")
    assert a != b


def test_address_unicode_nfkc() -> None:
    assert normalize_address("Plot \uFF24\uFF45lhi") == normalize_address(
        "Plot Delhi"
    )


# -----------------------------------------------------------------------
# Date normalization
# -----------------------------------------------------------------------


def test_date_version_is_stable_string() -> None:
    assert DATE_NORMALIZATION_VERSION == "cross-document-date-v1"


def test_date_rules_documented() -> None:
    joined = "\n".join(DATE_NORMALIZATION_RULES)
    assert "ISO" in joined
    assert "YYYY-MM-DD" in joined


def test_date_none_returns_none() -> None:
    assert normalize_date(None) is None


def test_date_iso_format() -> None:
    assert normalize_date("2024-07-28") == "2024-07-28"


def test_date_iso_with_slash() -> None:
    assert normalize_date("2024/07/28") == "2024-07-28"


def test_date_iso_with_datetime_suffix() -> None:
    assert normalize_date("2024-07-28T10:30:00") == "2024-07-28"


def test_date_dmy_format() -> None:
    assert normalize_date("28-07-2024") == "2024-07-28"
    assert normalize_date("28/07/2024") == "2024-07-28"


def test_date_month_name_format() -> None:
    assert normalize_date("28-Jul-2024") == "2024-07-28"
    assert normalize_date("28 JUL 2024") == "2024-07-28"


def test_date_datetime_object() -> None:
    assert normalize_date(datetime(2024, 7, 28, 12, 0)) == "2024-07-28"


def test_date_date_object() -> None:
    assert normalize_date(date(2024, 7, 28)) == "2024-07-28"


def test_date_invalid_returns_none() -> None:
    assert normalize_date("not a date") is None
    assert normalize_date("2024-13-45") is None  # not a real date
    assert normalize_date(12345) is None


def test_parse_iso_date_round_trip() -> None:
    assert parse_iso_date("2024-07-28") == date(2024, 7, 28)
    assert parse_iso_date(None) is None
    assert parse_iso_date("not iso") is None


# -----------------------------------------------------------------------
# Product normalization
# -----------------------------------------------------------------------


def test_product_version_is_stable_string() -> None:
    assert PRODUCT_NORMALIZATION_VERSION == "cross-document-product-v1"


def test_product_rules_documented() -> None:
    joined = "\n".join(PRODUCT_NORMALIZATION_RULES)
    assert "case-fold" in joined.lower() or "case fold" in joined.lower()


def test_product_none_returns_none() -> None:
    assert normalize_product(None) is None


def test_product_case_difference_normalizes_away() -> None:
    assert normalize_product("Class-I") == normalize_product("class-i")


def test_product_whitespace_collapse() -> None:
    assert normalize_product("Class  I") == normalize_product("Class I")


def test_product_no_fuzzy_match() -> None:
    assert normalize_product("Class-I") != normalize_product("Class-II")


# -----------------------------------------------------------------------
# Manufacturer normalization
# -----------------------------------------------------------------------


def test_manufacturer_version_is_identity_version() -> None:
    # Manufacturer reuses the identity name normalizer version stamp.
    assert MANUFACTURER_NORMALIZATION_VERSION == "identity-name-v1"


def test_manufacturer_reuses_identity_normalization() -> None:
    # The two implementations must agree on a known canonical case.
    from ai_verification.identity.normalization import normalize_legal_name

    assert normalize_manufacturer("ACME Industries Ltd") == (
        normalize_legal_name("ACME Industries Ltd")
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("  ACME  Industries  ", "acme industries"),
        ("Acme Pvt Ltd", "acme pvt ltd"),
    ],
)
def test_manufacturer_does_not_expand_abbreviations(raw: str, expected: str) -> None:
    # Per design, manufacturer does NOT silently rewrite
    # ``Pvt Ltd`` -> ``Private Limited``; this is the contract
    # shared with the identity package.
    assert normalize_manufacturer(raw) == expected
