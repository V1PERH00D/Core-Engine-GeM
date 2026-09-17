"""Tests for the MCA21 company registration rule (MCA21_REGISTRATION_001).

Covers:

* verified ACTIVE -> PASS with no flags,
* inactive / invalid -> FAIL with registry flags,
* NOT_FOUND / UNAVAILABLE / ERROR -> UNVERIFIABLE (never FAIL),
* missing / null CIN evidence -> MISSING with provenance preserved,
* explicitly not required -> NOT_APPLICABLE,
* explicitly configured ``required_status`` contradiction -> deterministic FAIL,
* provenance (evidence_refs / verification_refs preserved, enriched),
* boolean-only flags (registry-resolved, no severity / risk in output),
* determinism across repeated evaluation,
* adapter failure modes (default transport, transport error, 5xx, 4xx,
  malformed payload),
* canonical ``Capability.MCA21`` usage.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from compliance_engine.flags import get_flag_definition
from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules.mca import McaParameters, McaRegistrationRule
from compliance_engine.verification.mca_adapter import McaAdapter, McaQuery
from compliance_engine.verification.transport import (
    SourceResponseEnvelope,
    StaticTransport,
    TransportError,
)

RULE_ID = "MCA21_REGISTRATION_001"
CIN = "U27310KA2012PTC091234"


def _req(**params) -> Requirement:
    return Requirement(
        requirement_id="req-mca-1",
        capability=Capability.MCA21,
        description="MCA21 company registration must be verified.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        parameters=dict(params),
        rule_id=RULE_ID,
    )


def _cin_evidence(value: str | None = CIN) -> Evidence:
    return Evidence(
        evidence_id="doc-mca-1:cin",
        bidder_id="bidder-1",
        document_id="doc-mca-1",
        document_type="MCA",
        field_name="cin",
        value=value,
    )


def _verification(status: VerificationStatus, data: dict | None = None) -> Verification:
    return Verification(
        verification_id="MCA21:U27310KA2012PTC091234:call",
        bidder_id="bidder-1",
        capability=Capability.MCA21,
        source="MCA21",
        queried_identifier=CIN,
        status=status,
        data=data or {},
        retrieved_at=datetime.now(UTC),
    )


class _Provider:
    def __init__(self, verification: Verification) -> None:
        self.verification = verification

    def verify(self, bidder_id: str, identifier: str, **kwargs) -> Verification:
        return self.verification


def _run(evidence, verification, params: dict | None = None):
    return McaRegistrationRule().evaluate(
        evidence, _Provider(verification), _req(**(params or {}))
    )


# ---------------------------------------------------------------------------
# Rule: verified / failure / unverifiable semantics
# ---------------------------------------------------------------------------


def test_verified_registration_passes() -> None:
    r = _run([_cin_evidence()], _verification(VerificationStatus.VERIFIED))
    assert r.status is ComplianceStatus.PASS
    assert r.flags == []
    assert r.evidence_refs == ["doc-mca-1:cin"]
    assert r.verification_refs == ["MCA21:U27310KA2012PTC091234:call"]


def test_missing_cin_evidence_is_missing_not_pass() -> None:
    r = McaRegistrationRule().evaluate([], _Provider(_verification(VerificationStatus.VERIFIED)), _req())
    assert r.status is ComplianceStatus.MISSING
    assert r.flags == ["REQUIRED_FIELD_MISSING"]


def test_null_cin_value_is_missing_with_provenance() -> None:
    r = _run([_cin_evidence(None)], _verification(VerificationStatus.VERIFIED))
    assert r.status is ComplianceStatus.MISSING
    assert r.flags == ["REQUIRED_FIELD_MISSING"]
    # Provenance preserved even on the missing path.
    assert r.evidence_refs == ["doc-mca-1:cin"]


def test_wrong_document_type_is_missing() -> None:
    evidence = Evidence(
        evidence_id="doc-gst-1:cin",
        bidder_id="bidder-1",
        document_id="doc-gst-1",
        document_type="GST",
        field_name="cin",
        value=CIN,
    )
    r = _run([evidence], _verification(VerificationStatus.VERIFIED))
    assert r.status is ComplianceStatus.MISSING



def test_company_registration_doc_type_recognized() -> None:
    evidence = Evidence(
        evidence_id="doc-mca-2:cin",
        bidder_id="bidder-1",
        document_id="doc-mca-2",
        document_type="COMPANY_REGISTRATION",
        field_name="cin",
        value=CIN,
    )
    r = _run([evidence], _verification(VerificationStatus.VERIFIED))
    assert r.status is ComplianceStatus.PASS


def test_inactive_company_fails() -> None:
    r = _run([_cin_evidence()], _verification(VerificationStatus.INACTIVE))
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["COMPANY_INACTIVE"]


def test_invalid_cin_fails() -> None:
    r = _run([_cin_evidence()], _verification(VerificationStatus.INVALID))
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["CIN_INVALID"]


def test_cin_not_found_is_unverifiable() -> None:
    r = _run([_cin_evidence()], _verification(VerificationStatus.NOT_FOUND))
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["CIN_NOT_FOUND"]


def test_unavailable_is_unverifiable_never_fail() -> None:
    r = _run([_cin_evidence()], _verification(VerificationStatus.UNAVAILABLE))
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["MCA_VERIFICATION_UNAVAILABLE"]


def test_error_is_unverifiable_never_fail() -> None:
    r = _run([_cin_evidence()], _verification(VerificationStatus.ERROR))
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["MCA_VERIFICATION_UNAVAILABLE"]


def test_provider_failures_never_produce_positive_result() -> None:
    for status in (
        VerificationStatus.UNAVAILABLE,
        VerificationStatus.ERROR,
        VerificationStatus.NOT_FOUND,
    ):
        r = _run([_cin_evidence()], _verification(status))
        assert r.status is not ComplianceStatus.PASS
        assert r.status is not ComplianceStatus.FAIL


# ---------------------------------------------------------------------------
# Rule: applicability
# ---------------------------------------------------------------------------


def test_not_applicable_when_registration_not_required() -> None:
    r = McaRegistrationRule().evaluate(
        [], _Provider(_verification(VerificationStatus.VERIFIED)), _req(require_registration=False)
    )
    assert r.status is ComplianceStatus.NOT_APPLICABLE
    assert r.flags == []


def test_extra_parameters_are_forbidden() -> None:
    with pytest.raises(Exception):
        McaParameters(unknown_parameter="x")


# ---------------------------------------------------------------------------
# Rule: explicit required_status contradiction (deterministic failure)
# ---------------------------------------------------------------------------


def test_required_status_match_passes() -> None:
    r = _run(
        [_cin_evidence()],
        _verification(VerificationStatus.VERIFIED, {"company_status": "ACTIVE"}),
        {"required_status": "ACTIVE"},
    )
    assert r.status is ComplianceStatus.PASS
    assert r.flags == []


def test_required_status_contradiction_fails_inactive() -> None:
    r = _run(
        [_cin_evidence()],
        _verification(VerificationStatus.VERIFIED, {"company_status": "INACTIVE"}),
        {"required_status": "ACTIVE"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["COMPANY_INACTIVE"]


def test_required_status_contradiction_fails_strike_off() -> None:
    r = _run(
        [_cin_evidence()],
        _verification(VerificationStatus.VERIFIED, {"company_status": "STRIKE_OFF"}),
        {"required_status": "ACTIVE"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["COMPANY_STRIKE_OFF"]


def test_required_status_contradiction_fails_liquidation() -> None:
    r = _run(
        [_cin_evidence()],
        _verification(VerificationStatus.VERIFIED, {"company_status": "UNDER_LIQUIDATION"}),
        {"required_status": "ACTIVE"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["COMPANY_UNDER_LIQUIDATION"]


def test_required_status_missing_detail_does_not_fail() -> None:
    # The authoritative-source VERIFIED status is the compliance evidence;
    # a missing normalized detail does not contradict the requirement.
    r = _run(
        [_cin_evidence()],
        _verification(VerificationStatus.VERIFIED, {}),
        {"required_status": "ACTIVE"},
    )
    assert r.status is ComplianceStatus.PASS


def test_no_required_status_ignores_data_status() -> None:
    # Only explicitly configured parameters are checked.
    r = _run(
        [_cin_evidence()],
        _verification(VerificationStatus.VERIFIED, {"company_status": "SOMETHING_ELSE"}),
    )


# ---------------------------------------------------------------------------
# Rule: boolean flag contract, registry resolution, determinism, provenance
# ---------------------------------------------------------------------------


def test_emitted_flags_resolve_in_registry() -> None:
    for status, expected_flag in (
        (VerificationStatus.INACTIVE, "COMPANY_INACTIVE"),
        (VerificationStatus.INVALID, "CIN_INVALID"),
        (VerificationStatus.NOT_FOUND, "CIN_NOT_FOUND"),
        (VerificationStatus.UNAVAILABLE, "MCA_VERIFICATION_UNAVAILABLE"),
        (VerificationStatus.ERROR, "MCA_VERIFICATION_UNAVAILABLE"),
    ):
        r = _run([_cin_evidence()], _verification(status))
        assert r.flags == [expected_flag]
        # Registry-resolved canonical flag ID (raises UnknownFlagError otherwise).
        assert get_flag_definition(r.flags[0]).flag_id == expected_flag


def test_flags_are_plain_boolean_contract_strings() -> None:
    r = _run([_cin_evidence()], _verification(VerificationStatus.INACTIVE))
    dumped = r.model_dump(mode="json")
    # Downstream contract: flags are canonical string IDs only.
    assert all(isinstance(f, str) for f in dumped["flags"])
    assert not any("severity" in str(k).lower() for k in dumped)
    assert not any("risk" in str(k).lower() for k in dumped)


def test_deterministic_repeated_evaluation() -> None:
    verification = _verification(VerificationStatus.VERIFIED, {"company_status": "ACTIVE"})
    r1 = _run([_cin_evidence()], verification)
    r2 = _run([_cin_evidence()], verification)
    assert r1.status is r2.status
    assert r1.flags == r2.flags
    assert r1.reason == r2.reason
    assert r1.evidence_refs == r2.evidence_refs
    assert r1.verification_refs == r2.verification_refs
    assert r1.actual == r2.actual


def test_verification_evidence_provenance_enriched() -> None:
    r = _run([_cin_evidence()], _verification(VerificationStatus.VERIFIED))
    assert r.evidence_refs == ["doc-mca-1:cin"]
    assert r.verification_refs == ["MCA21:U27310KA2012PTC091234:call"]
    assert r.capability == Capability.MCA21
    assert r.rule_id == RULE_ID


# ---------------------------------------------------------------------------
# Adapter: capability, transports, parser failure modes
# ---------------------------------------------------------------------------


def _envelope(status_code: int, raw: dict | None = None) -> SourceResponseEnvelope:
    return SourceResponseEnvelope(
        status_code=status_code,
        raw_response=raw,
        latency_ms=12,
        correlation_id="corr-test",
    )


def _adapter(envelope: SourceResponseEnvelope | None = None) -> McaAdapter:
    transport = StaticTransport(
        default_response=envelope,
        query_key=lambda q: q.cin,
    )
    return McaAdapter(transport=transport)


def test_adapter_capability_is_canonical() -> None:
    adapter = _adapter(_envelope(200, {"company_status": "ACTIVE"}))
    verification = adapter.verify("bidder-1", CIN)
    assert verification.capability == Capability.MCA21
    assert verification.capability == "MCA21"
    assert adapter.SOURCE == "MCA21"
    assert verification.queried_identifier == CIN
    assert verification.bidder_id == "bidder-1"


def test_default_transport_maps_to_unavailable() -> None:
    # InProcessTransport raises NotImplementedError; the adapter must
    # translate it into UNAVAILABLE, never an exception or a positive result.
    adapter = McaAdapter()
    verification = adapter.verify("bidder-1", CIN)
    assert verification.status is VerificationStatus.UNAVAILABLE


def test_transport_error_maps_to_unavailable() -> None:
    class _FailingTransport:
        def send_query(self, query: McaQuery) -> SourceResponseEnvelope:
            raise TransportError("connection refused")

    adapter = McaAdapter(transport=_FailingTransport())
    verification = adapter.verify("bidder-1", CIN)
    assert verification.status is VerificationStatus.UNAVAILABLE


def test_5xx_maps_to_unavailable() -> None:
    verification = _adapter(_envelope(503)).verify("bidder-1", CIN)
    assert verification.status is VerificationStatus.UNAVAILABLE
    assert verification.data == {}


def test_404_without_payload_maps_to_not_found() -> None:
    verification = _adapter(_envelope(404, None)).verify("bidder-1", CIN)
    assert verification.status is VerificationStatus.NOT_FOUND


def test_4xx_with_status_payload_maps_to_domain_status() -> None:
    verified = _adapter(_envelope(422, {"company_status": "ACTIVE"})).verify("bidder-1", CIN)
    assert verified.status is VerificationStatus.VERIFIED
    inactive = _adapter(_envelope(422, {"company_status": "INACTIVE"})).verify("bidder-1", CIN)
    assert inactive.status is VerificationStatus.INACTIVE


def test_4xx_without_status_field_maps_to_invalid() -> None:
    verification = _adapter(_envelope(422, {"unexpected": "payload"})).verify("bidder-1", CIN)
    assert verification.status is VerificationStatus.INVALID


def test_2xx_without_payload_maps_to_error() -> None:
    verification = _adapter(_envelope(200, None)).verify("bidder-1", CIN)
    assert verification.status is VerificationStatus.ERROR


def test_2xx_unknown_status_value_maps_to_error() -> None:
    verification = _adapter(_envelope(200, {"company_status": "UNDER_TRANSITION"})).verify("bidder-1", CIN)
    assert verification.status is VerificationStatus.ERROR


def test_2xx_verified_carries_normalized_data() -> None:
    verification = _adapter(
        _envelope(200, {"company_status": "ACTIVE", "company_name": "ACME PVT LTD"})
    ).verify("bidder-1", CIN)
    assert verification.status is VerificationStatus.VERIFIED
    assert verification.data["company_status"] == "ACTIVE"
    assert verification.data["company_name"] == "ACME PVT LTD"


def test_adapter_transport_records_query() -> None:
    transport = StaticTransport(
        default_response=_envelope(200, {"company_status": "ACTIVE"}),
        query_key=lambda q: q.cin,
    )
    adapter = McaAdapter(transport=transport)
    adapter.verify("bidder-1", CIN)
    assert len(transport.queries) == 1
    assert transport.queries[0].cin == CIN
    assert transport.queries[0].bidder_id == "bidder-1"


def test_adapter_repeated_verification_is_deterministic() -> None:
    adapter = _adapter(_envelope(200, {"company_status": "ACTIVE"}))
    v1 = adapter.verify("bidder-1", CIN)
    v2 = adapter.verify("bidder-1", CIN)
    # Per-call IDs may differ; logical results must not.
    assert v1.status is v2.status
    assert v1.data == v2.data
    assert v1.capability == v2.capability


def test_adapter_transport_status_preserved_for_audit() -> None:
    verification = _adapter(_envelope(503)).verify("bidder-1", CIN)
    assert verification.transport_status_code == 503
    assert verification.correlation_id == "corr-test"


def test_rule_maps_adapter_unavailable_to_unverifiable() -> None:
    adapter = McaAdapter()  # default transport -> UNAVAILABLE
    verification = adapter.verify("bidder-1", CIN)
    r = _run([_cin_evidence()], verification)
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["MCA_VERIFICATION_UNAVAILABLE"]
