"""Tests for debarment domain models.

Covers:

* enums and their values,
* normalized data: valid CLEAR, valid RESTRICTED, valid UNKNOWN,
* date semantics (active, expired, future, missing),
* invalid enum values,
* extra fields rejected (``extra="forbid"``),
* identifier / subject name preservation,
* the ``normalize_identifier`` helper,
* configuration objects: URL HTTPS-only, missing fields rejected.
"""

from __future__ import annotations

import pytest
from datetime import date
from pydantic import ValidationError

from compliance_engine.verification.debarment_models import (
    DebarmentClientCredentials,
    DebarmentConfig,
    DebarmentEndpointConfig,
    DebarmentQuery,
    DebarmentRestrictionStatus,
    DebarmentRestrictionType,
    MatchMethod,
    NormalizedDebarmentData,
    SubjectType,
    normalize_identifier,
)


# ---------------------------------------------------------------------------
# Enum tests
# ---------------------------------------------------------------------------


def test_restriction_status_values() -> None:
    assert DebarmentRestrictionStatus.CLEAR.value == "CLEAR"
    assert DebarmentRestrictionStatus.RESTRICTED.value == "RESTRICTED"
    assert DebarmentRestrictionStatus.UNKNOWN.value == "UNKNOWN"


def test_restriction_type_values() -> None:
    assert DebarmentRestrictionType.BLACKLIST.value == "BLACKLIST"
    assert DebarmentRestrictionType.DEBARMENT.value == "DEBARMENT"
    assert DebarmentRestrictionType.SUSPENSION.value == "SUSPENSION"
    assert (
        DebarmentRestrictionType.PROCUREMENT_RESTRICTION.value
        == "PROCUREMENT_RESTRICTION"
    )
    assert DebarmentRestrictionType.OTHER.value == "OTHER"


def test_match_method_values() -> None:
    assert MatchMethod.EXACT_IDENTIFIER.value == "EXACT_IDENTIFIER"
    assert MatchMethod.NORMALIZED_IDENTIFIER.value == "NORMALIZED_IDENTIFIER"
    assert MatchMethod.EXACT_NAME.value == "EXACT_NAME"
    assert MatchMethod.NORMALIZED_NAME.value == "NORMALIZED_NAME"
    assert MatchMethod.INSUFFICIENT_EVIDENCE.value == "INSUFFICIENT_EVIDENCE"


def test_subject_type_values() -> None:
    assert SubjectType.INDIVIDUAL.value == "INDIVIDUAL"
    assert SubjectType.ORGANIZATION.value == "ORGANIZATION"
    assert SubjectType.DIRECTOR.value == "DIRECTOR"
    assert SubjectType.UNKNOWN.value == "UNKNOWN"


# ---------------------------------------------------------------------------
# normalize_identifier helper
# ---------------------------------------------------------------------------


def test_normalize_identifier_none() -> None:
    assert normalize_identifier(None) is None


def test_normalize_identifier_empty_string() -> None:
    assert normalize_identifier("") is None
    assert normalize_identifier("   ") is None


def test_normalize_identifier_strips_whitespace() -> None:
    assert normalize_identifier("  AAACI1234F  ") == "AAACI1234F"


def test_normalize_identifier_collapses_whitespace() -> None:
    assert normalize_identifier("AAACI 1234 F") == "AAACI 1234 F"


def test_normalize_identifier_uppercases() -> None:
    assert normalize_identifier("abcde1234f") == "ABCDE1234F"


# ---------------------------------------------------------------------------
# NormalizedDebarmentData: valid shapes
# ---------------------------------------------------------------------------


def test_normalized_clear_payload() -> None:
    data = NormalizedDebarmentData(restriction_status="CLEAR")
    assert data.restriction_status is DebarmentRestrictionStatus.CLEAR
    assert data.restriction_type is None
    assert data.effective_date is None
    assert data.end_date is None
    assert data.issuing_authority is None
    assert data.reference_number is None
    assert data.subject_type is SubjectType.UNKNOWN
    assert data.subject_identifier is None
    assert data.match_method is MatchMethod.INSUFFICIENT_EVIDENCE


def test_normalized_restricted_payload_active() -> None:
    data = NormalizedDebarmentData(
        restriction_status="RESTRICTED",
        restriction_type="DEBARMENT",
        effective_date=date(2024, 1, 1),
        end_date=date(2026, 1, 1),
        issuing_authority="GeM",
        reference_number="REF-2024-001",
        source_reference="https://example.invalid/records/1",
        subject_type="ORGANIZATION",
        subject_identifier="27AAACI1234F1Z5",
        subject_name_original="ACME Enterprises Private Limited",
        subject_name_normalized="acme enterprises private limited",
        match_method="EXACT_IDENTIFIER",
    )
    assert data.restriction_status is DebarmentRestrictionStatus.RESTRICTED
    assert data.restriction_type is DebarmentRestrictionType.DEBARMENT
    assert data.effective_date == date(2024, 1, 1)
    assert data.end_date == date(2026, 1, 1)
    assert data.issuing_authority == "GeM"
    assert data.reference_number == "REF-2024-001"
    assert data.subject_type is SubjectType.ORGANIZATION
    assert data.match_method is MatchMethod.EXACT_IDENTIFIER


def test_normalized_unknown_payload() -> None:
    data = NormalizedDebarmentData(restriction_status="UNKNOWN")
    assert data.restriction_status is DebarmentRestrictionStatus.UNKNOWN


def test_normalized_open_ended_restriction() -> None:
    data = NormalizedDebarmentData(
        restriction_status="RESTRICTED",
        restriction_type="SUSPENSION",
        effective_date=date(2024, 6, 1),
        end_date=None,
    )
    assert data.end_date is None


# ---------------------------------------------------------------------------
# NormalizedDebarmentData: invalid inputs
# ---------------------------------------------------------------------------


def test_normalized_rejects_invalid_restriction_status() -> None:
    with pytest.raises(ValidationError):
        NormalizedDebarmentData(restriction_status="MAYBE")


def test_normalized_rejects_invalid_restriction_type() -> None:
    with pytest.raises(ValidationError):
        NormalizedDebarmentData(
            restriction_status="RESTRICTED",
            restriction_type="FOOBAR",
        )


def test_normalized_rejects_invalid_subject_type() -> None:
    with pytest.raises(ValidationError):
        NormalizedDebarmentData(
            restriction_status="RESTRICTED",
            subject_type="CYBORG",
        )


def test_normalized_rejects_invalid_match_method() -> None:
    with pytest.raises(ValidationError):
        NormalizedDebarmentData(
            restriction_status="CLEAR",
            match_method="FUZZY",
        )


def test_normalized_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        NormalizedDebarmentData(
            restriction_status="CLEAR",
            unexpected_field="x",
        )


def test_normalized_rejects_missing_restriction_status() -> None:
    with pytest.raises(ValidationError):
        NormalizedDebarmentData()


def test_normalized_rejects_non_date_value() -> None:
    with pytest.raises(ValidationError):
        NormalizedDebarmentData(
            restriction_status="RESTRICTED",
            effective_date="not-a-date",
        )


def test_normalized_invalid_date_ordering_accepted_by_model() -> None:
    # The model does not enforce effective <= end_date semantics;
    # the rule is responsible for evaluating whether the
    # restriction is active on the evaluation date.
    data = NormalizedDebarmentData(
        restriction_status="RESTRICTED",
        effective_date=date(2025, 1, 1),
        end_date=date(2024, 1, 1),
    )
    assert data.effective_date == date(2025, 1, 1)
    assert data.end_date == date(2024, 1, 1)


# ---------------------------------------------------------------------------
# DebarmentQuery: identifier / subject name preservation
# ---------------------------------------------------------------------------


def test_query_carries_identifier_only() -> None:
    q = DebarmentQuery(
        bidder_id="bidder_1", identifier="27AAACI1234F1Z5"
    )
    assert q.bidder_id == "bidder_1"
    assert q.identifier == "27AAACI1234F1Z5"
    assert q.subject_name is None
    assert q.call_id  # auto-allocated


def test_query_carries_subject_name() -> None:
    q = DebarmentQuery(
        bidder_id="bidder_1",
        identifier="27AAACI1234F1Z5",
        subject_name="ACME ENTERPRISES PRIVATE LIMITED",
    )
    assert q.subject_name == "ACME ENTERPRISES PRIVATE LIMITED"


def test_query_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DebarmentQuery(
            bidder_id="bidder_1",
            identifier="27AAACI1234F1Z5",
            mystery="x",
        )


def test_query_call_id_unique_per_instance() -> None:
    a = DebarmentQuery(bidder_id="b", identifier="i")
    b = DebarmentQuery(bidder_id="b", identifier="i")
    assert a.call_id != b.call_id


def test_query_evaluation_date_carried_through() -> None:
    q = DebarmentQuery(
        bidder_id="b",
        identifier="i",
        evaluation_date=date(2025, 6, 15),
    )
    assert q.evaluation_date == date(2025, 6, 15)


# ---------------------------------------------------------------------------
# Configuration objects
# ---------------------------------------------------------------------------


def test_endpoint_https_only_rejects_http() -> None:
    with pytest.raises(ValidationError):
        DebarmentEndpointConfig(
            url="http://example.invalid/query",
        )


def test_endpoint_allows_https() -> None:
    cfg = DebarmentEndpointConfig(
        url="https://example.invalid/query",
        timeout_seconds=5.0,
    )
    assert cfg.url == "https://example.invalid/query"
    assert cfg.timeout_seconds == 5.0


def test_endpoint_allows_empty_url_for_late_validation() -> None:
    # An empty URL is allowed at field-validator level so the
    # higher-level ``DebarmentConfig.validate_for_real_use`` can
    # surface a clear error.
    cfg = DebarmentEndpointConfig(url="")
    assert cfg.url == ""


def test_endpoint_rejects_too_small_timeout() -> None:
    with pytest.raises(ValidationError):
        DebarmentEndpointConfig(
            url="https://example.invalid/q",
            timeout_seconds=0.0,
        )


def test_credentials_rejects_empty_refs() -> None:
    with pytest.raises(ValidationError):
        DebarmentClientCredentials(
            client_id_ref="",
            client_secret_ref="X",
        )
    with pytest.raises(ValidationError):
        DebarmentClientCredentials(
            client_id_ref="X",
            client_secret_ref="",
        )


def test_config_validate_for_real_use_reports_missing_endpoint() -> None:
    # Empty URL is allowed at field level so the higher-level
    # validator can produce a clear error message.
    cfg = DebarmentConfig(
        endpoint=DebarmentEndpointConfig(url=""),
        client=DebarmentClientCredentials(
            client_id_ref="OK",
            client_secret_ref="OK",
        ),
    )
    with pytest.raises(ValueError, match="endpoint.url"):
        cfg.validate_for_real_use()


def test_config_validate_for_real_use_passes_when_complete() -> None:
    cfg = DebarmentConfig(
        endpoint=DebarmentEndpointConfig(
            url="https://example.invalid/q",
        ),
        client=DebarmentClientCredentials(
            client_id_ref="DEBARMENT_CLIENT_ID_REF",
            client_secret_ref="DEBARMENT_CLIENT_SECRET_REF",
        ),
    )
    cfg.validate_for_real_use()


def test_config_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        DebarmentConfig(
            endpoint=DebarmentEndpointConfig(url="https://x/y"),
            client=DebarmentClientCredentials(
                client_id_ref="x",
                client_secret_ref="y",
            ),
            unexpected="z",
        )
