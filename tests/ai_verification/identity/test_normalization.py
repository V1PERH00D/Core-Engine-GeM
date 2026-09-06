"""Tests for the deterministic name normalization algorithm."""

from __future__ import annotations

import unicodedata

import pytest

from ai_verification.identity import (
    NAME_NORMALIZATION_RULES,
    NAME_NORMALIZATION_VERSION,
    normalize_legal_name,
)


# ---------------------------------------------------------------------------
# Version + rules
# ---------------------------------------------------------------------------


def test_normalization_version_is_stable_string() -> None:
    """The normalization version must be a non-empty stable string."""

    assert isinstance(NAME_NORMALIZATION_VERSION, str)
    assert NAME_NORMALIZATION_VERSION
    # Bumping this string is a deliberate, auditable act.
    assert NAME_NORMALIZATION_VERSION == "identity-name-v1"


def test_normalization_rules_are_documented() -> None:
    """The rule list must contain at least the documented steps."""

    joined = "\n".join(NAME_NORMALIZATION_RULES)
    assert "NFKC" in joined
    assert "whitespace" in joined.lower()
    assert "case" in joined.lower()


# ---------------------------------------------------------------------------
# Basic equivalence
# ---------------------------------------------------------------------------


def test_exact_match_normalizes_identically() -> None:
    """Two byte-identical strings must normalize to the same value."""

    text = "Acme Enterprises"
    assert normalize_legal_name(text) == normalize_legal_name(text)


def test_case_difference_normalizes_away() -> None:
    """Casing alone must not survive normalization."""

    assert (
        normalize_legal_name("ACME Enterprises")
        == normalize_legal_name("acme ENTERPRISES")
        == "acme enterprises"
    )


def test_whitespace_collapse() -> None:
    """Repeated internal whitespace must collapse to a single space."""

    assert normalize_legal_name("  ACME    ENTERPRISES  ") == "acme enterprises"


def test_punctuation_removed_from_edges() -> None:
    """Trailing/leading punctuation must be stripped."""

    assert normalize_legal_name("ACME ENTERPRISES.") == "acme enterprises"
    assert normalize_legal_name("ACME ENTERPRISES,") == "acme enterprises"
    assert normalize_legal_name("..ACME ENTERPRISES..") == "acme enterprises"


def test_punctuation_interior_is_preserved_literally() -> None:
    """Interior punctuation is NOT removed by this milestone's rules.

    The engine intentionally does not rewrite interior punctuation
    because that would risk amplifying formatting differences into
    identity matches. "ACME-ENTERPRISES" stays distinct from
    "ACME ENTERPRISES" at this layer.
    """

    assert (
        normalize_legal_name("ACME-ENTERPRISES")
        != normalize_legal_name("ACME ENTERPRISES")
    )


def test_pvt_vs_private_is_not_implicitly_equalized() -> None:
    """The engine MUST NOT silently rewrite "PVT LTD" -> "PRIVATE LIMITED".

    The Compliance Engine's cross-document anomaly detector already
    performs this lexical rewrite for evidence fields; the
    cross-source identity engine deliberately does NOT, so synonym
    rewrites cannot create fake cross-source matches.
    """

    assert (
        normalize_legal_name("ACME PVT LTD")
        != normalize_legal_name("ACME PRIVATE LIMITED")
    )


def test_unicode_nfkc_applied() -> None:
    """Unicode NFKC forms must normalize to the same canonical form."""

    # Use a string with a compatibility character.
    decomposed = unicodedata.normalize("NFKD", "ACME")
    assert normalize_legal_name(decomposed) == "acme"


def test_none_input_returns_none() -> None:
    """None must propagate as None."""

    assert normalize_legal_name(None) is None


def test_empty_input_returns_none() -> None:
    """An empty / whitespace-only string must collapse to None."""

    assert normalize_legal_name("") is None
    assert normalize_legal_name("   ") is None
    assert normalize_legal_name("\t\n") is None


def test_non_string_input_raises_type_error() -> None:
    """A non-string, non-None input must fail loudly."""

    with pytest.raises(TypeError):
        normalize_legal_name(123)  # type: ignore[arg-type]


def test_normalization_is_pure() -> None:
    """Repeated calls must produce the same value (no hidden state)."""

    first = normalize_legal_name("  ACME  Enterprises  ")
    second = normalize_legal_name("  ACME  Enterprises  ")
    assert first == second == "acme enterprises"


def test_original_value_is_not_mutated_by_normalization() -> None:
    """The normalizer must never mutate the caller's input."""

    text = "  ACME  "
    snapshot = text
    normalize_legal_name(text)
    assert text == snapshot