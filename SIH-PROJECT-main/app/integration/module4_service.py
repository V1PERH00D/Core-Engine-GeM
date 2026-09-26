"""Module 4 orchestration service.

This service wires and runs the EXISTING Core-Engine-GeM engines:

    VerificationEngine(
        identity_reconciliation_engine=IdentityReconciliationEngine(),
        cross_document_consistency_engine=CrossDocumentConsistencyEngine(...),
    )

* The ``CrossDocumentConsistencyEngine`` runs on the *document-level*
  Evidence produced by the Module 1/2 adapter — this is the mandatory
  current-integration path.
* The ``IdentityReconciliationEngine`` is wired normally but receives
  whatever (currently zero) authoritative ``Verification`` records exist;
  today the correct "no authoritative verification yet" semantics apply
  until the future Module 3 stage (see ``future_module3.py``) exists. No
  fake Verification objects are ever constructed here.
* Explanations are produced AFTER findings, by Core's
  ``ExplanationEngine``, grounded in the finding's real source evidence
  and the structured pairwise comparison. The deterministic fallback
  generator is the default; an LLM may explain but can never create,
  remove or modify a flag.
"""

from __future__ import annotations

import datetime
from typing import Any, Optional, Sequence

from compliance_engine.models import Evidence

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

from .module12_adapter import build_bidder_evidence

STATUS_VERIFIED = "VERIFIED"
STATUS_FAILED = "MODULE4_FAILED"
STATUS_NO_DOCUMENTS = "NO_DOCUMENTS"


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
        verification_refs=tuple(),
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


def build_verification_engine(
    *, evaluation_date_iso: Optional[str] = None
) -> tuple[VerificationEngine, _ObservedCrossDocumentEngine]:
    """Wire the real Core engines using their actual constructor APIs."""
    cross_document_engine = _ObservedCrossDocumentEngine(
        CrossDocumentConsistencyEngine(evaluation_date_iso=evaluation_date_iso)
    )
    engine = VerificationEngine(
        identity_reconciliation_engine=IdentityReconciliationEngine(),
        cross_document_consistency_engine=cross_document_engine,
    )
    return engine, cross_document_engine


def run_bidder_verification(
    bidder_id: str,
    evidence: Sequence[Evidence],
    *,
    evaluation_date_iso: Optional[str] = None,
    verification_records: Optional[Sequence[Any]] = None,
    explanation_engine: Optional[ExplanationEngine] = None,
) -> dict[str, Any]:
    """Run Module 4 for one bidder over document-level Evidence.

    ``verification_records`` remains empty until the future Module 3
    supplies authoritative Verification records; identity reconciliation
    is wired and simply has nothing to reconcile today.
    """
    evidence_list = list(evidence)
    engine, observed_cross_doc = build_verification_engine(
        evaluation_date_iso=evaluation_date_iso
    )
    result = engine.run(
        VerificationInput(
            bidder_id=str(bidder_id),
            evidence=evidence_list,
            verification_records=list(verification_records or []),
        )
    )

    aggregation = (
        observed_cross_doc.last_result.aggregation
        if observed_cross_doc.last_result is not None
        else None
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

    return {
        "bidder_id": str(bidder_id),
        "status": STATUS_VERIFIED,
        "evidence": [e.model_dump(mode="json") for e in evidence_list],
        "findings": [f.model_dump(mode="json") for f in result.findings],
        "flags": sorted({f.flag_id for f in result.findings}),
        "explanations": [e.model_dump(mode="json") for e in explanations],
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "verification_records_used": len(verification_records or []),
    }


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
        BidderFolder,
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
                    }
                else:
                    evidence = build_bidder_evidence(bidder_id, documents)
                    outcome = run_bidder_verification(
                        bidder_id,
                        evidence,
                        evaluation_date_iso=evaluation_date_iso,
                    )
                    outcome["bidder_name"] = bidder.raw_folder_name
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
            session.commit()
            bidder_results.append(outcome)

        evaluation.status = (
            f"{STATUS_FAILED}: at least one bidder failed"
            if had_errors
            else STATUS_VERIFIED
        )
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
    "STATUS_NO_DOCUMENTS",
    "STATUS_VERIFIED",
    "build_verification_engine",
    "explain_finding",
    "run_bidder_verification",
    "run_module4_for_evaluation",
]
