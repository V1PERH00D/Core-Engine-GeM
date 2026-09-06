"""End-to-end tests for the procurement-eligibility / debarment
capability, including:

* risk engine integration (active restriction drives HIGH_RISK,
  expired does not create active risk, unavailable does not
  create HIGH_RISK by itself),
* deterministic risk attribution,
* identity / normalizer compatibility,
* ComplianceEngine integration (the rule plugs into the engine
  through the existing executor and tracking wrapper),
* Verification object consumability by AI verification,
* no provider re-query.
"""

from __future__ import annotations

from datetime import date, UTC, datetime
from typing import Any

import pytest

from ai_verification.risk import (
    BidderRiskEngine,
    RiskState,
)
from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules import DebarmentEligibilityRule
from compliance_engine.verification import (
    DebarmentAdapter,
    StaticDebarmentTransport,
)
from compliance_engine.verification.debarment_models import (
    DEBARMENT_CAPABILITY,
)
from compliance_engine.verification.transport import SourceResponseEnvelope


RULE_ID = "DEBARMENT_ELIGIBILITY_001"


def _evidence(value: str = "27AAACI1234F1Z5") -> Evidence:
    return Evidence(
        evidence_id="doc-deb-001:debarment_identifier",
        bidder_id="bidder_acme_01",
        document_id="doc-deb-001",
        document_type="DEBARMENT",
        field_name="debarment_identifier",
        value=value,
    )


def _requirement(
    *,
    evaluation_date: date | None = None,
    requirement_id: str = "req-debarment-001",
) -> Requirement:
    parameters: dict[str, Any] = {}
    if evaluation_date is not None:
        parameters["evaluation_date"] = evaluation_date
    return Requirement(
        requirement_id=requirement_id,
        capability=DEBARMENT_CAPABILITY,
        description="Procurement eligibility must be verified.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="CLEAR",
        rule_id=RULE_ID,
        parameters=parameters,
    )


def _env(
    *,
    status_code: int,
    raw: dict[str, Any] | None = None,
) -> SourceResponseEnvelope:
    return SourceResponseEnvelope(
        status_code=status_code, raw_response=raw, latency_ms=10,
        correlation_id="corr-test",
    )


def _active_restricted_payload() -> dict[str, Any]:
    return {
        "restriction_status": "RESTRICTED",
        "restriction_type": "DEBARMENT",
        "effective_date": "2024-01-01",
        "end_date": "2026-12-31",
        "issuing_authority": "GeM",
        "reference_number": "REF-2024-001",
        "subject_type": "ORGANIZATION",
        "subject_identifier": "27AAACI1234F1Z5",
        "subject_name_original": "ACME ENTERPRISES PRIVATE LIMITED",
        "match_method": "EXACT_IDENTIFIER",
    }


def _clear_payload() -> dict[str, Any]:
    return {
        "restriction_status": "CLEAR",
        "match_method": "EXACT_IDENTIFIER",
    }


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------


def test_engine_runs_debarment_rule_through_executor() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=_clear_payload()
                )
            }
        )
    )
    engine = ComplianceEngine(
        rules={RULE_ID: DebarmentEligibilityRule()},
        providers={DEBARMENT_CAPABILITY: adapter},
    )
    result = engine.run(
        evidence=[_evidence()],
        requirements=[_requirement(evaluation_date=date(2025, 6, 15))],
    )
    assert result.compliance_results
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.rule_id == RULE_ID
    # The Verification object was captured by the engine.
    assert len(result.verification_records) == 1


def test_engine_records_verification_with_evidence_enrichment() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=_active_restricted_payload()
                )
            }
        )
    )
    engine = ComplianceEngine(
        rules={RULE_ID: DebarmentEligibilityRule()},
        providers={DEBARMENT_CAPABILITY: adapter},
    )
    result = engine.run(
        evidence=[_evidence()],
        requirements=[_requirement(evaluation_date=date(2025, 6, 15))],
    )
    v = result.verification_records[0]
    assert v.evidence_id == "doc-deb-001:debarment_identifier"
    assert v.document_id == "doc-deb-001"
    assert v.capability == DEBARMENT_CAPABILITY
    # The verification_refs on the ComplianceResult must match.
    assert result.compliance_results[0].verification_refs == [
        v.verification_id
    ]


def test_engine_handles_multiple_debarment_requirements() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=_active_restricted_payload()
                )
            }
        )
    )
    engine = ComplianceEngine(
        rules={RULE_ID: DebarmentEligibilityRule()},
        providers={DEBARMENT_CAPABILITY: adapter},
    )
    result = engine.run(
        evidence=[_evidence()],
        requirements=[
            _requirement(evaluation_date=date(2025, 6, 15)),
            _requirement(
                evaluation_date=date(2025, 6, 15),
                requirement_id="req-debarment-002",
            ),
        ],
    )
    # Both requirements must be evaluated; the engine re-queries the
    # provider for each, producing distinct verification IDs.
    assert len(result.compliance_results) == 2
    assert len(result.verification_records) == 2
    assert (
        result.verification_records[0].verification_id
        != result.verification_records[1].verification_id
    )


# ---------------------------------------------------------------------------
# Risk engine integration
# ---------------------------------------------------------------------------


def _critical_capability_verifications() -> list[Verification]:
    return [
        Verification(
            verification_id="v-gst",
            bidder_id="bidder_acme_01",
            capability="GST / GSTN",
            source="GSTN_MOCK",
            status=VerificationStatus.VERIFIED,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        Verification(
            verification_id="v-pan",
            bidder_id="bidder_acme_01",
            capability="PAN / Income Tax",
            source="PAN_MOCK",
            status=VerificationStatus.VERIFIED,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
        Verification(
            verification_id="v-uid",
            bidder_id="bidder_acme_01",
            capability="Bidder Identity",
            source="BIDDER_IDENTITY_MOCK",
            status=VerificationStatus.VERIFIED,
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    ]


def test_active_restriction_drives_high_risk_signal() -> None:
    from compliance_engine.flags import get_flag_definition
    from compliance_engine.models import ComplianceResult
    from compliance_engine.models.result import ComplianceStatus

    cr = ComplianceResult(
        requirement_id="req-debarment-001",
        capability=DEBARMENT_CAPABILITY,
        status=ComplianceStatus.FAIL,
        reason="active restriction",
        evidence_refs=["doc-deb-001:debarment_identifier"],
        verification_refs=["v-deb"],
        flags=["PROCUREMENT_DEBARMENT_ACTIVE"],
        rule_id=RULE_ID,
    )
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "bidder_acme_01",
        compliance_results=[cr],
        verification_records=_critical_capability_verifications(),
    )
    assert assessment.risk_state is RiskState.HIGH_RISK
    assert assessment.strongest_signal is not None
    assert (
        assessment.strongest_signal.severity
        == get_flag_definition("PROCUREMENT_DEBARMENT_ACTIVE").severity.value
    )


def test_unavailable_does_not_create_high_risk() -> None:
    from compliance_engine.models.result import ComplianceStatus
    from compliance_engine.models import ComplianceResult

    cr = ComplianceResult(
        requirement_id="req-debarment-001",
        capability=DEBARMENT_CAPABILITY,
        status=ComplianceStatus.UNVERIFIABLE,
        reason="source unavailable",
        evidence_refs=["doc-deb-001:debarment_identifier"],
        verification_refs=["v-deb"],
        flags=["PROCUREMENT_ELIGIBILITY_UNVERIFIABLE"],
        rule_id=RULE_ID,
    )
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "bidder_acme_01",
        compliance_results=[cr],
        verification_records=_critical_capability_verifications(),
    )
    # UNVERIFIABLE is treated as availability/uncertainty, not
    # as a HIGH_RISK by itself.
    assert assessment.risk_state is not RiskState.HIGH_RISK


def test_expired_restriction_passes_does_not_create_active_risk() -> None:
    from compliance_engine.models.result import ComplianceStatus
    from compliance_engine.models import ComplianceResult

    cr = ComplianceResult(
        requirement_id="req-debarment-001",
        capability=DEBARMENT_CAPABILITY,
        status=ComplianceStatus.PASS,
        reason="expired restriction",
        evidence_refs=["doc-deb-001:debarment_identifier"],
        verification_refs=["v-deb"],
        flags=[],
        rule_id=RULE_ID,
        actual={"historical_restriction": True},
    )
    engine = BidderRiskEngine()
    assessment = engine.assess(
        "bidder_acme_01",
        compliance_results=[cr],
        verification_records=_critical_capability_verifications(),
    )
    assert assessment.risk_state is RiskState.CLEAR


def test_risk_assessment_is_deterministic() -> None:
    from compliance_engine.flags import get_flag_definition
    from compliance_engine.models import ComplianceResult
    from compliance_engine.models.result import ComplianceStatus

    cr = ComplianceResult(
        requirement_id="req-debarment-001",
        capability=DEBARMENT_CAPABILITY,
        status=ComplianceStatus.FAIL,
        reason="active",
        evidence_refs=["doc-deb-001:debarment_identifier"],
        verification_refs=["v-deb"],
        flags=["PROCUREMENT_DEBARMENT_ACTIVE"],
        rule_id=RULE_ID,
    )
    engine = BidderRiskEngine()
    inputs = dict(
        bidder_id="bidder_acme_01",
        compliance_results=[cr],
        verification_records=_critical_capability_verifications(),
    )
    a1 = engine.assess(**inputs)
    a2 = engine.assess(**inputs)
    assert a1.risk_state == a2.risk_state
    assert a1.aggregate_score == a2.aggregate_score
    assert a1.summary == a2.summary
    # The strongest signal's severity matches the registry.
    assert a1.strongest_signal is not None
    assert (
        a1.strongest_signal.severity
        == get_flag_definition("PROCUREMENT_DEBARMENT_ACTIVE").severity.value
    )


# ---------------------------------------------------------------------------
# Identity compatibility
# ---------------------------------------------------------------------------


def test_subject_name_uses_identity_normalizer() -> None:
    """The adapter must reuse the identity normalizer for subject names."""
    from ai_verification.identity.normalization import (
        NAME_NORMALIZATION_VERSION,
        normalize_legal_name,
    )

    # The subject name on the source side flows through the
    # existing identity normalizer.
    raw = _active_restricted_payload()
    raw["subject_name_original"] = "  ACME Enterprises Private Limited "
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=raw
                )
            }
        )
    )
    v = adapter.verify("bidder_acme_01", "27AAACI1234F1Z5")
    assert v.data["subject_name_normalized"] == normalize_legal_name(
        "  ACME Enterprises Private Limited "
    )
    # The normalizer is versioned so audit consumers can verify
    # which rules were in effect.
    assert NAME_NORMALIZATION_VERSION == "identity-name-v1"


def test_subject_name_preserved_original_and_normalized() -> None:
    raw = _active_restricted_payload()
    raw["subject_name_original"] = "ACME ENTERPRISES PRIVATE LIMITED"
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=raw
                )
            }
        )
    )
    v = adapter.verify("bidder_acme_01", "27AAACI1234F1Z5")
    # Original preserved verbatim.
    assert v.data["subject_name_original"] == (
        "ACME ENTERPRISES PRIVATE LIMITED"
    )
    # Normalized via the identity normalizer.
    assert v.data["subject_name_normalized"] is not None


# ---------------------------------------------------------------------------
# AI Verification consumability
# ---------------------------------------------------------------------------


def test_verification_object_is_consumable_by_ai_verification() -> None:
    # The Verification returned by the adapter must carry the
    # same fields the existing AI verification pipeline reads.
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=_active_restricted_payload()
                )
            }
        )
    )
    v = adapter.verify("bidder_acme_01", "27AAACI1234F1Z5")
    # The Verification object is a frozen pydantic model with
    # all the audit fields AI verification reads.
    from compliance_engine.models import Verification
    assert isinstance(v, Verification)
    assert v.verification_id
    assert v.bidder_id == "bidder_acme_01"
    assert v.capability == DEBARMENT_CAPABILITY
    assert v.source
    assert v.queried_identifier
    assert v.status is VerificationStatus.VERIFIED
    assert isinstance(v.data, dict)
    assert v.retrieved_at.tzinfo is not None


def test_no_provider_re_query() -> None:
    # A rule.evaluate call must call the provider exactly once.
    # A subsequent compliance engine access must not trigger a
    # second provider call.
    transport = StaticDebarmentTransport(
        responses={
            "27AAACI1234F1Z5": _env(
                status_code=200, raw=_clear_payload()
            )
        }
    )
    adapter = DebarmentAdapter(transport=transport)
    rule = DebarmentEligibilityRule()
    rule.evaluate(
        [_evidence()], adapter, _requirement(evaluation_date=date(2025, 6, 15))
    )
    assert len(transport.queries) == 1


def test_compliance_engine_records_distinct_verification_ids() -> None:
    # The engine re-queries the provider for each requirement,
    # producing distinct verification IDs even when the bidder
    # and identifier are the same.
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=_clear_payload()
                )
            }
        )
    )
    engine = ComplianceEngine(
        rules={RULE_ID: DebarmentEligibilityRule()},
        providers={DEBARMENT_CAPABILITY: adapter},
    )
    result = engine.run(
        evidence=[_evidence()],
        requirements=[
            _requirement(evaluation_date=date(2025, 6, 15)),
            _requirement(
                evaluation_date=date(2025, 6, 15),
                requirement_id="req-debarment-002",
            ),
        ],
    )
    ids = {v.verification_id for v in result.verification_records}
    assert len(ids) == 2
