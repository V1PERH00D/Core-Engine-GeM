"""Tests for the procurement-eligibility / debarment adapter.

Covers:

* Transport seam: static transport, HTTPS enforcement, timeout,
  unavailable transport, malformed response, 4xx handling, 5xx
  handling.
* Parser: status-code -> VerificationStatus mapping,
  business restriction status extraction, normalized data
  construction, raw_response preservation.
* Adapter: distinct verification IDs across repeated calls, query
  preservation, raw_response preservation, correlation ID
  preservation, transport status preservation, normalized data
  preservation.
* Matching: EXACT_IDENTIFIER, NORMALIZED_IDENTIFIER, EXACT_NAME,
  NORMALIZED_NAME, INSUFFICIENT_EVIDENCE -- identifier preferred
  over name.
* Audit fields: verification_id uniqueness across calls.
* Default transport: fails fast and loud.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from compliance_engine.models import Verification, VerificationStatus
from compliance_engine.verification.debarment_adapter import (
    DEBARMENT_CAPABILITY,
    DEBARMENT_SOURCE,
    DebarmentAdapter,
    DebarmentDefaultHttpTransport,
    DebarmentHttpRequest,
    DebarmentHttpResponse,
    DebarmentHttpTransportError,
    DebarmentResponseParser,
    StaticDebarmentHttpTransport,
    StaticDebarmentTransport,
    derive_match_method,
    http_response_to_envelope,
)
from compliance_engine.verification.debarment_models import (
    DebarmentQuery,
    DebarmentRestrictionStatus,
    DebarmentRestrictionType,
    MatchMethod,
    NormalizedDebarmentData,
)
from compliance_engine.verification.transport import (
    InProcessTransport,
    SourceResponseEnvelope,
    StaticTransport,
    TransportError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _env(
    *,
    status_code: int,
    raw: dict[str, Any] | None = None,
    latency_ms: int | None = 12,
    correlation_id: str | None = "corr-debarment",
) -> SourceResponseEnvelope:
    return SourceResponseEnvelope(
        status_code=status_code,
        raw_response=raw,
        latency_ms=latency_ms,
        correlation_id=correlation_id,
    )


_CLEAR_PAYLOAD = {
    "restriction_status": "CLEAR",
    "match_method": "EXACT_IDENTIFIER",
}


def _active_restricted_payload(
    *,
    identifier: str = "27AAACI1234F1Z5",
    name: str = "ACME ENTERPRISES PRIVATE LIMITED",
    effective: str = "2024-01-01",
    end: str | None = "2026-01-01",
    restriction_type: str = "DEBARMENT",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "restriction_status": "RESTRICTED",
        "restriction_type": restriction_type,
        "effective_date": effective,
        "issuing_authority": "GeM",
        "reference_number": "REF-2024-001",
        "source_reference": "https://example.invalid/records/1",
        "subject_type": "ORGANIZATION",
        "subject_identifier": identifier,
        "subject_name_original": name,
        "match_method": "EXACT_IDENTIFIER",
    }
    if end is not None:
        payload["end_date"] = end
    return payload


# ---------------------------------------------------------------------------
# Adapter defaults (no transport -> UNAVAILABLE)
# ---------------------------------------------------------------------------


def test_default_adapter_returns_unavailable_without_transport() -> None:
    adapter = DebarmentAdapter()
    v = adapter.verify("bidder_1", "27AAACI1234F1Z5")
    assert v.status is VerificationStatus.UNAVAILABLE
    assert v.capability == DEBARMENT_CAPABILITY
    assert v.source == DEBARMENT_SOURCE
    assert v.queried_identifier == "27AAACI1234F1Z5"


def test_default_http_transport_fails_fast() -> None:
    http = DebarmentDefaultHttpTransport()
    request = DebarmentHttpRequest(
        url="https://example.invalid/q", body={}
    )
    with pytest.raises(DebarmentHttpTransportError):
        http.send(request)


# ---------------------------------------------------------------------------
# Static transport: contract basics
# ---------------------------------------------------------------------------


def test_static_transport_default_404_for_unknown_identifier() -> None:
    transport = StaticDebarmentTransport()
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("bidder_1", "27AAACI1234F1Z5")
    assert v.status is VerificationStatus.NOT_FOUND


def test_static_transport_records_query() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=_CLEAR_PAYLOAD)}
    )
    DebarmentAdapter(transport=transport).verify("bidder_1", "X")
    assert len(transport.queries) == 1
    q = transport.queries[0]
    assert q.bidder_id == "bidder_1"
    assert q.identifier == "X"
    assert q.call_id


def test_static_transport_set_method_adds_response() -> None:
    transport = StaticDebarmentTransport()
    transport.set("X", _env(status_code=200, raw=_CLEAR_PAYLOAD))
    DebarmentAdapter(transport=transport).verify("b", "X")
    assert len(transport.queries) == 1


def test_static_transport_default_response_used_when_no_match() -> None:
    default = _env(status_code=200, raw=_CLEAR_PAYLOAD)
    transport = StaticDebarmentTransport(default_response=default)
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "anything")
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["restriction_status"] == "CLEAR"


# ---------------------------------------------------------------------------
# Static HTTP transport: contract basics
# ---------------------------------------------------------------------------


def test_static_http_transport_refuses_non_https() -> None:
    http = StaticDebarmentHttpTransport()
    request = DebarmentHttpRequest(url="http://example.invalid/q", body={})
    with pytest.raises(DebarmentHttpTransportError):
        http.send(request)


def test_static_http_transport_refuses_plain_http_for_https_endpoint() -> None:
    http = StaticDebarmentHttpTransport(
        responses={
            "X": DebarmentHttpResponse(status_code=200, body_json=_CLEAR_PAYLOAD)
        }
    )
    request = DebarmentHttpRequest(url="http://example.invalid/q", body={"identifier": "X"})
    with pytest.raises(DebarmentHttpTransportError):
        http.send(request)


def test_static_http_transport_records_request() -> None:
    http = StaticDebarmentHttpTransport(
        responses={
            "X": DebarmentHttpResponse(status_code=200, body_json=_CLEAR_PAYLOAD)
        }
    )
    adapter = DebarmentAdapter(http_transport=http)
    adapter.verify("b", "X")
    assert len(http.requests) == 1
    assert http.requests[0].url.startswith("https://")


def test_static_http_transport_default_404_for_unknown_identifier() -> None:
    http = StaticDebarmentHttpTransport()
    adapter = DebarmentAdapter(http_transport=http)
    v = adapter.verify("b", "X")
    assert v.status is VerificationStatus.NOT_FOUND
    assert v.transport_status_code == 404


def test_http_transport_error_translates_to_unavailable() -> None:
    class _FailingHttp:
        def send(self, request: DebarmentHttpRequest) -> DebarmentHttpResponse:
            raise DebarmentHttpTransportError("boom")

    adapter = DebarmentAdapter(http_transport=_FailingHttp())
    v = adapter.verify("b", "X")
    assert v.status is VerificationStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# Parser: status-code -> VerificationStatus mapping
# ---------------------------------------------------------------------------


def test_parser_2xx_clear_maps_to_verified() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(status_code=200, raw=_CLEAR_PAYLOAD)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["restriction_status"] == "CLEAR"


def test_parser_2xx_restricted_maps_to_verified() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(status_code=200, raw=_active_restricted_payload())
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["restriction_status"] == "RESTRICTED"
    assert v.data["restriction_type"] == "DEBARMENT"


def test_parser_2xx_unknown_business_maps_to_error() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(
        status_code=200, raw={"restriction_status": "UNKNOWN"}
    )
    v = parser.parse(envelope, query=query, bidder_id="b")
    # Transport VERIFIED + business UNKNOWN -> ERROR (so the rule
    # can surface UNVERIFIABLE).
    assert v.status is VerificationStatus.ERROR
    assert v.data["restriction_status"] == "UNKNOWN"


def test_parser_2xx_malformed_maps_to_error() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(status_code=200, raw={"foo": "bar"})
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.ERROR
    assert v.data == {}


def test_parser_2xx_missing_payload_maps_to_error() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(status_code=200, raw=None)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.ERROR


def test_parser_4xx_missing_payload_maps_to_not_found() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(status_code=404, raw=None)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.NOT_FOUND


def test_parser_4xx_invalid_identifier_maps_to_invalid() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(
        status_code=400,
        raw={"identifier_status": "INVALID"},
    )
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.INVALID


def test_parser_5xx_maps_to_unavailable() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(status_code=503, raw=None)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.UNAVAILABLE


def test_parser_3xx_maps_to_error() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(status_code=301, raw=None)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.ERROR


def test_parser_999_maps_to_error() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(status_code=999, raw=None)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.ERROR


def test_parser_4xx_with_usable_payload_maps_to_verified() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    envelope = _env(status_code=404, raw=_CLEAR_PAYLOAD)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["restriction_status"] == "CLEAR"


def test_parser_unknown_restriction_type_coerced_to_other() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    raw = _active_restricted_payload()
    raw["restriction_type"] = "FOOBAR"
    envelope = _env(status_code=200, raw=raw)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.data["restriction_type"] == "OTHER"


def test_parser_unknown_subject_type_coerced_to_unknown() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    raw = _active_restricted_payload()
    raw["subject_type"] = "ROBOT"
    envelope = _env(status_code=200, raw=raw)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.data["subject_type"] == "UNKNOWN"


def test_parser_unknown_match_method_coerced_to_insufficient_evidence() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    raw = _active_restricted_payload()
    raw["match_method"] = "FUZZY"
    envelope = _env(status_code=200, raw=raw)
    v = parser.parse(envelope, query=query, bidder_id="b")
    assert v.data["match_method"] == "INSUFFICIENT_EVIDENCE"


def test_parser_normalizes_subject_name_through_identity_helper() -> None:
    parser = DebarmentResponseParser()
    query = DebarmentQuery(bidder_id="b", identifier="X")
    raw = _active_restricted_payload()
    raw["subject_name_original"] = "  ACME Enterprises Private Limited "
    envelope = _env(status_code=200, raw=raw)
    v = parser.parse(envelope, query=query, bidder_id="b")
    # The identity normalizer is reused -- the exact output is
    # governed by ``ai_verification.identity.normalization``.
    assert v.data["subject_name_original"].strip() == (
        "ACME Enterprises Private Limited"
    )
    assert v.data["subject_name_normalized"] is not None


# ---------------------------------------------------------------------------
# Adapter: end-to-end status and audit fields
# ---------------------------------------------------------------------------


def test_adapter_clear_maps_to_verified() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=_CLEAR_PAYLOAD)}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "X")
    assert v.status is VerificationStatus.VERIFIED
    assert v.capability == DEBARMENT_CAPABILITY
    assert v.source == DEBARMENT_SOURCE
    assert v.queried_identifier == "X"


def test_adapter_active_restricted_payload_data() -> None:
    from datetime import date
    payload = _active_restricted_payload()
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=payload)}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "X")
    assert v.status is VerificationStatus.VERIFIED
    assert v.data["restriction_status"] == "RESTRICTED"
    assert v.data["restriction_type"] == "DEBARMENT"
    assert v.data["effective_date"] == date(2024, 1, 1)
    assert v.data["end_date"] == date(2026, 1, 1)
    assert v.data["issuing_authority"] == "GeM"
    assert v.data["reference_number"] == "REF-2024-001"


def test_adapter_preserves_query_for_audit() -> None:
    from datetime import date as _date
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=_CLEAR_PAYLOAD)}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify(
        "bidder-42",
        "X",
        subject_name="ACME",
        evaluation_date=_date(2025, 6, 15),
        correlation_id="trace-1",
    )
    assert v.query["bidder_id"] == "bidder-42"
    assert v.query["identifier"] == "X"
    assert v.query["subject_name"] == "ACME"
    assert v.query["evaluation_date"] == _date(2025, 6, 15)


def test_adapter_preserves_raw_response() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=_CLEAR_PAYLOAD)}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "X")
    assert v.raw_response == _CLEAR_PAYLOAD


def test_adapter_preserves_transport_status_code() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=_CLEAR_PAYLOAD)}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "X")
    assert v.transport_status_code == 200


def test_adapter_preserves_correlation_id_from_envelope() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(
            status_code=200, raw=_CLEAR_PAYLOAD,
            correlation_id="trace-xyz",
        )}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "X")
    assert v.correlation_id == "trace-xyz"


def test_adapter_correlation_id_falls_back_to_query() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(
            status_code=200, raw=_CLEAR_PAYLOAD, correlation_id=None,
        )}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "X", correlation_id="from-kwargs")
    assert v.correlation_id == "from-kwargs"


def test_adapter_preserves_latency() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(
            status_code=200, raw=_CLEAR_PAYLOAD, latency_ms=137,
        )}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "X")
    assert v.latency_ms == 137


# ---------------------------------------------------------------------------
# Verification ID uniqueness across calls
# ---------------------------------------------------------------------------


def test_repeated_calls_produce_distinct_verification_ids() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=_CLEAR_PAYLOAD)}
    )
    adapter = DebarmentAdapter(transport=transport)
    v1 = adapter.verify("b", "X")
    v2 = adapter.verify("b", "X")
    assert v1.verification_id != v2.verification_id


def test_repeated_calls_share_same_payload_data() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=_CLEAR_PAYLOAD)}
    )
    adapter = DebarmentAdapter(transport=transport)
    v1 = adapter.verify("b", "X")
    v2 = adapter.verify("b", "X")
    assert v1.data == v2.data


def test_preallocated_verification_id_used_when_supplied() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=_CLEAR_PAYLOAD)}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "X", verification_id="DEBARMENT_REGISTRY:X:CUSTOM")
    assert v.verification_id == "DEBARMENT_REGISTRY:X:CUSTOM"


# ---------------------------------------------------------------------------
# Transport errors -> UNAVAILABLE
# ---------------------------------------------------------------------------


def test_transport_error_translates_to_unavailable() -> None:
    class _Raising:
        def send_query(self, query: Any) -> SourceResponseEnvelope:
            raise TransportError("simulated")

    adapter = DebarmentAdapter(transport=_Raising())
    v = adapter.verify("b", "X")
    assert v.status is VerificationStatus.UNAVAILABLE


def test_not_implemented_translate_to_unavailable() -> None:
    adapter = DebarmentAdapter(transport=InProcessTransport())
    v = adapter.verify("b", "X")
    assert v.status is VerificationStatus.UNAVAILABLE
    assert v.transport_status_code is None


# ---------------------------------------------------------------------------
# Unavailable audit fields
# ---------------------------------------------------------------------------


def test_unavailable_carries_query_and_correlation_id() -> None:
    adapter = DebarmentAdapter()
    v = adapter.verify("b", "X", correlation_id="trace-1")
    assert v.correlation_id == "trace-1"
    assert v.query["identifier"] == "X"
    assert v.data == {}
    assert v.transport_status_code is None


# ---------------------------------------------------------------------------
# derive_match_method
# ---------------------------------------------------------------------------


def test_match_exact_identifier() -> None:
    method = derive_match_method(
        queried_identifier="27AAACI1234F1Z5",
        queried_subject_name=None,
        source_identifier="27AAACI1234F1Z5",
        source_name_original=None,
    )
    assert method is MatchMethod.EXACT_IDENTIFIER


def test_match_normalized_identifier() -> None:
    method = derive_match_method(
        queried_identifier="  27AAACI1234F1Z5  ",
        queried_subject_name=None,
        source_identifier="27AAACI1234F1Z5",
        source_name_original=None,
    )
    assert method is MatchMethod.NORMALIZED_IDENTIFIER


def test_match_identifier_preferred_over_name() -> None:
    method = derive_match_method(
        queried_identifier="27AAACI1234F1Z5",
        queried_subject_name="ACME",
        source_identifier="27AAACI1234F1Z5",
        source_name_original="Other Co",
    )
    assert method is MatchMethod.EXACT_IDENTIFIER


def test_match_exact_name_when_no_identifier() -> None:
    method = derive_match_method(
        queried_identifier="ACME",
        queried_subject_name="ACME",
        source_identifier=None,
        source_name_original="ACME",
    )
    assert method is MatchMethod.EXACT_NAME


def test_match_normalized_name() -> None:
    method = derive_match_method(
        queried_identifier="ACME",
        queried_subject_name="acme enterprises",
        source_identifier=None,
        source_name_original="ACME Enterprises",
    )
    assert method is MatchMethod.NORMALIZED_NAME


def test_match_insufficient_evidence_when_similar_but_not_equal() -> None:
    method = derive_match_method(
        queried_identifier="ACME ENTERPRISES PRIVATE LIMITED",
        queried_subject_name=None,
        source_identifier=None,
        source_name_original="ACME ENTERPRISES LIMITED",
    )
    assert method is MatchMethod.INSUFFICIENT_EVIDENCE


def test_match_insufficient_evidence_when_no_data() -> None:
    method = derive_match_method(
        queried_identifier="X",
        queried_subject_name=None,
        source_identifier=None,
        source_name_original=None,
    )
    assert method is MatchMethod.INSUFFICIENT_EVIDENCE


# ---------------------------------------------------------------------------
# http_response_to_envelope
# ---------------------------------------------------------------------------


def test_http_response_to_envelope_preserves_all_fields() -> None:
    response = DebarmentHttpResponse(
        status_code=200,
        body_json={"restriction_status": "CLEAR"},
        latency_ms=42,
        correlation_id="trace-1",
    )
    env = http_response_to_envelope(response)
    assert env.status_code == 200
    assert env.raw_response == {"restriction_status": "CLEAR"}
    assert env.latency_ms == 42
    assert env.correlation_id == "trace-1"


# ---------------------------------------------------------------------------
# Verified record shape
# ---------------------------------------------------------------------------


def test_verified_record_is_typed_model() -> None:
    transport = StaticDebarmentTransport(
        responses={"X": _env(status_code=200, raw=_CLEAR_PAYLOAD)}
    )
    adapter = DebarmentAdapter(transport=transport)
    v = adapter.verify("b", "X")
    assert isinstance(v, Verification)
    assert v.retrieved_at.tzinfo is not None
