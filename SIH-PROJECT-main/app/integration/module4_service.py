"""Module 4 orchestration service (with the REAL Module 3 wired in).

This service wires and runs the EXISTING Core-Engine-GeM engines:

    VerificationEngine(
        identity_reconciliation_engine=IdentityReconciliationEngine(),
        cross_document_consistency_engine=CrossDocumentConsistencyEngine(...),
    )

* The ``CrossDocumentConsistencyEngine`` runs on the *document-level*
  Evidence produced by the Module 1/2 adapter — this is the mandatory
  current-integration path.
* The ``IdentityReconciliationEngine`` receives the REAL authoritative
  ``Verification[]`` records produced by Module 3 (the Core compliance
  engine, see ``module3_service``). Module 4 never queries provider APIs
  itself and never fabricates a Verification record.
* Explanations are produced AFTER findings, by Core's
  ``ExplanationEngine``, grounded in the finding's real source evidence,
  the real Module 3 verification references and the structured pairwise
  comparison. The deterministic fallback generator is the default; an
  LLM may explain but can never create, remove or modify a flag.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional, Sequence

from compliance_engine.models import Evidence
from compliance_engine.models.result import ComplianceResult
from compliance_engine.models.verification import Verification

from ai_verification.cross_document import (
    ConsistencyDimension,
    CrossDocumentConsistencyEngine,
    CrossDocumentConsistencyResult,
    classify_field,
)
from ai_verification.explanations import (
    ExplanationEngine,
    ExplanationGrounding,
    ExplanationResult,
    FactKind,
    StructuredFact,
)
from ai_verification.identity import IdentityReconciliationEngine
from ai_verification.models.contracts import (
    VerificationFinding,
    VerificationInput,
)
from ai_verification import VerificationEngine

from .module12_adapter import build_bidder_evidence, build_document_inputs
from .module3_service import run_module3_for_bidder
from .scoring_service import score_bidder_documents

STATUS_VERIFIED = "VERIFIED"
STATUS_FAILED = "MODULE4_FAILED"
STATUS_NO_DOCUMENTS = "NO_DOCUMENTS"
#: Distinct failure kind: the REAL Module 3 (compliance engine) raised.
STATUS_MODULE3_FAILED = "MODULE3_FAILED"


class _Module3Failure(Exception):
    """Internal marker: the REAL Module 3 compliance engine raised.

    Lets the per-bidder loop record a MODULE3_FAILED state (with no
    fabricated findings/flags/scores) without masking the pipeline as a
    clean pass or as a generic Module 4 failure.
    """


class _ObservedCrossDocumentEngine:
    """Observation seam around the real CrossDocumentConsistencyEngine.

    Delegates 100% of behaviour to the wrapped Core engine and merely
    keeps the returned result so the explanation builder can read the
    exact structured pairwise comparisons (values, normalizations,
    outcomes) that produced each finding. No logic is re-implemented and
    nothing is mocked.
    """

    def __init__(self, inner: CrossDocumentConsistencyEngine) -> None:
        self._inner = inner
        self.last_result: Optional[CrossDocumentConsistencyResult] = None

    def run(self, *args: Any, **kwargs: Any) -> CrossDocumentConsistencyResult:
        self.last_result = self._inner.run(*args, **kwargs)
        return self.last_result


class _ObservedIdentityEngine:
    """Observation seam around the real IdentityReconciliationEngine.

    Delegates 100% of behaviour to the wrapped Core engine and merely
    keeps the returned result so the pipeline can hand Module 5 the REAL
    ``IdentityFinding[]`` objects the engine produced from the Module 3
    ``Verification[]`` records. No logic is re-implemented and nothing
    is mocked.
    """

    def __init__(self, inner: IdentityReconciliationEngine) -> None:
        self._inner = inner
        self.last_result: Any = None

    def reconcile(self, *args: Any, **kwargs: Any) -> Any:
        self.last_result = self._inner.reconcile(*args, **kwargs)
        return self.last_result


def _comparison_for(
    aggregation: Any, left_evidence_id: str, right_evidence_id: str
) -> Any:
    for comparison in aggregation.comparisons:
        if {comparison.left_evidence_id, comparison.right_evidence_id} == {
            left_evidence_id,
            right_evidence_id,
        }:
            return comparison
    return None


def _fact_kind_for(document_type: str, field_name: str) -> FactKind:
    spec = classify_field(document_type, field_name)
    if spec is not None and spec.dimension is ConsistencyDimension.IDENTIFIER:
        return FactKind.IDENTIFIER
    if spec is not None and spec.dimension is ConsistencyDimension.DATE:
        return FactKind.DATE
    return FactKind.ACTUAL_VALUE


def _facts_for_finding(
    finding: VerificationFinding,
    evidence_by_id: dict[str, Evidence],
    aggregation: Any,
) -> list[StructuredFact]:
    """Build the structured, source-grounded facts for one finding.

    Contains, for each side of the comparison: the source document, the
    field name and the real extracted value (with confidence only when
    upstream actually supplied one), plus the deterministic comparison
    outcome. Nothing is inferred by a model.
    """
    facts: list[StructuredFact] = []
    sides = [ref for ref in finding.evidence_refs if ref in evidence_by_id]

    for ref in sides:
        record = evidence_by_id[ref]
        facts.append(
            StructuredFact(
                fact_id=f"{ref}:document",
                kind=FactKind.DOCUMENT_NAME,
                value=record.document_id,
                source_ref=ref,
                document_ref=record.document_id,
            )
        )
        facts.append(
            StructuredFact(
                fact_id=f"{ref}:value",
                kind=_fact_kind_for(record.document_type, record.field_name),
                value=record.value,
                field_name=record.field_name,
                source_ref=ref,
                document_ref=record.document_id,
                confidence=record.confidence,
            )
        )

    if len(sides) >= 2 and aggregation is not None:
        comparison = _comparison_for(aggregation, sides[0], sides[1])
        if comparison is not None:
            facts.append(
                StructuredFact(
                    fact_id=(
                        f"comparison:{comparison.left_evidence_id}"
                        f"<->{comparison.right_evidence_id}"
                    ),
                    kind=FactKind.COMPARISON_OUTCOME,
                    comparison_outcome=comparison.outcome,
                    source_ref=comparison.left_evidence_id,
                    document_ref=comparison.left_document_id,
                )
            )
    return facts


def explain_finding(
    engine: ExplanationEngine,
    finding: VerificationFinding,
    *,
    evidence_by_id: dict[str, Evidence],
    aggregation: Any,
) -> ExplanationResult:
    """Explain an EXISTING finding. The explanation never changes flags."""
    sides = [ref for ref in finding.evidence_refs if ref in evidence_by_id]
    document_refs = sorted(
        {evidence_by_id[ref].document_id for ref in sides}
    )
    grounding = ExplanationGrounding(
        evidence_refs=tuple(sides),
        # Real Module 3 verification references for this finding (empty
        # for purely evidence-based cross-document findings).
        verification_refs=tuple(finding.verification_refs),
        document_refs=tuple(document_refs),
        finding_refs=(finding.finding_id,),
        comparison_refs=(),
        trace_refs=(),
    )
    facts = _facts_for_finding(finding, evidence_by_id, aggregation)
    return engine.explain(
        bidder_id=finding.bidder_id,
        flag_id=finding.flag_id,
        flag_state=True,  # a finding exists precisely because the flag is true
        grounding=grounding,
        finding=finding,
        facts=facts,
    )


def _coerce_verification_records(
    verification_records: Optional[Sequence[Any]],
) -> list[Verification]:
    """Accept real ``Verification`` objects or their JSON dumps — never invent."""
    if not verification_records:
        return []
    records: list[Verification] = []
    for record in verification_records:
        if isinstance(record, Verification):
            records.append(record)
        elif isinstance(record, dict):
            records.append(Verification.model_validate(record))
        else:
            raise TypeError(
                f"Verification record must be a Verification or a dict, "
                f"got {type(record).__name__}"
            )
    return records


def _coerce_compliance_results(
    compliance_results: Optional[Sequence[Any]],
) -> list[ComplianceResult]:
    """Accept real ``ComplianceResult`` objects or their JSON dumps."""
    if not compliance_results:
        return []
    results: list[ComplianceResult] = []
    for result in compliance_results:
        if isinstance(result, ComplianceResult):
            results.append(result)
        elif isinstance(result, dict):
            results.append(ComplianceResult.model_validate(result))
        else:
            raise TypeError(
                f"ComplianceResult must be a ComplianceResult or a dict, "
                f"got {type(result).__name__}"
            )
    return results


def build_verification_engine(
    *, evaluation_date_iso: Optional[str] = None
) -> tuple[VerificationEngine, _ObservedCrossDocumentEngine, _ObservedIdentityEngine]:
    """Wire the real Core engines using their actual constructor APIs."""
    cross_document_engine = _ObservedCrossDocumentEngine(
        CrossDocumentConsistencyEngine(evaluation_date_iso=evaluation_date_iso)
    )
    identity_engine = _ObservedIdentityEngine(IdentityReconciliationEngine())
    engine = VerificationEngine(
        identity_reconciliation_engine=identity_engine,
        cross_document_consistency_engine=cross_document_engine,
    )
    return engine, cross_document_engine, identity_engine


def run_bidder_verification(
    bidder_id: str,
    evidence: Sequence[Evidence],
    *,
    documents: Optional[Sequence[Any]] = None,
    submission_id: Optional[str] = None,
    evaluation_date_iso: Optional[str] = None,
    compliance_results: Optional[Sequence[Any]] = None,
    verification_records: Optional[Sequence[Any]] = None,
    explanation_engine: Optional[ExplanationEngine] = None,
    scoring_engine: Optional[Any] = None,
) -> dict[str, Any]:
    """Run Module 4 for one bidder over document-level Evidence.

    ``compliance_results`` / ``verification_records`` are the REAL Module
    3 outputs (the Core compliance engine's ``ComplianceResult[]`` /
    ``Verification[]``). The authoritative ``Verification[]`` records are
    handed to the real ``IdentityReconciliationEngine``; both artefacts
    are forwarded to Module 5 scoring. Both stay empty when Module 3
    produced nothing — never fabricated here.

    When ``documents`` (the Module 1/2 document records the Evidence was
    built from) is supplied, the EXISTING Core ``DocumentScoringEngine``
    runs AFTER the findings/flags/explanations exist and scores the same
    document-level Evidence Module 4 consumed (see
    ``scoring_service.score_bidder_documents``).
    """
    evidence_list = list(evidence)
    verification_list = _coerce_verification_records(verification_records)
    compliance_list = _coerce_compliance_results(compliance_results)
    engine, observed_cross_doc, observed_identity = build_verification_engine(
        evaluation_date_iso=evaluation_date_iso
    )
    result = engine.run(
        VerificationInput(
            bidder_id=str(bidder_id),
            evidence=evidence_list,
            verification_records=verification_list,
        )
    )

    aggregation = (
        observed_cross_doc.last_result.aggregation
        if observed_cross_doc.last_result is not None
        else None
    )
    # REAL IdentityFinding[] objects produced by the identity engine from
    # the Module 3 Verification[] records (empty when there was nothing
    # to reconcile). Forwarded to Module 5; never invented here.
    identity_findings = (
        list(observed_identity.last_result.identity_findings)
        if observed_identity.last_result is not None
        else []
    )
    evidence_by_id = {record.evidence_id: record for record in evidence_list}

    explainer = explanation_engine or ExplanationEngine()
    explanations = [
        explain_finding(
            explainer,
            finding,
            evidence_by_id=evidence_by_id,
            aggregation=aggregation,
        )
        for finding in result.findings
    ]

    outcome: dict[str, Any] = {
        "bidder_id": str(bidder_id),
        "status": STATUS_VERIFIED,
        "evidence": [e.model_dump(mode="json") for e in evidence_list],
        "findings": [f.model_dump(mode="json") for f in result.findings],
        "flags": sorted({f.flag_id for f in result.findings}),
        "explanations": [e.model_dump(mode="json") for e in explanations],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verification_records_used": len(verification_list),
        # REAL Module 3 outputs (empty when Module 3 produced nothing).
        "compliance_results": [r.model_dump(mode="json") for r in compliance_list],
        "verification_records": [v.model_dump(mode="json") for v in verification_list],
        "scoring": None,
    }

    if documents is not None:
        # Scoring happens strictly AFTER the deterministic Module 4
        # findings/flags above. The scorer consumes the SAME evidence and
        # finding objects; it never decides which flags exist.
        score = score_bidder_documents(
            bidder_id,
            submission_id=submission_id,
            documents=build_document_inputs(documents),
            requirements=(),  # no tender requirement data in the live pipeline
            evidence=evidence_list,
            compliance_results=compliance_list,  # REAL Module 3 output
            verification_records=verification_list,  # REAL Module 3 output
            findings=result.findings,
            identity_findings=identity_findings,  # REAL identity findings
            quality_by_document_id=None,  # not produced by this wiring today
            scoring_engine=scoring_engine,
        )
        outcome["scoring"] = score.model_dump(mode="json")

    return outcome


# --------------------------------------------------------------------------
# Application / persistence layer (uses the EXISTING SIH database)
# --------------------------------------------------------------------------


def run_module4_for_evaluation(
    evaluation_id: str,
    *,
    evaluation_date_iso: Optional[str] = None,
    db: Any = None,
) -> dict[str, Any]:
    """Run Module 4 for every bidder of an evaluation and persist results.

    Uses the application's existing PostgreSQL database. Prior results for
    the evaluation are replaced (idempotent re-runs). Per-bidder failures
    are recorded on the bidder's result row and surfaced in the evaluation
    status — they are never converted into a fake "no findings" outcome.
    """
    import uuid as _uuid

    from app.database import (  # deferred: keeps pure helpers DB-free
        BidderComplianceResultRecord,
        BidderDocumentScoreRecord,
        BidderFolder,
        BidderVerificationRecord,
        BidderVerificationResult,
        Document,
        DocumentEvidence,
        Evaluation,
        SessionLocal,
    )

    if isinstance(evaluation_id, _uuid.UUID):
        eval_uuid = evaluation_id
    else:
        eval_uuid = _uuid.UUID(str(evaluation_id))

    session = db or SessionLocal()
    owns_session = db is None
    bidder_results: list[dict[str, Any]] = []
    had_errors = False
    had_module3_errors = False

    try:
        evaluation = (
            session.query(Evaluation).filter(Evaluation.id == eval_uuid).first()
        )
        if evaluation is None:
            raise ValueError(f"Evaluation {evaluation_id} not found")

        bidder_folders = (
            session.query(BidderFolder)
            .filter(BidderFolder.evaluation_id == evaluation.id)
            .all()
        )

        for bidder in bidder_folders:
            documents = (
                session.query(Document)
                .filter(Document.bidder_folder_id == bidder.id)
                .all()
            )
            bidder_id = str(bidder.id)
            try:
                if not documents:
                    # Honest empty state: the bidder submitted no processable
                    # documents. This is neither a failure nor a clean pass.
                    outcome = {
                        "bidder_id": bidder_id,
                        "bidder_name": bidder.raw_folder_name,
                        "status": STATUS_NO_DOCUMENTS,
                        "evidence": [],
                        "findings": [],
                        "flags": [],
                        "explanations": [],
                        "generated_at": None,
                        "verification_records_used": 0,
                        "compliance_results": [],
                        "verification_records": [],
                        "scoring": None,
                    }
                else:
                    # Module 2 -> document-level Evidence (single pass over
                    # the fields Module 2 already extracted per document).
                    evidence = build_bidder_evidence(bidder_id, documents)

                    # Module 3: the REAL compliance engine over the SAME
                    # document-level Evidence. An engine failure is a
                    # MODULE3_FAILED state — never a fake clean outcome.
                    try:
                        module3 = run_module3_for_bidder(
                            bidder_id,
                            evidence,
                            submission_id=str(evaluation.id),
                        )
                    except Exception as exc:
                        had_module3_errors = True
                        raise _Module3Failure(str(exc)) from exc

                    # Module 4 (identity + cross-document) + explanations
                    # + Module 5 scoring over the same Evidence/documents.
                    outcome = run_bidder_verification(
                        bidder_id,
                        evidence,
                        documents=documents,
                        submission_id=str(evaluation.id),
                        evaluation_date_iso=evaluation_date_iso,
                        compliance_results=module3["_compliance_result_objects"],
                        verification_records=module3["_verification_record_objects"],
                    )
                    outcome["module3_status"] = module3["status"]
                    outcome["bidder_name"] = bidder.raw_folder_name
            except _Module3Failure as exc:
                had_errors = True
                outcome = {
                    "bidder_id": bidder_id,
                    "bidder_name": bidder.raw_folder_name,
                    "status": STATUS_MODULE3_FAILED,
                    "error": str(exc),
                    "evidence": [],
                    "findings": [],
                    "flags": [],
                    "explanations": [],
                    "generated_at": None,
                    "verification_records_used": 0,
                    "compliance_results": [],  # nothing fabricated
                    "verification_records": [],
                    "scoring": None,  # no score without Module 3 results
                }
            except Exception as exc:  # never mask a failure as "no findings"
                had_errors = True
                outcome = {
                    "bidder_id": bidder_id,
                    "bidder_name": bidder.raw_folder_name,
                    "status": STATUS_FAILED,
                    "error": str(exc),
                    "evidence": [],
                    "findings": [],
                    "flags": [],
                    "explanations": [],
                    "generated_at": None,
                    "verification_records_used": 0,
                    "compliance_results": [],
                    "verification_records": [],
                    "scoring": None,
                }

            # Persist document-level evidence provenance (replace-on-rerun).
            session.query(DocumentEvidence).filter(
                DocumentEvidence.bidder_folder_id == bidder.id
            ).delete()
            for record in outcome["evidence"]:
                session.add(
                    DocumentEvidence(
                        evaluation_id=evaluation.id,
                        bidder_folder_id=bidder.id,
                        evidence_id=record["evidence_id"],
                        document_id=record["document_id"],
                        document_type=record["document_type"],
                        field_name=record["field_name"],
                        value={"value": record.get("value")},
                        confidence=record.get("confidence"),
                        page=record.get("page"),
                        bbox=record.get("bbox"),
                    )
                )

            session.query(BidderVerificationResult).filter(
                BidderVerificationResult.bidder_folder_id == bidder.id
            ).delete()
            session.add(
                BidderVerificationResult(
                    evaluation_id=evaluation.id,
                    bidder_folder_id=bidder.id,
                    status=outcome["status"],
                    findings=outcome["findings"],
                    flags=outcome["flags"],
                    explanations=outcome["explanations"],
                    error=outcome.get("error"),
                )
            )

            # Persist the REAL Module 3 outputs (replace-on-rerun): one
            # compliance-result row per evaluated requirement and one
            # verification-record row per provider query. Rows are
            # faithful copies of the engine's own models — a provider
            # outage stays UNAVAILABLE/UNVERIFIABLE, never a fake pass.
            session.query(BidderComplianceResultRecord).filter(
                BidderComplianceResultRecord.bidder_folder_id == bidder.id
            ).delete()
            for result in outcome.get("compliance_results") or []:
                session.add(
                    BidderComplianceResultRecord(
                        evaluation_id=evaluation.id,
                        bidder_folder_id=bidder.id,
                        bidder_id=outcome["bidder_id"],
                        requirement_id=result.get("requirement_id"),
                        capability=result.get("capability"),
                        status=result.get("status"),
                        reason=result.get("reason"),
                        rule_id=result.get("rule_id"),
                        expected=result.get("expected"),
                        actual=result.get("actual"),
                        evidence_refs=list(result.get("evidence_refs") or []),
                        verification_refs=list(result.get("verification_refs") or []),
                        flags=list(result.get("flags") or []),
                    )
                )
            session.query(BidderVerificationRecord).filter(
                BidderVerificationRecord.bidder_folder_id == bidder.id
            ).delete()
            for record in outcome.get("verification_records") or []:
                session.add(
                    BidderVerificationRecord(
                        evaluation_id=evaluation.id,
                        bidder_folder_id=bidder.id,
                        bidder_id=outcome["bidder_id"],
                        verification_id=record.get("verification_id"),
                        capability=record.get("capability"),
                        source=record.get("source"),
                        queried_identifier=record.get("queried_identifier"),
                        status=record.get("status"),
                        data=record.get("data"),
                        evidence_id=record.get("evidence_id"),
                        document_id=record.get("document_id"),
                        transport_status_code=record.get("transport_status_code"),
                        retrieved_at=record.get("retrieved_at"),
                    )
                )

            # Persist the DocumentScoringEngine output (replace-on-rerun).
            # No score row is written when verification failed or the
            # bidder had no documents — a failure is never converted into
            # a fake score, and an empty bidder honestly has no score.
            session.query(BidderDocumentScoreRecord).filter(
                BidderDocumentScoreRecord.bidder_folder_id == bidder.id
            ).delete()
            scoring = outcome.get("scoring")
            if scoring is not None:
                session.add(
                    BidderDocumentScoreRecord(
                        evaluation_id=evaluation.id,
                        bidder_folder_id=bidder.id,
                        bidder_id=outcome["bidder_id"],
                        submission_id=scoring.get("submission_id"),
                        status=outcome["status"],
                        overall_score=scoring["score"],
                        category=scoring["category"],
                        reason_codes=scoring["reason_codes"],
                        document_scores=scoring["documents"],
                        summary=scoring["summary"],
                    )
                )
            session.commit()
            bidder_results.append(outcome)

        if had_module3_errors:
            evaluation.status = (
                f"{STATUS_MODULE3_FAILED}: at least one bidder failed"
            )
        elif had_errors:
            evaluation.status = f"{STATUS_FAILED}: at least one bidder failed"
        else:
            evaluation.status = STATUS_VERIFIED
        session.commit()

        return {
            "status": evaluation.status,
            "evaluation_id": str(evaluation.id),
            "total_bidders": len(bidder_results),
            "bidders": bidder_results,
        }
    except Exception:
        if owns_session:
            session.rollback()
        raise
    finally:
        if owns_session:
            session.close()


__all__ = [
    "STATUS_FAILED",
    "STATUS_MODULE3_FAILED",
    "STATUS_NO_DOCUMENTS",
    "STATUS_VERIFIED",
    "build_verification_engine",
    "explain_finding",
    "run_bidder_verification",
    "run_module4_for_evaluation",
]
