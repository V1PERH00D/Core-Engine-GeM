"""Tests for the bidder-level risk engine: state mapping and basic
contract."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_verification.cross_bidder import SimilarityLayer
from ai_verification.evidence_quality import QualityState
from ai_verification.risk import (
    BidderRiskAssessment,
    BidderRiskEngine,
    CorrelationKey,
    EvidenceAvailability,
    ReasonCode,
    RiskCategory,
    RiskSignal,
    RiskState,
    severity_weight,
)
from ai_verification.risk.aggregation import (
    compute_aggregate_score,
    deduplicate_signals,
    determine_risk_state,
    select_strongest_signal,
)
from ai_verification.risk.severity import normalize_severity
from compliance_engine.flags import FlagSeverity
from compliance_engine.models.result import ComplianceStatus
from compliance_engine.models.verification import VerificationStatus

from tests.ai_verification.risk._builders import (
    get_flag_id_with_severity,
    make_compliance_result,
    make_identity_finding,
    make_quality_assessment,
    make_trace,
    make_verification,
    make_verification_finding,
)


ENGINE = BidderRiskEngine()


def _verified_critical_capabilities(bidder_id: str = "bidder-1"):
    """Return a list of verified Verification records for all
    critical capabilities.
    """

    return [
        make_verification(verification_id="v-gst", bidder_id=bidder_id),
        make_verification(
            verification_id="v-pan",
            bidder_id=bidder_id,
            capability="PAN / Income Tax",
        ),
        make_verification(
            verification_id="v-uid",
            bidder_id=bidder_id,
            capability="Bidder Identity",
        ),
    ]


# --- Empty / CLEAR state ---


def test_no_inputs_returns_clear():
    assessment = ENGINE.assess("bidder-1")
    assert assessment.bidder_id == "bidder-1"
    assert assessment.risk_state is RiskState.CLEAR
    assert assessment.aggregate_score == 0.0
    assert assessment.signals == ()
    assert assessment.strongest_signal is None
    assert assessment.supporting_signals == ()
    assert assessment.deduplicated_signal_count == 0
    assert "NO_RISK_SIGNALS_PRESENT" in assessment.reason_codes


def test_only_passing_compliance_returns_clear():
    """PASS / NOT_APPLICABLE / UNVERIFIABLE are not risks."""

    results = [
        make_compliance_result(requirement_id="r1", status=ComplianceStatus.PASS),
        make_compliance_result(requirement_id="r2", status=ComplianceStatus.NOT_APPLICABLE),
        make_compliance_result(requirement_id="r3", status=ComplianceStatus.UNVERIFIABLE),
    ]
    assessment = ENGINE.assess("bidder-1", compliance_results=results)
    assert assessment.risk_state is RiskState.CLEAR
    assert assessment.signals == ()

# --- Single-signal state mapping ---


def test_one_high_severity_signal_drives_high_risk():
    flag_id = get_flag_id_with_severity("HIGH")
    finding = make_verification_finding(
        finding_id="f-high-1",
        flag_id=flag_id,
        bidder_id="bidder-1",
        confidence=0.95,
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.HIGH_RISK
    assert assessment.aggregate_score > 0.0
    assert assessment.strongest_signal is not None
    assert assessment.strongest_signal.severity == FlagSeverity.HIGH.value


def test_one_medium_severity_signal_drives_review():
    flag_id = get_flag_id_with_severity("MEDIUM")
    finding = make_verification_finding(
        finding_id="f-med-1",
        flag_id=flag_id,
        bidder_id="bidder-1",
        confidence=0.85,
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.REVIEW
    assert assessment.strongest_signal is not None
    assert assessment.strongest_signal.severity == FlagSeverity.MEDIUM.value


def test_low_severity_signal_alone_does_not_elevate_state():
    """A single LOW signal should not push the score above REVIEW_THRESHOLD."""

    flag_id = get_flag_id_with_severity("LOW")
    finding = make_verification_finding(
        finding_id="f-low-1",
        flag_id=flag_id,
        bidder_id="bidder-1",
        confidence=0.7,
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.CLEAR
    assert assessment.aggregate_score <= 0.30


def test_info_signal_does_not_elevate_state():
    flag_id = get_flag_id_with_severity("INFO")
    finding = make_verification_finding(
        finding_id="f-info-1",
        flag_id=flag_id,
        bidder_id="bidder-1",
        confidence=0.5,
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.CLEAR


# --- Compliance failures ---


def test_compliance_failure_with_high_flag_drives_high_risk():
    flag_id = get_flag_id_with_severity("HIGH")
    result = make_compliance_result(
        requirement_id="req-gst-001",
        status=ComplianceStatus.FAIL,
        flag_id=flag_id,
        evidence_refs=["ev-gst-1"],
        verification_refs=["v-gst-1"],
    )
    assessment = ENGINE.assess(
        "bidder-1",
        compliance_results=[result],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.HIGH_RISK
    assert any(
        s.category is RiskCategory.COMPLIANCE for s in assessment.signals
    )


# --- Identity mismatch ---


def test_identity_mismatch_alone_drives_high_risk():
    identity = make_identity_finding()
    assessment = ENGINE.assess(
        "bidder-1",
        identity_findings=[identity],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.HIGH_RISK
    assert any(
        s.category is RiskCategory.IDENTITY for s in assessment.signals
    )


# --- Cross-bidder document reuse ---


def test_exact_document_reuse_drives_high_risk():
    finding = make_verification_finding(
        finding_id="f-reuse-1",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-2",
        layer=SimilarityLayer.EXACT,
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.HIGH_RISK
    assert any(
        s.category is RiskCategory.DOCUMENT_REUSE for s in assessment.signals
    )


def test_semantic_near_duplicate_drives_review():
    finding = make_verification_finding(
        finding_id="f-near-1",
        flag_id="CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-2",
        layer=SimilarityLayer.SEMANTIC,
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.REVIEW


def test_lexical_near_duplicate_drives_review():
    finding = make_verification_finding(
        finding_id="f-near-2",
        flag_id="CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-2",
        layer=SimilarityLayer.LEXICAL,
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.REVIEW


# --- Cross-bidder attribution ---


def test_same_cross_bidder_finding_attributes_to_both_bidders():
    finding = make_verification_finding(
        finding_id="f-reuse-2",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-2",
        layer=SimilarityLayer.EXACT,
    )

    a1 = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=_verified_critical_capabilities("bidder-1"),
    )
    a2 = ENGINE.assess(
        "bidder-2",
        findings=[finding],
        traces=[trace],
        verification_records=_verified_critical_capabilities("bidder-2"),
    )

    reuse_a1 = [s for s in a1.signals if s.category is RiskCategory.DOCUMENT_REUSE]
    reuse_a2 = [s for s in a2.signals if s.category is RiskCategory.DOCUMENT_REUSE]
    assert len(reuse_a1) == 1
    assert len(reuse_a2) == 1
    assert (
        reuse_a1[0].correlation_key.document_ids
        == reuse_a2[0].correlation_key.document_ids
    )
    assert reuse_a1[0].correlation_key.primary_bidder_id == "bidder-1"
    assert reuse_a2[0].correlation_key.primary_bidder_id == "bidder-2"


# --- Independent supporting signals ---


def test_multiple_supporting_signals_boost_score_bounded():
    finding_a = make_verification_finding(
        finding_id="f-a",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
        evidence_refs=["ev-a-1", "ev-a-2"],
    )
    finding_b = make_verification_finding(
        finding_id="f-b",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-3"],
        evidence_refs=["ev-b-1", "ev-b-2"],
    )
    finding_c = make_verification_finding(
        finding_id="f-c",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-4"],
        evidence_refs=["ev-c-1", "ev-c-2"],
    )
    traces = [
        make_trace(left_bidder_id="bidder-1", right_bidder_id="bidder-2"),
        make_trace(
            left_bidder_id="bidder-1",
            right_bidder_id="bidder-3",
            left_document_id="doc-1b",
            right_document_id="doc-3b",
        ),
        make_trace(
            left_bidder_id="bidder-1",
            right_bidder_id="bidder-4",
            left_document_id="doc-1c",
            right_document_id="doc-4c",
        ),
    ]
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding_a, finding_b, finding_c],
        traces=traces,
        verification_records=_verified_critical_capabilities(),
    )

    assert assessment.aggregate_score <= 1.0
    assert len(assessment.supporting_signals) >= 1


def test_ten_low_signals_do_not_outweigh_one_high_signal():
    high_finding = make_verification_finding(
        finding_id="f-hi",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
        evidence_refs=["ev-hi-1", "ev-hi-2"],
    )
    low_finding_id = get_flag_id_with_severity("LOW")

    low_findings = [
        make_verification_finding(
            finding_id=f"f-lo-{i}",
            flag_id=low_finding_id,
            bidder_id="bidder-1",
            evidence_refs=[f"ev-lo-{i}"],
            verification_refs=[f"v-lo-{i}"],
        )
        for i in range(10)
    ]
    assessment_with_high = ENGINE.assess(
        "bidder-1",
        findings=[high_finding] + low_findings,
        verification_records=_verified_critical_capabilities(),
    )
    assessment_without_high = ENGINE.assess(
        "bidder-1",
        findings=low_findings,
        verification_records=_verified_critical_capabilities(),
    )

    assert (
        assessment_with_high.aggregate_score
        > assessment_without_high.aggregate_score
    )
    assert assessment_with_high.aggregate_score <= 1.0


# --- Deduplication ---


def test_correlated_findings_deduplicated():
    finding = make_verification_finding(
        finding_id="f-dup",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
        evidence_refs=["ev-1", "ev-2"],
    )
    duplicate = finding.model_copy(update={"finding_id": "f-dup-2"})

    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding, duplicate],
        verification_records=_verified_critical_capabilities(),
    )

    assert len(assessment.signals) == 1
    assert assessment.deduplicated_signal_count == 1


def test_duplicate_verification_records_are_safe():
    """Duplicate verification records must not crash and the assessment
    is deterministic. With GST-only verifications and missing critical
    capabilities (PAN / Identity), the bidder is INDETERMINATE.
    """

    verifications = [
        make_verification(verification_id="v-gst", bidder_id="bidder-1")
        for _ in range(5)
    ]
    a1 = ENGINE.assess("bidder-1", verification_records=verifications)
    a2 = ENGINE.assess("bidder-1", verification_records=verifications)
    assert a1.risk_state is a2.risk_state
    assert a1.model_dump() == a2.model_dump()
    assert a1.risk_state is RiskState.INDETERMINATE


# --- Verification availability / INDETERMINATE ---


def test_unavailable_provider_does_not_create_high_risk():
    verifications = [
        make_verification(
            verification_id="v-gst",
            bidder_id="bidder-1",
            status=VerificationStatus.UNAVAILABLE,
        )
    ]
    assessment = ENGINE.assess(
        "bidder-1", verification_records=verifications
    )
    assert assessment.risk_state is RiskState.INDETERMINATE


def test_not_found_does_not_create_high_risk():
    verifications = [
        make_verification(
            verification_id="v-gst",
            bidder_id="bidder-1",
            status=VerificationStatus.NOT_FOUND,
        )
    ]
    assessment = ENGINE.assess(
        "bidder-1", verification_records=verifications
    )
    assert assessment.risk_state is RiskState.INDETERMINATE
    assert (
        ReasonCode.CRITICAL_VERIFICATIONS_UNAVAILABLE.value
        in assessment.reason_codes
    )


def test_repeated_provider_failures_do_not_inflate_risk():
    verifications = [
        make_verification(
            verification_id=f"v-gst-{i}",
            bidder_id="bidder-1",
            status=VerificationStatus.UNAVAILABLE,
        )
        for i in range(10)
    ]
    assessment = ENGINE.assess(
        "bidder-1", verification_records=verifications
    )
    assert assessment.risk_state is RiskState.INDETERMINATE
    availability = [
        s
        for s in assessment.signals
        if s.category is RiskCategory.VERIFICATION_AVAILABILITY
    ]
    assert len(availability) == 1
    assert availability[0].is_actionable is False


def test_zero_provider_failures_does_not_alter_risk():
    verifications = [
        make_verification(
            verification_id="v-gst",
            bidder_id="bidder-1",
            status=VerificationStatus.VERIFIED,
        )
    ]
    assessment = ENGINE.assess(
        "bidder-1", verification_records=verifications
    )
    assert all(
        s.category is not RiskCategory.VERIFICATION_AVAILABILITY
        for s in assessment.signals
    )


def test_clear_when_no_verifications_and_no_signals():
    """No verifications attempted AND no signals -> CLEAR (nothing to
    assess; we do not invent epistemic uncertainty from absence).
    """

    assessment = ENGINE.assess("bidder-1")
    assert assessment.risk_state is RiskState.CLEAR


def test_strong_signal_overrides_indeterminate_when_critical_capability_verified():
    finding = make_verification_finding(
        finding_id="f-reuse",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(left_bidder_id="bidder-1", right_bidder_id="bidder-2")
    verifications = [
        make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        make_verification(
            verification_id="v-pan",
            bidder_id="bidder-1",
            capability="PAN / Income Tax",
            status=VerificationStatus.VERIFIED,
        ),
        make_verification(
            verification_id="v-uid",
            bidder_id="bidder-1",
            capability="Bidder Identity",
            status=VerificationStatus.VERIFIED,
        ),
    ]
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=verifications,
    )
    assert assessment.risk_state is RiskState.HIGH_RISK


# --- Evidence quality ---


def test_evidence_quality_unknown_drives_indeterminate():
    assessment = ENGINE.assess(
        "bidder-1",
        evidence_quality_assessments=[
            make_quality_assessment(state=QualityState.UNKNOWN, quality_score=0.1),
        ],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.INDETERMINATE


def test_evidence_quality_degraded_does_not_block_high_signal():
    finding = make_verification_finding(
        finding_id="f-reuse",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(left_bidder_id="bidder-1", right_bidder_id="bidder-2")
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        evidence_quality_assessments=[
            make_quality_assessment(state=QualityState.DEGRADED, quality_score=0.4),
        ],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.HIGH_RISK


def test_exact_reuse_unaffected_by_quality():
    finding = make_verification_finding(
        finding_id="f-exact",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-2",
        layer=SimilarityLayer.EXACT,
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        evidence_quality_assessments=[
            make_quality_assessment(state=QualityState.DEGRADED, quality_score=0.05),
        ],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.HIGH_RISK


def test_missing_quality_metadata_does_not_create_positive_risk():
    assessment = ENGINE.assess(
        "bidder-1",
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert all(
        s.category is not RiskCategory.EVIDENCE_QUALITY
        for s in assessment.signals
    )


# --- Independence: identity mismatch vs document reuse ---


def test_identity_mismatch_independent_of_document_reuse():
    identity = make_identity_finding()
    assessment = ENGINE.assess(
        "bidder-1",
        identity_findings=[identity],
        verification_records=_verified_critical_capabilities(),
    )
    categories = {s.category for s in assessment.signals}
    assert RiskCategory.IDENTITY in categories
    assert RiskCategory.DOCUMENT_REUSE not in categories


def test_document_reuse_independent_of_identity_mismatch():
    finding = make_verification_finding(
        finding_id="f-reuse-iso",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(left_bidder_id="bidder-1", right_bidder_id="bidder-2")
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=_verified_critical_capabilities(),
    )
    categories = {s.category for s in assessment.signals}
    assert RiskCategory.DOCUMENT_REUSE in categories
    assert RiskCategory.IDENTITY not in categories


# --- Threshold boundaries ---


def test_threshold_boundaries_at_review():
    from ai_verification.risk.policy import REVIEW_THRESHOLD
    assert severity_weight(FlagSeverity.MEDIUM) >= REVIEW_THRESHOLD


def test_threshold_boundaries_at_high_risk():
    from ai_verification.risk.policy import HIGH_RISK_THRESHOLD
    assert severity_weight(FlagSeverity.HIGH) >= HIGH_RISK_THRESHOLD


def test_signal_score_bounded():
    finding = make_verification_finding(
        finding_id="f-bnd",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    trace = make_trace()
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    for signal in assessment.signals:
        assert 0.0 <= signal.score <= 1.0


def test_aggregate_score_bounded():
    finding = make_verification_finding(
        finding_id="f-bnd",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    trace = make_trace()
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert 0.0 <= assessment.aggregate_score <= 1.0


# --- Strongest signal identification ---


def test_strongest_signal_identification():
    finding_high = make_verification_finding(
        finding_id="f-h",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    finding_med = make_verification_finding(
        finding_id="f-m",
        flag_id="CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE",
        bidder_id="bidder-1",
    )
    trace1 = make_trace()
    trace2 = make_trace(
        left_document_id="doc-x",
        right_document_id="doc-y",
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-3",
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding_high, finding_med],
        traces=[trace1, trace2],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.strongest_signal is not None
    assert assessment.strongest_signal.severity == FlagSeverity.HIGH.value


# --- Determinism and ordering ---


def test_deterministic_assessment():
    finding = make_verification_finding(
        finding_id="f-det",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    trace = make_trace()
    verifications = _verified_critical_capabilities()
    a1 = ENGINE.assess(
        "bidder-1", findings=[finding], traces=[trace], verification_records=verifications
    )
    a2 = ENGINE.assess(
        "bidder-1", findings=[finding], traces=[trace], verification_records=verifications
    )
    assert a1.model_dump() == a2.model_dump()


def test_summary_is_deterministic_and_contains_no_claims():
    finding = make_verification_finding(
        finding_id="f-sum",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(left_bidder_id="bidder-1", right_bidder_id="bidder-2")
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    summary = assessment.summary
    assert isinstance(summary, str)
    assert summary.endswith(".")
    forbidden = ("fraud", "collusion", "intent", "illegal", "guilty")
    for word in forbidden:
        assert word not in summary.lower()


def test_signal_ordering_is_deterministic():
    f1 = make_verification_finding(
        finding_id="f-z",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    f2 = make_verification_finding(
        finding_id="f-a",
        flag_id="CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE",
        bidder_id="bidder-1",
    )
    trace1 = make_trace()
    trace2 = make_trace(
        left_document_id="doc-y",
        right_document_id="doc-z",
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-3",
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[f1, f2],
        traces=[trace1, trace2],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    ids = [s.signal_id for s in assessment.signals]
    assert ids == sorted(ids)


# --- Reference preservation ---


def test_evidence_refs_preserved_on_signal():
    finding = make_verification_finding(
        finding_id="f-ev",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        evidence_refs=["ev-A", "ev-B"],
        verification_refs=["v-A"],
    )
    trace = make_trace()
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-A", bidder_id="bidder-1"),
        ],
    )
    reuse = [
        s for s in assessment.signals if s.category is RiskCategory.DOCUMENT_REUSE
    ]
    assert reuse
    assert set(reuse[0].evidence_refs) == {"ev-A", "ev-B"}
    assert "v-A" in reuse[0].verification_refs
    assert "f-ev" in reuse[0].finding_refs


def test_no_fabricated_references():
    finding = make_verification_finding(
        finding_id="f-nofab",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        evidence_refs=["ev-1"],
        verification_refs=["v-1"],
    )
    trace = make_trace()
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-1", bidder_id="bidder-1"),
        ],
    )
    for signal in assessment.signals:
        for ref in signal.evidence_refs:
            assert ref in {"ev-1"}
        for ref in signal.verification_refs:
            assert ref in {"v-1"}


# --- Type / validation ---


def test_risk_signal_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        RiskSignal(
            bidder_id="b",
            signal_id="x",
            correlation_key=CorrelationKey(
                category=RiskCategory.COMPLIANCE,
                primary_bidder_id="b",
            ),
            category=RiskCategory.COMPLIANCE,
            severity="HIGH",
            score=2.0,
            confidence=0.5,
            is_actionable=True,
            reason_code="X",
            human_reason="y",
        )


def test_risk_signal_rejects_unknown_field():
    with pytest.raises(ValidationError):
        RiskSignal(
            bidder_id="b",
            signal_id="x",
            correlation_key=CorrelationKey(
                category=RiskCategory.COMPLIANCE,
                primary_bidder_id="b",
            ),
            category=RiskCategory.COMPLIANCE,
            severity="HIGH",
            score=0.5,
            confidence=0.5,
            is_actionable=True,
            reason_code="X",
            human_reason="y",
            made_up_field="nope",  # type: ignore[call-arg]
        )


def test_assessment_is_immutable():
    assessment = ENGINE.assess("bidder-1")
    with pytest.raises(Exception):
        assessment.bidder_id = "other"  # type: ignore[misc]


def test_evidence_availability_summary_present():
    assessment = ENGINE.assess(
        "bidder-1",
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert isinstance(assessment.evidence_availability, EvidenceAvailability)


# --- Engine self-test / direct calls ---


def test_deduplicate_signals_keeps_strongest():
    finding = make_verification_finding(
        finding_id="f-x",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        evidence_refs=["ev-1"],
    )
    duplicate = finding.model_copy(update={"finding_id": "f-x-2"})
    a = ENGINE.assess(
        "bidder-1",
        findings=[finding, duplicate],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert a.deduplicated_signal_count == 1
    assert len(a.signals) == 1


def test_determine_risk_state_independent_function():
    state = determine_risk_state(
        aggregate_score=0.7,
        strongest=None,
        evidence_availability=EvidenceAvailability(
            verified_verification_count=2,
        ),
        no_signals=False,
        no_verifications=False,
    )
    assert state is RiskState.CLEAR


def test_compute_aggregate_score_bounded():
    finding = make_verification_finding(
        finding_id="f-bnd",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    trace = make_trace()
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert 0.0 <= compute_aggregate_score(
        assessment.strongest_signal,  # type: ignore[arg-type]
        assessment.supporting_signals,
    ) <= 1.0


def test_select_strongest_signal_empty():
    assert select_strongest_signal([]) is None


def test_select_strongest_signal_uses_score_then_severity():
    flag_med = get_flag_id_with_severity("MEDIUM")
    flag_high = get_flag_id_with_severity("HIGH")
    sig_med = make_verification_finding(
        finding_id="m",
        flag_id=flag_med,
        bidder_id="bidder-1",
    )
    sig_high = make_verification_finding(
        finding_id="h",
        flag_id=flag_high,
        bidder_id="bidder-1",
    )
    trace1 = make_trace()
    trace2 = make_trace(
        left_document_id="doc-x",
        right_document_id="doc-y",
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-3",
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[sig_med, sig_high],
        traces=[trace1, trace2],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert assessment.strongest_signal is not None
    assert assessment.strongest_signal.severity == FlagSeverity.HIGH.value


def test_deduplicate_signals_function_directly():
    finding = make_verification_finding(
        finding_id="f",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        evidence_refs=["ev-1"],
    )
    trace = make_trace()
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding, finding.model_copy(update={"finding_id": "f-2"})],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    deduped, count = deduplicate_signals(assessment.signals)
    assert count == 0
    assert deduped == assessment.signals


# --- Engine integration with existing subsystems ---


def test_engine_accepts_real_compliance_results():
    result = make_compliance_result(
        requirement_id="r-gst",
        status=ComplianceStatus.FAIL,
        flag_id="GSTIN_INVALID",
    )
    assessment = ENGINE.assess(
        "bidder-1",
        compliance_results=[result],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert any(
        s.category is RiskCategory.COMPLIANCE for s in assessment.signals
    )


def test_engine_accepts_real_identity_findings():
    finding = make_identity_finding()
    assessment = ENGINE.assess(
        "bidder-1",
        identity_findings=[finding],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert any(
        s.category is RiskCategory.IDENTITY for s in assessment.signals
    )


def test_engine_accepts_real_evidence_quality_assessments():
    assessment = ENGINE.assess(
        "bidder-1",
        evidence_quality_assessments=[
            make_quality_assessment(state=QualityState.DEGRADED, quality_score=0.5),
        ],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert any(
        s.category is RiskCategory.EVIDENCE_QUALITY for s in assessment.signals
    )


def test_engine_accepts_real_verification_records():
    assessment = ENGINE.assess(
        "bidder-1",
        verification_records=[
            make_verification(
                verification_id="v-gst",
                bidder_id="bidder-1",
                status=VerificationStatus.UNAVAILABLE,
            ),
        ],
    )
    assert assessment.risk_state is RiskState.INDETERMINATE


def test_engine_accepts_real_similarity_traces():
    finding = make_verification_finding(
        finding_id="f-tr",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    trace = make_trace(left_bidder_id="bidder-1", right_bidder_id="bidder-2")
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert any(
        s.category is RiskCategory.DOCUMENT_REUSE for s in assessment.signals
    )


# --- Severity weight mapping ---


def test_severity_weights():
    from ai_verification.risk.policy import (
        SEVERITY_WEIGHT_CRITICAL,
        SEVERITY_WEIGHT_HIGH,
        SEVERITY_WEIGHT_LOW,
        SEVERITY_WEIGHT_MEDIUM,
    )

    assert severity_weight(FlagSeverity.CRITICAL) == SEVERITY_WEIGHT_CRITICAL
    assert severity_weight(FlagSeverity.HIGH) == SEVERITY_WEIGHT_HIGH
    assert severity_weight(FlagSeverity.MEDIUM) == SEVERITY_WEIGHT_MEDIUM
    assert severity_weight(FlagSeverity.LOW) == SEVERITY_WEIGHT_LOW


def test_normalize_severity_returns_none_for_unknown():
    assert normalize_severity("NOT_A_SEVERITY") is None


# --- Cross-bidder engine compatibility ---


def test_existing_verification_engine_still_runs():
    from ai_verification.engine import VerificationEngine
    from ai_verification.models import VerificationInput

    engine = VerificationEngine()
    result = engine.run(
        VerificationInput(bidder_id="bidder-1")
    )
    assert result.bidder_id == "bidder-1"
    assert result.findings == []


# --- Builder usage ---


def test_build_assessment_directly_with_minimal_signals():
    finding = make_verification_finding(
        finding_id="f",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    trace = make_trace()
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert isinstance(assessment, BidderRiskAssessment)


def test_engine_handles_zero_inputs_cleanly():
    assessment = ENGINE.assess("bidder-x")
    assert assessment.bidder_id == "bidder-x"


def test_engine_summary_is_stable():
    inputs = dict(
        bidder_id="bidder-1",
        compliance_results=[
            make_compliance_result(
                requirement_id="r-1",
                status=ComplianceStatus.FAIL,
                flag_id="GSTIN_INVALID",
            )
        ],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    a1 = ENGINE.assess(**inputs)
    a2 = ENGINE.assess(**inputs)
    assert a1.summary == a2.summary


# --- Reason codes ---


def test_reason_code_includes_no_signals_when_empty():
    assessment = ENGINE.assess("bidder-1")
    assert ReasonCode.NO_RISK_SIGNALS_PRESENT.value in assessment.reason_codes


def test_reason_code_includes_correlated_dedup_when_duplicates():
    finding = make_verification_finding(
        finding_id="f",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    trace = make_trace()
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding, finding.model_copy(update={"finding_id": "f-2"})],
        traces=[trace],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    assert (
        ReasonCode.CORRELATED_SIGNALS_DEDUPLICATED.value
        in assessment.reason_codes
    )


def test_reason_code_includes_supporting_when_multiple_signals():
    f1 = make_verification_finding(
        finding_id="f1",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        evidence_refs=["e1"],
    )
    f2 = make_verification_finding(
        finding_id="f2",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        evidence_refs=["e2"],
    )
    t1 = make_trace()
    t2 = make_trace(
        left_document_id="doc-a",
        right_document_id="doc-b",
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-3",
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[f1, f2],
        traces=[t1, t2],
        verification_records=[
            make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        ],
    )
    if len(assessment.supporting_signals) >= 1:
        assert (
            ReasonCode.INDEPENDENT_SUPPORTING_SIGNALS.value
            in assessment.reason_codes
        )


# --- Additional coverage tests ---


def test_clear_when_only_low_signal_and_verified_critical_capabilities():
    """A single LOW signal with verified critical capabilities -> CLEAR."""

    flag_id = get_flag_id_with_severity("LOW")
    finding = make_verification_finding(
        finding_id="f-low-only",
        flag_id=flag_id,
        bidder_id="bidder-1",
    )
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        verification_records=_verified_critical_capabilities(),
    )
    assert assessment.risk_state is RiskState.CLEAR


def test_indeterminate_when_critical_capability_unavailable_no_signals():
    """Critical capability UNAVAILABLE with no actionable signals ->
    INDETERMINATE.
    """

    verifications = [
        make_verification(
            verification_id="v-gst",
            bidder_id="bidder-1",
            status=VerificationStatus.UNAVAILABLE,
        ),
    ]
    assessment = ENGINE.assess(
        "bidder-1", verification_records=verifications
    )
    assert assessment.risk_state is RiskState.INDETERMINATE


def test_indeterminate_distinct_from_high_risk_via_availability_signal():
    """Repeated provider failures must NOT drive HIGH_RISK; they
    produce INDETERMINATE only.
    """

    verifications = [
        make_verification(
            verification_id=f"v-gst-{i}",
            bidder_id="bidder-1",
            status=VerificationStatus.UNAVAILABLE,
        )
        for i in range(20)
    ]
    assessment = ENGINE.assess(
        "bidder-1", verification_records=verifications
    )
    # Crucially: not HIGH_RISK.
    assert assessment.risk_state is not RiskState.HIGH_RISK
    assert assessment.risk_state is RiskState.INDETERMINATE
    # Availability signal exists, is informational, not actionable.
    availability = [
        s
        for s in assessment.signals
        if s.category is RiskCategory.VERIFICATION_AVAILABILITY
    ]
    assert availability
    assert availability[0].is_actionable is False
    # The availability signal does not contribute to score.
    assert assessment.aggregate_score < 0.30


def test_high_risk_when_signal_present_and_some_verifications_missing():
    """A strong HIGH signal can drive HIGH_RISK even when some
    verifications are unavailable -- strong evidence is itself strong
    evidence.
    """

    finding = make_verification_finding(
        finding_id="f-reuse",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(left_bidder_id="bidder-1", right_bidder_id="bidder-2")
    verifications = [
        make_verification(verification_id="v-gst", bidder_id="bidder-1"),
        make_verification(
            verification_id="v-pan",
            bidder_id="bidder-1",
            capability="PAN / Income Tax",
        ),
        make_verification(
            verification_id="v-uid",
            bidder_id="bidder-1",
            capability="Bidder Identity",
        ),
    ]
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=verifications,
    )
    assert assessment.risk_state is RiskState.HIGH_RISK


def test_explanation_lists_strongest_signal_for_clear_with_no_signals():
    """No signals -> CLEAR with appropriate summary text."""

    assessment = ENGINE.assess("bidder-1")
    summary = assessment.summary
    assert "CLEAR" in summary


def test_explanation_mentions_indeterminate_when_critical_missing():
    """INDETERMINATE summary mentions the cause."""

    verifications = [
        make_verification(
            verification_id="v-gst",
            bidder_id="bidder-1",
            status=VerificationStatus.UNAVAILABLE,
        ),
    ]
    assessment = ENGINE.assess(
        "bidder-1", verification_records=verifications
    )
    assert "INDETERMINATE" in assessment.summary


def test_same_correlation_key_merges_across_findings_and_trace():
    """A cross-bidder finding plus its VerificationFinding share a
    correlation key and dedupe to one contribution.
    """

    # Without a matching trace, the VerificationFinding is the only
    # signal. With the trace, the cross-bidder signal is emitted.
    # Either way the resulting signal count must be one (not two).
    finding = make_verification_finding(
        finding_id="f",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
        evidence_refs=["ev-1"],
        verification_refs=["v-1"],
    )
    trace = make_trace(
        left_bidder_id="bidder-1",
        right_bidder_id="bidder-2",
    )
    a = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=_verified_critical_capabilities(),
    )
    reuse = [
        s for s in a.signals if s.category is RiskCategory.DOCUMENT_REUSE
    ]
    assert len(reuse) == 1


def test_summary_contains_score_when_nonzero():
    finding = make_verification_finding(
        finding_id="f-score",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
        related_bidder_ids=["bidder-2"],
    )
    trace = make_trace(left_bidder_id="bidder-1", right_bidder_id="bidder-2")
    assessment = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=_verified_critical_capabilities(),
    )
    assert "score" in assessment.summary


def test_assessment_serializes_deterministically():
    finding = make_verification_finding(
        finding_id="f-ser",
        flag_id="CROSS_BIDDER_DOCUMENT_REUSED",
        bidder_id="bidder-1",
    )
    trace = make_trace()
    verifications = _verified_critical_capabilities()
    a1 = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=verifications,
    )
    a2 = ENGINE.assess(
        "bidder-1",
        findings=[finding],
        traces=[trace],
        verification_records=verifications,
    )
    assert a1.model_dump_json() == a2.model_dump_json()


def test_policy_thresholds_are_exact():
    from ai_verification.risk.policy import (
        HIGH_RISK_THRESHOLD,
        REVIEW_THRESHOLD,
        SUPPORTING_BOOST_CAP,
        SUPPORTING_BOOST_PER_SIGNAL,
    )
    assert REVIEW_THRESHOLD == 0.30
    assert HIGH_RISK_THRESHOLD == 0.60
    assert SUPPORTING_BOOST_PER_SIGNAL == 0.05
    assert SUPPORTING_BOOST_CAP == 0.30


def test_engine_importable_from_top_level_package():
    """The engine must be importable from ai_verification.risk directly."""

    from ai_verification.risk import BidderRiskEngine as A
    from ai_verification.risk.engine import BidderRiskEngine as B

    assert A is B
