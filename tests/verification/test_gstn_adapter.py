"""Tests for the production-shaped GSTN adapter foundation.

These tests cover:

* the transport / parser / adapter boundary
* deterministic status mapping (200 -> VERIFIED, 404 -> NOT_FOUND, etc.)
* the normalized ``Verification.data`` contract
* raw-response and audit-field preservation
* safety: no network, no mutation, fresh objects
* end-to-end integration with the existing GST compliance rule
* end-to-end integration with the ComplianceEngine -> EngineResult pipeline
* extensibility: a different provider with the same contract works too
"""

from __future__ import annotations

import pytest
from datetime import UTC, datetime
from typing import Any

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
    Applicability,
    VerificationStatus,
)
from compliance_engine.rules import GSTRegistrationRule
from compliance_engine.verification import (
    GSTNAdapter,
    GstQuery,
    GstResponseEnvelope,
    GstResponseParser,
    InProcessTransport,
    NormalizedGstData,
    StaticTransport,
    TransportError,
    VerificationProvider,
)

from tests.engine._builders import gst_evidence, gst_requirement


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_envelope(
    *,
    status_code: int,
    raw: dict[str, Any] | None = None,
    latency_ms: int | None = 10,
    correlation_id: str | None = "corr-test",
) -> GstResponseEnvelope:
    return GstResponseEnvelope(
        status_code=status_code,
        raw_response=raw,
        latency_ms=latency_ms,
        correlation_id=correlation_id,
    )


# ---------------------------------------------------------------------------
# 1. Verified provider response
# ---------------------------------------------------------------------------


def test_verified_response_maps_to_verified_status() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={
                    "registration_status": "ACTIVE",
                    "legal_name": "ACME ENTERPRISES PRIVATE LIMITED",
                },
                latency_ms=42,
                correlation_id="corr-verified",
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.VERIFIED
    assert result.bidder_id == "bidder-1"
    assert result.queried_identifier == "27AAACI1234F1Z5"
    assert result.source == "GSTN"
    assert result.capability == Capability.GST


def test_verified_response_preserves_audit_fields() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
                latency_ms=99,
                correlation_id="trace-1",
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    # query is preserved for audit (and now includes a per-call
    # ``call_id`` so two consecutive calls remain distinguishable).
    assert result.query is not None
    assert result.query["bidder_id"] == "bidder-1"
    assert result.query["gstin"] == "27AAACI1234F1Z5"
    assert result.query["call_id"]
    # raw_response is preserved verbatim
    assert result.raw_response == {
        "registration_status": "ACTIVE",
        "legal_name": "ACME CO",
    }
    # latency_ms and correlation_id flow through
    assert result.latency_ms == 99
    assert result.correlation_id == "trace-1"
    # transport status code is captured for audit
    assert result.transport_status_code == 200


# ---------------------------------------------------------------------------
# 2. NOT_FOUND response
# ---------------------------------------------------------------------------


def test_not_found_response_maps_to_not_found_status() -> None:
    transport = StaticTransport(
        responses={
            "27AAAAA0000A1Z5": _make_envelope(status_code=404, raw=None)
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAAAA0000A1Z5")

    assert result.status is VerificationStatus.NOT_FOUND
    # No data when the source did not return a payload.
    assert result.data == {}
    assert result.raw_response is None


# ---------------------------------------------------------------------------
# 3. INACTIVE response
# ---------------------------------------------------------------------------


def test_inactive_response_maps_to_inactive_status() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI9999F1Z5": _make_envelope(
                status_code=410,
                raw={"registration_status": "INACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI9999F1Z5")

    assert result.status is VerificationStatus.INACTIVE
    # Normalized data is still populated so the rule can surface it.
    assert result.data == {
        "registration_status": "INACTIVE",
        "legal_name": "ACME CO",
    }


# ---------------------------------------------------------------------------
# 4. INVALID response
# ---------------------------------------------------------------------------


def test_invalid_response_maps_to_invalid_status() -> None:
    """A 4xx with a payload that lacks a recognizable domain field
    is interpreted as the source rejecting the identifier
    (``INVALID``), not as a missing record."""

    transport = StaticTransport(
        responses={
            "27XXXXX9999X1Z5": _make_envelope(
                status_code=400, raw={"error": "malformed identifier"}
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27XXXXX9999X1Z5")

    assert result.status is VerificationStatus.INVALID
    assert result.data == {}


# ---------------------------------------------------------------------------
# 5. Unavailable / Error responses
# ---------------------------------------------------------------------------


def test_unavailable_response_maps_to_unavailable_status() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(status_code=503, raw=None)
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.UNAVAILABLE


def test_unknown_transport_status_maps_to_error() -> None:
    """A non-standard status code (outside 2xx/4xx/5xx) must map to ERROR."""

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(status_code=999, raw=None)
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.ERROR


def test_transport_exception_maps_to_unavailable() -> None:
    """A transport that raises must be caught and surfaced as
    UNAVAILABLE so the rule layer never sees a transport exception."""

    class _ExplodingTransport:
        def send_query(self, query: GstQuery) -> GstResponseEnvelope:
            raise TransportError("upstream down")

    adapter = GSTNAdapter(transport=_ExplodingTransport())  # type: ignore[arg-type]

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.UNAVAILABLE
    assert result.raw_response is None
    assert result.data == {}


def test_default_in_process_transport_is_unavailable() -> None:
    """A GSTNAdapter with the default transport must NOT call the
    network: it must return UNAVAILABLE safely."""

    adapter = GSTNAdapter()  # no transport injected

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.status is VerificationStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# 6. Normalized Verification.data
# ---------------------------------------------------------------------------


def test_normalized_data_for_verified_response() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    # The exact shape the existing GST rule consumes:
    assert set(result.data.keys()) == {"registration_status", "legal_name"}
    assert result.data["registration_status"] == "ACTIVE"
    assert result.data["legal_name"] == "ACME CO"


def test_normalized_data_excludes_unrelated_payload_fields() -> None:
    """Fields the GST rule does not consume must not leak into
    ``Verification.data``; they stay in ``raw_response`` for audit."""

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={
                    "registration_status": "ACTIVE",
                    "legal_name": "ACME CO",
                    "address": "some address the rule ignores",
                    "tax_payer_type": "Regular",
                },
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert "address" not in result.data
    assert "tax_payer_type" not in result.data
    # But they survive in raw_response for audit.
    assert result.raw_response["address"] == "some address the rule ignores"
    assert result.raw_response["tax_payer_type"] == "Regular"


# ---------------------------------------------------------------------------
# 7. Raw response preservation
# ---------------------------------------------------------------------------


def test_raw_response_preserved_when_provided() -> None:
    raw = {
        "registration_status": "ACTIVE",
        "legal_name": "ACME CO",
        "extra": {"nested": "value"},
    }
    transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _make_envelope(status_code=200, raw=raw)}
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.raw_response == raw


def test_raw_response_is_none_when_not_provided() -> None:
    transport = StaticTransport(
        responses={"27AAACI1234F1Z5": _make_envelope(status_code=200, raw=None)}
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.raw_response is None


# ---------------------------------------------------------------------------
# 8. Optional audit fields remain None when no transport exists
# ---------------------------------------------------------------------------


def test_optional_audit_fields_remain_none_on_unavailable() -> None:
    adapter = GSTNAdapter()  # default in-process transport

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.latency_ms is None
    assert result.correlation_id is None
    # query is still populated for audit even on UNAVAILABLE. It now
    # also carries the per-call ``call_id`` so that two consecutive
    # unavailable calls for the same identifier remain
    # distinguishable.
    assert result.query is not None
    assert result.query["bidder_id"] == "bidder-1"
    assert result.query["gstin"] == "27AAACI1234F1Z5"
    assert result.query["call_id"]


def test_optional_audit_fields_come_from_envelope_when_provided() -> None:
    """If the canned envelope has them, they show up on the Verification."""

    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
                latency_ms=77,
                correlation_id="trace-77",
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    assert result.latency_ms == 77
    assert result.correlation_id == "trace-77"


# ---------------------------------------------------------------------------
# 9. Provider returns a fresh Verification object
# ---------------------------------------------------------------------------


def test_adapter_returns_fresh_verification_per_call() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    v1 = adapter.verify("bidder-1", "27AAACI1234F1Z5")
    v2 = adapter.verify("bidder-1", "27AAACI1234F1Z5")

    # Two distinct Python objects.
    assert v1 is not v2
    # Two calls for the same source + identifier must produce
    # DISTINCT verification IDs so the audit trail can tell them
    # apart.
    assert v1.verification_id != v2.verification_id
    # All other fields are deterministic and equal. ``retrieved_at``
    # is intentionally wall-clock and not asserted equal.
    for field in (
        "bidder_id",
        "capability",
        "source",
        "queried_identifier",
        "status",
        "data",
        "raw_response",
        "latency_ms",
        "correlation_id",
        "transport_status_code",
    ):
        assert getattr(v1, field) == getattr(v2, field), field
    # ``query`` is a dict and may carry a distinct ``call_id`` per
    # call. The other keys must still match.
    assert v1.query is not None
    assert v2.query is not None
    assert v1.query["bidder_id"] == v2.query["bidder_id"]
    assert v1.query["gstin"] == v2.query["gstin"]
    assert v1.query["call_id"] != v2.query["call_id"]


# ---------------------------------------------------------------------------
# 10. Provider does not mutate input
# ---------------------------------------------------------------------------


def test_adapter_does_not_mutate_inputs() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    gstin = "27AAACI1234F1Z5"
    before = id(gstin)
    result = adapter.verify("bidder-1", gstin)
    after = id(gstin)
    assert before == after
    # The result is a fresh object.
    assert result.bidder_id == "bidder-1"
    assert result.queried_identifier == gstin


def test_transport_does_not_mutate_injected_responses() -> None:
    """The adapter must not modify the canned envelope that was
    injected for tests."""

    envelope = _make_envelope(
        status_code=200,
        raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
    )
    transport = StaticTransport(responses={"27AAACI1234F1Z5": envelope})
    adapter = GSTNAdapter(transport=transport)

    adapter.verify("bidder-1", "27AAACI1234F1Z5")
    adapter.verify("bidder-1", "27AAACI1234F1Z5")

    # The injected envelope is unchanged.
    assert envelope.raw_response == {
        "registration_status": "ACTIVE",
        "legal_name": "ACME CO",
    }


# ---------------------------------------------------------------------------
# 11. Existing GST rule semantics remain unchanged
# ---------------------------------------------------------------------------


def _gst_requirement() -> Requirement:
    return Requirement(
        requirement_id="req-gstn-001",
        capability=Capability.GST,
        description="GST registration must be valid and active.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        rule_id="GST_REGISTRATION_001",
    )


def _gstin_evidence(value: str) -> Evidence:
    return Evidence(
        evidence_id="doc-gstn-001:gstin",
        bidder_id="bidder-1",
        document_id="doc-gstn-001",
        document_type="GST",
        field_name="gstin",
        value=value,
    )


def test_gst_rule_with_gstn_adapter_verified_yields_pass() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = GSTRegistrationRule().evaluate(
        evidence=[_gstin_evidence("27AAACI1234F1Z5")],
        provider=adapter,
        requirement=_gst_requirement(),
    )

    assert result.status is ComplianceStatus.PASS
    assert result.actual["status"] is VerificationStatus.VERIFIED


def test_gst_rule_with_gstn_adapter_not_found_yields_unverifiable() -> None:
    transport = StaticTransport(
        responses={"27AAAAA0000A1Z5": _make_envelope(status_code=404, raw=None)}
    )
    adapter = GSTNAdapter(transport=transport)

    result = GSTRegistrationRule().evaluate(
        evidence=[_gstin_evidence("27AAAAA0000A1Z5")],
        provider=adapter,
        requirement=_gst_requirement(),
    )

    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.actual["status"] is VerificationStatus.NOT_FOUND


def test_gst_rule_with_gstn_adapter_inactive_yields_fail() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI9999F1Z5": _make_envelope(
                status_code=410,
                raw={"registration_status": "INACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    result = GSTRegistrationRule().evaluate(
        evidence=[_gstin_evidence("27AAACI9999F1Z5")],
        provider=adapter,
        requirement=_gst_requirement(),
    )

    assert result.status is ComplianceStatus.FAIL
    assert result.actual["status"] is VerificationStatus.INACTIVE


def test_gst_rule_with_gstn_adapter_unavailable_does_not_pass() -> None:
    """A unavailable transport must not yield a PASS even if the
    identifier looks valid."""

    adapter = GSTNAdapter()  # default = UNAVAILABLE

    result = GSTRegistrationRule().evaluate(
        evidence=[_gstin_evidence("27AAACI1234F1Z5")],
        provider=adapter,
        requirement=_gst_requirement(),
    )

    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.actual["status"] is VerificationStatus.UNAVAILABLE


# ---------------------------------------------------------------------------
# 12. EngineResult still captures the Verification
# ---------------------------------------------------------------------------


def test_engine_result_captures_gstn_adapter_verification() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
                latency_ms=50,
                correlation_id="trace-engine",
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: adapter},
    )

    result = engine.run(
        evidence=[_gstin_evidence("27AAACI1234F1Z5")],
        requirements=[_gst_requirement()],
    )

    assert len(result.verification_records) == 1
    v = result.verification_records[0]
    # verification_id is now per-call-unique; assert the prefix and
    # that the captured object matches the one referenced by the
    # compliance result.
    assert v.verification_id.startswith("GSTN:27AAACI1234F1Z5:")
    assert v.source == "GSTN"
    # Audit fields survive end-to-end.
    assert v.latency_ms == 50
    assert v.correlation_id == "trace-engine"
    assert v.transport_status_code == 200
    assert v.query is not None
    assert v.query["bidder_id"] == "bidder-1"
    assert v.query["gstin"] == "27AAACI1234F1Z5"
    assert v.query["call_id"]


# ---------------------------------------------------------------------------
# 13. ComplianceResult.verification_refs still references the same id
# ---------------------------------------------------------------------------


def test_compliance_result_verification_refs_matches_engine_record() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: adapter},
    )

    result = engine.run(
        evidence=[_gstin_evidence("27AAACI1234F1Z5")],
        requirements=[_gst_requirement()],
    )

    cr = result.compliance_results[0]
    # The verification_id is now per-call-unique. The rule still
    # emits it in ``verification_refs`` and the engine captures the
    # same object in ``verification_records``.
    assert len(cr.verification_refs) == 1
    vid = cr.verification_refs[0]
    assert vid.startswith("GSTN:27AAACI1234F1Z5:")
    assert [v.verification_id for v in result.verification_records] == cr.verification_refs


# ---------------------------------------------------------------------------
# 14. Extensibility: another provider can be substituted for GST
# ---------------------------------------------------------------------------


class _AlternateGSTProvider(VerificationProvider):
    """A different GST provider implementation showing that the engine
    accepts any ``VerificationProvider`` without modification."""

    SOURCE = "ALT_GST"

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any):
        from compliance_engine.models import Verification
        return Verification(
            verification_id=f"{self.SOURCE}:{identifier}",
            bidder_id=bidder_id,
            capability=Capability.GST,
            source=self.SOURCE,
            queried_identifier=identifier,
            status=VerificationStatus.VERIFIED,
            data={"registration_status": "ACTIVE", "legal_name": "ALT CO"},
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_engine_accepts_alternate_gst_provider() -> None:
    """The engine does not depend on the GSTNAdapter specifically; any
    ``VerificationProvider`` for the GST capability plugs in."""

    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: _AlternateGSTProvider()},
    )

    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert len(cr.verification_refs) == 1
    assert cr.verification_refs[0].startswith("ALT_GST:")


# ---------------------------------------------------------------------------
# 15. Transport seam is injectable and observed
# ---------------------------------------------------------------------------


def test_transport_receives_typed_query() -> None:
    transport = StaticTransport(
        responses={
            "27AAACI1234F1Z5": _make_envelope(
                status_code=200,
                raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
            )
        }
    )
    adapter = GSTNAdapter(transport=transport)

    adapter.verify("bidder-42", "27AAACI1234F1Z5")

    assert len(transport.queries) == 1
    q = transport.queries[0]
    assert q.bidder_id == "bidder-42"
    assert q.gstin == "27AAACI1234F1Z5"


def test_static_transport_default_404_for_unknown_gstin() -> None:
    transport = StaticTransport()
    adapter = GSTNAdapter(transport=transport)

    result = adapter.verify("bidder-1", "unknown-gstin")

    assert result.status is VerificationStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# 16. Parser is a separate, testable unit
# ---------------------------------------------------------------------------


def test_parser_handles_verified_envelope() -> None:
    parser = GstResponseParser()
    envelope = _make_envelope(
        status_code=200,
        raw={"registration_status": "ACTIVE", "legal_name": "X"},
    )
    query = GstQuery(bidder_id="b", gstin="g")

    v = parser.parse(envelope, query=query, bidder_id="b")

    assert v.status is VerificationStatus.VERIFIED
    assert v.data == {"registration_status": "ACTIVE", "legal_name": "X"}


def test_parser_does_not_populate_data_for_error_status() -> None:
    parser = GstResponseParser()
    envelope = _make_envelope(
        status_code=999,
        raw={"registration_status": "ACTIVE", "legal_name": "X"},
    )
    query = GstQuery(bidder_id="b", gstin="g")

    v = parser.parse(envelope, query=query, bidder_id="b")

    # 999 is outside the table, so it maps to ERROR and the data dict
    # is not populated (we don't trust unknown payloads).
    assert v.status is VerificationStatus.ERROR
    assert v.data == {}


# ---------------------------------------------------------------------------
# 17. Normalized data is structurally enforced
# ---------------------------------------------------------------------------


def test_normalized_gst_data_rejects_extra_fields() -> None:
    with pytest.raises(Exception):
        NormalizedGstData(
            registration_status="ACTIVE",
            legal_name="ACME",
            unexpected_field="x",
        )
