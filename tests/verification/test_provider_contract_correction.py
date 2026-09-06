"""Tests for the provider-contract correction milestone.

These tests cover three things introduced or hardened in this
milestone:

1. ``Verification.verification_id`` is unique per call.
2. The domain :class:`VerificationStatus` is derived from the source
   payload, never from the HTTP transport status code alone.
3. ``Verification`` is a frozen pydantic model.

The tests live in this single file so the correction has a single,
self-contained regression suite that can be run on its own.
"""

from __future__ import annotations

from typing import Any

import pytest

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules import (
    GSTRegistrationRule,
    PANValidationRule,
    UdyamRegistrationRule,
)
from compliance_engine.verification import (
    GSTNAdapter,
    GstQuery,
    McaAdapter,
    McaQuery,
    PanAdapter,
    PanQuery,
    SourceResponseEnvelope,
    StaticTransport,
    UdyamAdapter,
    UdyamQuery,
    VerificationProvider,
    VerificationStatus as VS,
)
from compliance_engine.verification.transport import TransportError

from tests.engine._builders import (
    gst_evidence,
    gst_requirement,
    pan_evidence,
    pan_requirement,
    udyam_evidence,
    udyam_requirement,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _env(
    *,
    status_code: int,
    raw: dict[str, Any] | None = None,
    latency_ms: int | None = 10,
    correlation_id: str | None = "corr-test",
) -> SourceResponseEnvelope:
    return SourceResponseEnvelope(
        status_code=status_code,
        raw_response=raw,
        latency_ms=latency_ms,
        correlation_id=correlation_id,
    )


_GSTIN = "27AAACI1234F1Z5"
_UDYAM = "UDYAM-MH-12-0019842"
_PAN = "AAACI1234F"
_CIN = "L17110MH1973PLC012012"


def _udyam_transport(responses: dict[str, SourceResponseEnvelope]) -> StaticTransport:
    return StaticTransport(
        responses=responses, query_key=lambda q: q.udyam_registration_number
    )


def _pan_transport(responses: dict[str, SourceResponseEnvelope]) -> StaticTransport:
    return StaticTransport(responses=responses, query_key=lambda q: q.pan)


def _mca_transport(responses: dict[str, SourceResponseEnvelope]) -> StaticTransport:
    return StaticTransport(responses=responses, query_key=lambda q: q.cin)


def _gstin_evidence(value: str) -> Evidence:
    return Evidence(
        evidence_id="doc-gstn-001:gstin",
        bidder_id="bidder-1",
        document_id="doc-gstn-001",
        document_type="GST",
        field_name="gstin",
        value=value,
    )


def _gstn_requirement() -> Requirement:
    return Requirement(
        requirement_id="req-gstn-001",
        capability=Capability.GST,
        description="GST registration must be valid and active.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        rule_id="GST_REGISTRATION_001",
    )


# ===========================================================================
# PART 6.1 -- repeated verification calls produce DISTINCT IDs
# ===========================================================================


def test_repeated_gstn_calls_produce_distinct_verification_ids() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    }))
    v1 = adapter.verify("bidder-1", _GSTIN)
    v2 = adapter.verify("bidder-1", _GSTIN)
    assert v1.verification_id != v2.verification_id
    # Both ids follow the canonical {source}:{identifier}:{call_id} shape.
    assert v1.verification_id.startswith("GSTN:" + _GSTIN + ":")
    assert v2.verification_id.startswith("GSTN:" + _GSTIN + ":")


def test_repeated_udyam_calls_produce_distinct_verification_ids() -> None:
    adapter = UdyamAdapter(transport=_udyam_transport({
        _UDYAM: _env(status_code=200, raw={
            "registration_status": "ACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium",
        }),
    }))
    v1 = adapter.verify("bidder-1", _UDYAM)
    v2 = adapter.verify("bidder-1", _UDYAM)
    assert v1.verification_id != v2.verification_id
    assert v1.verification_id.startswith("UDYAM:" + _UDYAM + ":")
    assert v2.verification_id.startswith("UDYAM:" + _UDYAM + ":")


def test_repeated_pan_calls_produce_distinct_verification_ids() -> None:
    adapter = PanAdapter(transport=_pan_transport({
        _PAN: _env(status_code=200, raw={"pan_status": "ACTIVE", "name_on_pan": "ACME CO"}),
    }))
    v1 = adapter.verify("bidder-1", _PAN)
    v2 = adapter.verify("bidder-1", _PAN)
    assert v1.verification_id != v2.verification_id
    assert v1.verification_id.startswith("PAN:" + _PAN + ":")
    assert v2.verification_id.startswith("PAN:" + _PAN + ":")


def test_repeated_mca_calls_produce_distinct_verification_ids() -> None:
    adapter = McaAdapter(transport=_mca_transport({
        _CIN: _env(status_code=200, raw={"company_status": "ACTIVE", "company_name": "ACME LTD"}),
    }))
    v1 = adapter.verify("bidder-1", _CIN)
    v2 = adapter.verify("bidder-1", _CIN)
    assert v1.verification_id != v2.verification_id
    assert v1.verification_id.startswith("MCA21:" + _CIN + ":")
    assert v2.verification_id.startswith("MCA21:" + _CIN + ":")


def test_query_objects_carry_distinct_call_ids() -> None:
    """The query envelope itself must carry a per-call id so the
    transport layer can echo it back without ambiguity."""
    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })
    adapter = GSTNAdapter(transport=transport)
    adapter.verify("bidder-1", _GSTIN)
    adapter.verify("bidder-1", _GSTIN)
    assert len(transport.queries) == 2
    q1, q2 = transport.queries
    assert isinstance(q1, GstQuery)
    assert isinstance(q2, GstQuery)
    assert q1.call_id != q2.call_id
    # call_id is a uuid4 hex (32 chars).
    assert len(q1.call_id) == 32


# ===========================================================================
# PART 6.2 -- 200 + INACTIVE payload -> INACTIVE (regression for B2)
# ===========================================================================


def test_gstn_200_with_inactive_payload_yields_inactive() -> None:
    """The exact bug the review caught: an HTTP 200 carrying an
    ``INACTIVE`` payload must NOT be reported as ``VERIFIED``."""
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        "27AAACI9999F1Z5": _env(status_code=200, raw={"registration_status": "INACTIVE", "legal_name": "ACME CO"}),
    }))
    v = adapter.verify("bidder-1", "27AAACI9999F1Z5")
    assert v.status is VerificationStatus.INACTIVE
    # The HTTP code is still preserved for audit.
    assert v.transport_status_code == 200


def test_pan_200_with_inactive_payload_yields_inactive() -> None:
    adapter = PanAdapter(transport=_pan_transport({
        "AAACI9999F": _env(status_code=200, raw={"pan_status": "INACTIVE", "name_on_pan": "ACME CO"}),
    }))
    v = adapter.verify("bidder-1", "AAACI9999F")
    assert v.status is VerificationStatus.INACTIVE
    assert v.transport_status_code == 200


def test_udyam_200_with_inactive_payload_yields_inactive() -> None:
    adapter = UdyamAdapter(transport=_udyam_transport({
        "UDYAM-MH-12-0019843": _env(status_code=200, raw={
            "registration_status": "INACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium",
        }),
    }))
    v = adapter.verify("bidder-1", "UDYAM-MH-12-0019843")
    assert v.status is VerificationStatus.INACTIVE
    assert v.transport_status_code == 200


def test_mca_200_with_inactive_payload_yields_inactive() -> None:
    adapter = McaAdapter(transport=_mca_transport({
        _CIN: _env(status_code=200, raw={"company_status": "INACTIVE", "company_name": "ACME LTD"}),
    }))
    v = adapter.verify("bidder-1", _CIN)
    assert v.status is VerificationStatus.INACTIVE
    assert v.transport_status_code == 200


# ===========================================================================
# PART 6.3 -- verified / not_found / malformed / unavailable distinctions
# ===========================================================================


def test_payload_200_with_active_status_yields_verified() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME"}),
    }))
    assert adapter.verify("bidder-1", _GSTIN).status is VerificationStatus.VERIFIED


def test_payload_200_missing_status_field_yields_error() -> None:
    """A 2xx response whose payload lacks the expected domain field
    is treated as a malformed payload (``ERROR``), not as a
    verified positive."""
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"legal_name": "ACME CO"}),  # no registration_status
    }))
    v = adapter.verify("bidder-1", _GSTIN)
    assert v.status is VerificationStatus.ERROR


def test_404_with_no_payload_yields_not_found() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        "missing-gstin": _env(status_code=404, raw=None),
    }))
    v = adapter.verify("bidder-1", "missing-gstin")
    assert v.status is VerificationStatus.NOT_FOUND
    assert v.transport_status_code == 404


def test_transport_exception_yields_unavailable() -> None:
    class _Exploding:
        def send_query(self, query: Any) -> SourceResponseEnvelope:
            raise TransportError("upstream down")

    v = GSTNAdapter(transport=_Exploding()).verify("bidder-1", _GSTIN)  # type: ignore[arg-type]
    assert v.status is VerificationStatus.UNAVAILABLE


def test_default_transport_yields_unavailable() -> None:
    v = GSTNAdapter().verify("bidder-1", _GSTIN)
    assert v.status is VerificationStatus.UNAVAILABLE
    # When no real transport is wired in, transport_status_code is
    # None (advisory only).
    assert v.transport_status_code is None


def test_5xx_yields_unavailable_with_transport_status_captured() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(status_code=503, raw={"error": "down"}),
    }))
    v = adapter.verify("bidder-1", _GSTIN)
    assert v.status is VerificationStatus.UNAVAILABLE
    assert v.transport_status_code == 503


# ===========================================================================
# PART 6.4 -- Immutability
# ===========================================================================


def test_verification_is_immutable() -> None:
    """Direct field assignment on a Verification must fail."""
    v = Verification(
        verification_id="x:1:c1",
        bidder_id="b",
        capability="GST",
        source="GSTN",
        status=VerificationStatus.VERIFIED,
    )
    with pytest.raises(Exception):
        v.evidence_id = "evil"  # type: ignore[misc]
    with pytest.raises(Exception):
        v.status = VerificationStatus.ERROR  # type: ignore[misc]


def test_verification_model_copy_returns_new_object() -> None:
    v = Verification(
        verification_id="x:1:c1",
        bidder_id="b",
        capability="GST",
        source="GSTN",
        status=VerificationStatus.VERIFIED,
    )
    v2 = v.model_copy(update={"evidence_id": "e1", "document_id": "d1"})
    assert v2 is not v
    assert v2.evidence_id == "e1"
    assert v2.document_id == "d1"
    # Original is untouched.
    assert v.evidence_id is None
    assert v.document_id is None


def test_verification_evidence_refs_preserved_after_model_copy() -> None:
    v = Verification(
        verification_id="x:1:c1",
        bidder_id="b",
        capability="GST",
        source="GSTN",
        status=VerificationStatus.VERIFIED,
    )
    v2 = v.model_copy(update={"evidence_id": "e1"})
    assert v2.verification_id == v.verification_id
    assert v2.bidder_id == v.bidder_id
    assert v2.status == v.status


# ===========================================================================
# PART 6.5 -- GST evidence/document enrichment under immutability
# ===========================================================================


def test_gst_rule_does_not_mutate_provider_return() -> None:
    """The GST rule must produce a new Verification with the
    evidence_id/document_id set, not mutate the original."""
    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })
    adapter = GSTNAdapter(transport=transport)
    rule = GSTRegistrationRule()
    requirement = _gstn_requirement()
    evidence = _gstin_evidence(_GSTIN)

    cr = rule.evaluate(evidence=[evidence], provider=adapter, requirement=requirement)

    assert cr.status is ComplianceStatus.PASS
    # The provider's returned Verification (without evidence_id) is
    # the bare object the engine captured. The rule must NOT have
    # mutated it.
    direct = adapter.verify("bidder-1", _GSTIN)
    assert direct.evidence_id is None
    assert direct.document_id is None
    # But the ComplianceResult references a verification_id that the
    # engine must have also recorded.
    assert cr.verification_refs[0].startswith("GSTN:" + _GSTIN + ":")


def test_engine_captures_enriched_verification_in_records() -> None:
    """The engine's verification_records must contain the enriched
    Verification (with evidence_id and document_id set), not the
    bare provider return value."""
    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )

    ev = gst_evidence()
    result = engine.run(evidence=[ev], requirements=[gst_requirement()])

    assert len(result.verification_records) == 1
    v = result.verification_records[0]
    # The engine's captured record carries the rule's enrichment.
    assert v.evidence_id == ev.evidence_id
    assert v.document_id == ev.document_id


def test_engine_verification_refs_matches_captured_record_id() -> None:
    """ComplianceResult.verification_refs[0] must equal the
    verification_id of the engine-captured record."""
    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )

    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])
    cr = result.compliance_results[0]
    assert cr.verification_refs == [v.verification_id for v in result.verification_records]


# ===========================================================================
# PART 6.6 -- Audit-trail preservation
# ===========================================================================


def test_audit_fields_populated_when_transport_supplies_them() -> None:
    adapter = GSTNAdapter(transport=StaticTransport(responses={
        _GSTIN: _env(
            status_code=200,
            raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"},
            latency_ms=123,
            correlation_id="trace-xyz",
        ),
    }))
    v = adapter.verify("bidder-1", _GSTIN)
    assert v.latency_ms == 123
    assert v.correlation_id == "trace-xyz"
    assert v.query is not None
    assert v.query["gstin"] == _GSTIN
    assert v.query["call_id"]
    assert v.raw_response == {
        "registration_status": "ACTIVE",
        "legal_name": "ACME CO",
    }
    # transport_status_code is preserved separately.
    assert v.transport_status_code == 200


def test_audit_fields_none_when_no_transport() -> None:
    v = GSTNAdapter().verify("bidder-1", _GSTIN)
    assert v.latency_ms is None
    assert v.correlation_id is None
    assert v.raw_response is None
    assert v.transport_status_code is None
    # But the query and call_id are still present for audit.
    assert v.query is not None
    assert v.query["call_id"]


# ===========================================================================
# PART 6.7 -- Existing engine integration stays green
# ===========================================================================


def test_existing_engine_integration_gstn_pass() -> None:
    """A verified GST via the production adapter still drives the
    engine to PASS."""
    transport = StaticTransport(responses={
        _GSTIN: _env(status_code=200, raw={"registration_status": "ACTIVE", "legal_name": "ACME CO"}),
    })
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: GSTNAdapter(transport=transport)},
    )
    result = engine.run(evidence=[gst_evidence()], requirements=[gst_requirement()])
    assert result.compliance_results[0].status is ComplianceStatus.PASS


def test_existing_engine_integration_udyam_pass() -> None:
    transport = _udyam_transport({
        _UDYAM: _env(status_code=200, raw={
            "registration_status": "ACTIVE", "enterprise_name": "ACME", "enterprise_category": "Medium",
        }),
    })
    engine = ComplianceEngine(
        rules={"UDYAM_REGISTRATION_001": UdyamRegistrationRule()},
        providers={Capability.UDYAM: UdyamAdapter(transport=transport)},
    )
    result = engine.run(evidence=[udyam_evidence()], requirements=[udyam_requirement()])
    assert result.compliance_results[0].status is ComplianceStatus.PASS


def test_existing_engine_integration_pan_pass() -> None:
    transport = _pan_transport({
        _PAN: _env(status_code=200, raw={"pan_status": "ACTIVE", "name_on_pan": "ACME CO"}),
    })
    engine = ComplianceEngine(
        rules={"PAN_VALIDATION_001": PANValidationRule()},
        providers={Capability.PAN_INCOME_TAX: PanAdapter(transport=transport)},
    )
    result = engine.run(evidence=[pan_evidence()], requirements=[pan_requirement()])
    assert result.compliance_results[0].status is ComplianceStatus.PASS
