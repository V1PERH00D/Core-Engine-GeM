"""Test fixture builders for the bidder-risk tests.

These helpers construct real ComplianceResult, Verification,
IdentityFinding, VerificationFinding, SimilarityTrace, and
EvidenceQualityAssessment instances from the existing project
contracts.
"""

from __future__ import annotations

from compliance_engine.flags import FLAG_REGISTRY, get_flag_definition
from compliance_engine.models import (
    Capability,
    ComplianceResult,
    IdentityFinding,
)
from compliance_engine.models.result import ComplianceStatus
from compliance_engine.models.verification import (
    Verification,
    VerificationStatus,
)

from ai_verification.cross_bidder import (
    CorroborationSignals,
    QualitySignals,
    SimilarityLayer,
    SimilarityTrace,
    TemplateGate,
    TemplateGateStatus,
)
from ai_verification.evidence_quality import (
    QualityComponentScores,
    QualityState,
)
from ai_verification.evidence_quality.assessment import (
    EvidenceQualityAssessment,
)
from ai_verification.models.contracts import VerificationFinding

def make_compliance_result(
    *,
    requirement_id: str = "req-1",
    status: ComplianceStatus = ComplianceStatus.FAIL,
    capability: str = "GST / GSTN",
    flag_id: str | None = None,
    evidence_refs: list[str] | None = None,
    verification_refs: list[str] | None = None,
    rule_id: str = "rule-1",
    reason: str = "rule fired",
) -> ComplianceResult:
    """Build a ComplianceResult with deterministic defaults."""

    flags: list[str] = []
    if flag_id is not None:
        flags.append(flag_id)
    return ComplianceResult(
        requirement_id=requirement_id,
        capability=capability,
        status=status,
        reason=reason,
        evidence_refs=list(evidence_refs or []),
        verification_refs=list(verification_refs or []),
        flags=flags,
        rule_id=rule_id,
    )


def make_verification(
    *,
    verification_id: str,
    bidder_id: str = "bidder-1",
    capability: str = "GST / GSTN",
    source: str = "GSTN_MOCK",
    status: VerificationStatus = VerificationStatus.VERIFIED,
    data: dict | None = None,
) -> Verification:
    """Build a Verification record."""

    return Verification(
        verification_id=verification_id,
        bidder_id=bidder_id,
        capability=capability,
        source=source,
        status=status,
        data=data or {},
    )


def make_identity_finding(
    *,
    flag_id: str = "CROSS_SOURCE_IDENTITY_MISMATCH",
    capability: Capability = Capability.BIDDER_IDENTITY,
    left_document_id: str = "doc-gst-1",
    right_document_id: str = "doc-pan-1",
    evidence_refs: list[str] | None = None,
    message: str = "Names differ",
) -> IdentityFinding:
    """Build an IdentityFinding."""

    return IdentityFinding(
        flag_id=flag_id,
        capability=capability,
        message=message,
        evidence_refs=list(evidence_refs or ["ev-gst-1", "ev-pan-1"]),
        compared_values=["ACME LIMITED", "ACME TRADING LIMITED"],
        normalized_values=["acme limited", "acme trading limited"],
        left_document_id=left_document_id,
        right_document_id=right_document_id,
    )


def make_verification_finding(
    *,
    finding_id: str,
    bidder_id: str = "bidder-1",
    flag_id: str = "CROSS_BIDDER_DOCUMENT_REUSED",
    confidence: float = 0.95,
    explanation: str = "Documents are byte-identical",
    evidence_refs: list[str] | None = None,
    verification_refs: list[str] | None = None,
    related_bidder_ids: list[str] | None = None,
) -> VerificationFinding:
    """Build a VerificationFinding."""

    definition = get_flag_definition(flag_id)
    return VerificationFinding(
        finding_id=finding_id,
        bidder_id=bidder_id,
        flag_id=flag_id,
        severity=definition.severity,
        confidence=confidence,
        explanation=explanation,
        evidence_refs=list(evidence_refs or ["ev-1", "ev-2"]),
        verification_refs=list(verification_refs or []),
        related_bidder_ids=list(related_bidder_ids or ["bidder-2"]),
    )


def make_trace(
    *,
    left_document_id: str = "doc-1",
    right_document_id: str = "doc-2",
    left_bidder_id: str = "bidder-1",
    right_bidder_id: str = "bidder-2",
    layer: SimilarityLayer = SimilarityLayer.EXACT,
    confidence: float = 0.95,
) -> SimilarityTrace:
    """Build a SimilarityTrace."""

    return SimilarityTrace(
        layer=layer,
        left_document_id=left_document_id,
        right_document_id=right_document_id,
        left_bidder_id=left_bidder_id,
        right_bidder_id=right_bidder_id,
        doc_type="OEM_AUTH",
        left_file_hash="hash-left",
        right_file_hash="hash-right",
        left_norm_text_hash="norm-left",
        right_norm_text_hash="norm-right",
        normalization_version="v1",
        similarity_score=1.0,
        threshold=0.80,
        corroboration=CorroborationSignals(
            same_issuer=True,
            same_authorization_number=True,
            same_issue_date=True,
            validity_overlap=True,
        ),
        quality=QualitySignals(
            ocr_confidence=0.95,
            field_confidence=0.95,
            quality_score=0.95,
        ),
        template_gate=TemplateGate(
            status=TemplateGateStatus.MATCH,
            score=1.0,
            matched_fields=["authorization_number"],
        ),
        confidence=confidence,
    )


def make_quality_assessment(
    *,
    state: QualityState = QualityState.GOOD,
    quality_score: float = 1.0,
) -> EvidenceQualityAssessment:
    """Build an EvidenceQualityAssessment."""

    return EvidenceQualityAssessment(
        state=state,
        quality_score=quality_score,
        components=QualityComponentScores(
            ocr_quality=quality_score,
            field_quality=quality_score,
            completeness=quality_score,
            metadata_reliability=quality_score,
        ),
    )


def get_flag_id_with_severity(severity_name: str) -> str:
    """Return the first flag_id in the registry with the given severity."""

    target = severity_name.upper()
    for flag_id, definition in FLAG_REGISTRY.items():
        if definition.severity.value == target:
            return flag_id
    raise AssertionError(f"No flag with severity {severity_name}")
