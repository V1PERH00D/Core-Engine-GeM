"""Deterministic scoring engine for submitted procurement documents."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from compliance_engine.flags import FlagSeverity, get_flag_definition
from compliance_engine.models import (
    ComplianceResult,
    Evidence,
    IdentityFinding,
    Requirement,
)
from compliance_engine.models.result import ComplianceStatus
from compliance_engine.models.verification import Verification, VerificationStatus

from ai_verification.evidence_quality import EvidenceQualityAssessment, QualityState
from ai_verification.models.contracts import VerificationFinding

from .models import (
    BidderDocumentScore,
    DocumentInput,
    DocumentPriority,
    DocumentScoreDetail,
    DocumentScoreReason,
    TrafficLight,
)
from .policy import DEFAULT_POLICY, DocumentScoringPolicy

_COMPLIANCE_DEDUCTIONS: dict[ComplianceStatus, float] = {
    ComplianceStatus.FAIL: 60.0,
    ComplianceStatus.MISSING: 45.0,
    ComplianceStatus.UNVERIFIABLE: 30.0,
    ComplianceStatus.WARNING: 20.0,
    ComplianceStatus.NOT_CHECKED: 20.0,
}
_VERIFICATION_DEDUCTIONS: dict[VerificationStatus, float] = {
    VerificationStatus.INVALID: 45.0,
    VerificationStatus.INACTIVE: 45.0,
    VerificationStatus.NOT_FOUND: 40.0,
    VerificationStatus.UNAVAILABLE: 30.0,
    VerificationStatus.ERROR: 30.0,
}
_QUALITY_DEDUCTIONS: dict[QualityState, float] = {
    QualityState.DEGRADED: 15.0,
    QualityState.UNKNOWN: 25.0,
}
_MATERIAL_SEVERITIES = frozenset({FlagSeverity.CRITICAL, FlagSeverity.HIGH})


class DocumentScoringEngine:
    """Score document information without changing compliance decisions."""

    def __init__(self, policy: DocumentScoringPolicy | None = None) -> None:
        self._policy = policy or DEFAULT_POLICY

    def score(
        self,
        bidder_id: str,
        *,
        submission_id: str | None = None,
        documents: Sequence[DocumentInput],
        requirements: Sequence[Requirement] = (),
        evidence: Sequence[Evidence] = (),
        compliance_results: Sequence[ComplianceResult] = (),
        verification_records: Sequence[Verification] = (),
        findings: Sequence[VerificationFinding] = (),
        identity_findings: Sequence[IdentityFinding] = (),
        quality_by_document_id: Mapping[str, EvidenceQualityAssessment] | None = None,
    ) -> BidderDocumentScore:
        """Return a weighted document score and RED/YELLOW/GREEN category."""
        document_inputs = list(documents)
        expected_types = self._expected_types(requirements, compliance_results)
        if not document_inputs and not expected_types:
            return self._empty_result(bidder_id, submission_id)

        evidence_by_document = self._index_evidence(evidence)
        details: list[DocumentScoreDetail] = []
        present_types: set[str] = set()
        for document in document_inputs:
            canonical = self._canonical_type(document.document_type)
            present_types.add(canonical)
            details.append(
                self._score_document(
                    document=document,
                    canonical_type=canonical,
                    evidence=evidence_by_document.get(document.document_id, ()),
                    compliance_results=compliance_results,
                    verification_records=verification_records,
                    findings=findings,
                    identity_findings=identity_findings,
                    quality=(quality_by_document_id or {}).get(document.document_id),
                )
            )

        for missing_type in sorted(expected_types - present_types):
            details.append(self._score_missing(missing_type))

        final_score = self._weighted_score(details)
        category = self._categorize(final_score, details)
        reason_codes = tuple(
            sorted({reason for detail in details for reason in detail.reasons})
        )
        return BidderDocumentScore(
            bidder_id=bidder_id,
            submission_id=submission_id,
            score=round(final_score, 2),
            category=category,
            documents=tuple(details),
            reason_codes=reason_codes,
            summary=self._summary(bidder_id, final_score, category, details),
        )

    def _canonical_type(self, document_type: str) -> str:
        canonical = self._policy.normalize_document_type(document_type)
        return canonical if canonical in self._policy.document_importance else "UNKNOWN"

    def _expected_types(
        self,
        requirements: Sequence[Requirement],
        results: Sequence[ComplianceResult],
    ) -> set[str]:
        expected: set[str] = set()
        for requirement in requirements:
            if str(requirement.applicability).upper() == "NOT_APPLICABLE":
                continue
            expected.update(self._policy.expected_documents_for(requirement.capability))
        for result in results:
            if result.status is ComplianceStatus.NOT_APPLICABLE:
                continue
            expected.update(self._policy.expected_documents_for(result.capability))
        return {self._canonical_type(item) for item in expected}

    def _index_evidence(
        self, evidence: Sequence[Evidence]
    ) -> dict[str, tuple[Evidence, ...]]:
        grouped: dict[str, list[Evidence]] = defaultdict(list)
        for item in evidence:
            grouped[item.document_id].append(item)
        return {key: tuple(value) for key, value in grouped.items()}

    def _results_for_type(
        self, canonical_type: str, results: Sequence[ComplianceResult]
    ) -> tuple[ComplianceResult, ...]:
        return tuple(
            result
            for result in results
            if canonical_type
            in self._policy.expected_documents_for(result.capability)
        )

    def _verifications_for_type(
        self, canonical_type: str, records: Sequence[Verification]
    ) -> tuple[Verification, ...]:
        return tuple(
            record
            for record in records
            if canonical_type
            in self._policy.expected_documents_for(record.capability)
        )

    def _flags_for_type(
        self,
        document_id: str,
        evidence: Sequence[Evidence],
        findings: Sequence[VerificationFinding],
        identity_findings: Sequence[IdentityFinding],
    ) -> tuple[str, ...]:
        evidence_ids = {item.evidence_id for item in evidence}
        flags: set[str] = set()
        for finding in findings:
            trace = finding.trace
            trace_matches_document = bool(
                trace is not None
                and document_id in {
                    trace.left_document_id,
                    trace.right_document_id,
                }
            )
            if evidence_ids.intersection(finding.evidence_refs) or trace_matches_document:
                flags.add(finding.flag_id)
        for finding in identity_findings:
            if evidence_ids.intersection(finding.evidence_refs):
                flags.add(finding.flag_id)
        return tuple(sorted(flags))


    def _score_document(
        self,
        *,
        document: DocumentInput,
        canonical_type: str,
        evidence: tuple[Evidence, ...],
        compliance_results: Sequence[ComplianceResult],
        verification_records: Sequence[Verification],
        findings: Sequence[VerificationFinding],
        identity_findings: Sequence[IdentityFinding],
        quality: EvidenceQualityAssessment | None,
    ) -> DocumentScoreDetail:
        importance = self._policy.importance_for(canonical_type)
        reasons: set[DocumentScoreReason] = set()
        score = 100.0
        if not evidence:
            score -= 35.0
            reasons.add(DocumentScoreReason.NO_EVIDENCE)
        if canonical_type == "UNKNOWN":
            reasons.add(DocumentScoreReason.UNKNOWN_DOCUMENT_TYPE)

        confidences = [item.confidence for item in evidence if item.confidence is not None]
        average_confidence = (
            round(sum(confidences) / len(confidences), 4) if confidences else None
        )
        if (
            average_confidence is not None
            and average_confidence < self._policy.minimum_evidence_confidence
        ):
            score -= 15.0
            reasons.add(DocumentScoreReason.LOW_EVIDENCE_CONFIDENCE)

        results = self._results_for_type(canonical_type, compliance_results)
        statuses = tuple(sorted({result.status.value for result in results}))
        for result in results:
            score -= _COMPLIANCE_DEDUCTIONS.get(result.status, 0.0)
            if result.status is ComplianceStatus.FAIL:
                reasons.add(DocumentScoreReason.COMPLIANCE_FAILED)
            elif result.status is ComplianceStatus.MISSING:
                reasons.add(DocumentScoreReason.COMPLIANCE_MISSING)
            elif result.status is ComplianceStatus.UNVERIFIABLE:
                reasons.add(DocumentScoreReason.COMPLIANCE_UNVERIFIABLE)
            elif result.status is ComplianceStatus.WARNING:
                reasons.add(DocumentScoreReason.COMPLIANCE_WARNING)

        verifications = self._verifications_for_type(
            canonical_type, verification_records
        )
        verification_statuses = tuple(sorted({item.status.value for item in verifications}))
        for verification in verifications:
            score -= _VERIFICATION_DEDUCTIONS.get(verification.status, 0.0)
            if verification.status in {
                VerificationStatus.INVALID,
                VerificationStatus.INACTIVE,
                VerificationStatus.NOT_FOUND,
            }:
                reasons.add(DocumentScoreReason.VERIFICATION_FAILED)
            elif verification.status in {
                VerificationStatus.UNAVAILABLE,
                VerificationStatus.ERROR,
            }:
                reasons.add(DocumentScoreReason.VERIFICATION_UNAVAILABLE)

        flags = set(
            self._flags_for_type(
                document.document_id,
                evidence,
                findings,
                identity_findings,
            )
        )
        for result in results:
            flags.update(result.flags)
        for flag_id in sorted(flags):
            if get_flag_definition(flag_id).severity in _MATERIAL_SEVERITIES:
                score -= 25.0
                reasons.add(DocumentScoreReason.MATERIAL_FINDING)

        if quality is not None:
            score -= _QUALITY_DEDUCTIONS.get(quality.state, 0.0)
            if quality.state is QualityState.DEGRADED:
                reasons.add(DocumentScoreReason.EVIDENCE_QUALITY_DEGRADED)
            elif quality.state is QualityState.UNKNOWN:
                reasons.add(DocumentScoreReason.EVIDENCE_QUALITY_UNKNOWN)

        if score >= 80.0 and not reasons:
            reasons.add(DocumentScoreReason.NO_MATERIAL_ISSUES)
        if (
            verifications
            and all(item.status is VerificationStatus.VERIFIED for item in verifications)
            and not reasons
        ):
            reasons.add(DocumentScoreReason.VERIFIED)

        return DocumentScoreDetail(
            document_id=document.document_id,
            document_type=canonical_type,
            source_document_types=(document.document_type,),
            priority=importance.priority,
            weight=importance.weight,
            present=True,
            evidence_count=len(evidence),
            average_evidence_confidence=average_confidence,
            compliance_statuses=statuses,
            verification_statuses=verification_statuses,
            finding_flag_ids=tuple(sorted(flags)),
            reasons=tuple(sorted(reasons)),
            score=round(max(0.0, min(100.0, score)), 2),
        )

    def _score_missing(self, document_type: str) -> DocumentScoreDetail:
        importance = self._policy.importance_for(document_type)
        return DocumentScoreDetail(
            document_id=None,
            document_type=document_type,
            priority=importance.priority,
            weight=importance.weight,
            present=False,
            evidence_count=0,
            reasons=(
                DocumentScoreReason.DOCUMENT_MISSING,
                DocumentScoreReason.NO_EVIDENCE,
            ),
            score=0.0,
        )

    def _weighted_score(self, details: Sequence[DocumentScoreDetail]) -> float:
        denominator = sum(item.weight for item in details)
        if denominator <= 0:
            return 0.0
        return sum(item.score * item.weight for item in details) / denominator

    @staticmethod
    def _has_material_finding(detail: DocumentScoreDetail) -> bool:
        return DocumentScoreReason.MATERIAL_FINDING in detail.reasons

    def _categorize(
        self, score: float, details: Sequence[DocumentScoreDetail]
    ) -> TrafficLight:
        critical_missing = any(
            item.priority is DocumentPriority.CRITICAL
            and DocumentScoreReason.DOCUMENT_MISSING in item.reasons
            for item in details
        )
        high_priority_missing = any(
            item.priority is DocumentPriority.HIGH
            and DocumentScoreReason.DOCUMENT_MISSING in item.reasons
            for item in details
        )
        critical_failure = any(
            item.priority is DocumentPriority.CRITICAL
            and (
                DocumentScoreReason.COMPLIANCE_FAILED in item.reasons
                or DocumentScoreReason.COMPLIANCE_MISSING in item.reasons
                or DocumentScoreReason.VERIFICATION_FAILED in item.reasons
                or self._has_material_finding(item)
            )
            for item in details
        )
        high_priority_failure = any(
            item.priority is DocumentPriority.HIGH
            and (
                DocumentScoreReason.COMPLIANCE_FAILED in item.reasons
                or DocumentScoreReason.COMPLIANCE_MISSING in item.reasons
                or DocumentScoreReason.VERIFICATION_FAILED in item.reasons
                or self._has_material_finding(item)
            )
            for item in details
        )
        material_finding = any(
            self._has_material_finding(item) for item in details
        )
        unknown_document = any(
            item.document_type == "UNKNOWN" for item in details
        )
        if (
            score < self._policy.red_threshold
            or critical_missing
            or high_priority_missing
            or critical_failure
            or high_priority_failure
            or material_finding
        ):
            return TrafficLight.RED
        if score < self._policy.yellow_threshold or unknown_document:
            return TrafficLight.YELLOW
        return TrafficLight.GREEN

    def _empty_result(
        self, bidder_id: str, submission_id: str | None = None
    ) -> BidderDocumentScore:
        return BidderDocumentScore(
            bidder_id=bidder_id,
            submission_id=submission_id,
            score=0.0,
            category=TrafficLight.RED,
            reason_codes=(DocumentScoreReason.DOCUMENT_MISSING,),
            summary=(
                f"Bidder {bidder_id}: RED document score 0.00/100; "
                "no documents were scored."
            ),
        )

    @staticmethod
    def _summary(
        bidder_id: str,
        score: float,
        category: TrafficLight,
        details: Sequence[DocumentScoreDetail],
    ) -> str:
        blocking = sorted(
            item.document_type
            for item in details
            if DocumentScoreReason.DOCUMENT_MISSING in item.reasons
            or DocumentScoreReason.MATERIAL_FINDING in item.reasons
        )
        suffix = f"; priority issues: {', '.join(blocking)}" if blocking else ""
        return (
            f"Bidder {bidder_id}: {category.value} document score "
            f"{score:.2f}/100 across {len(details)} document type(s){suffix}."
        )


__all__ = ["DocumentScoringEngine"]


