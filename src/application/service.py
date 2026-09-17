"""Application service: orchestrates the existing engines end-to-end.

Flow implemented here (each stage durable via the processing coordinator)::

    BIDDER SUBMISSION        (validate + persist bidder/submission/docs)
      -> DOCUMENT / EVIDENCE INGESTION   (persist evidence rows)
      -> VERIFICATION / RULE EVALUATION  (ComplianceEngine only)
      -> CROSS-DOCUMENT / CROSS-BIDDER   (VerificationEngine only)
      -> CANONICAL BOOLEAN FLAGS         (flag projection, not logic)
      -> BOOLEAN FLAG SNAPSHOT           (materialize_flag_snapshot)
      -> GROUNDED EXPLANATION            (ExplanationEngine / fallback)
      -> PROCUREMENT OFFICER REVIEW      (persisted, retrievable)

The service contains no compliance logic. If a rule or an engine raises,
the submission is marked FAILED with the classified error kind and the
exception propagates -- an infrastructure failure is never converted
into a compliance outcome.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable, Iterable

from ai_verification.engine import VerificationEngine
from ai_verification.explanations.engine import ExplanationEngine
from ai_verification.explanations.facts import FactKind, StructuredFact
from ai_verification.explanations.grounding import ExplanationGrounding
from ai_verification.explanations.models import ExplanationResult
from ai_verification.explanations.pipeline import to_explanation_record
from ai_verification.models.contracts import (
    VerificationFinding,
    VerificationInput,
)
from compliance_engine.engine import ComplianceEngine
from compliance_engine.flags import FLAG_REGISTRY
from compliance_engine.models import (
    ComplianceResult,
    EngineResult,
    IdentityFinding,
)

from infrastructure.audit import audit_event
from infrastructure.artifacts import ArtifactStore
from infrastructure.errors import (
    FailureKind,
    ProcessingError,
    classify_failure,
)
from infrastructure.flags import (
    BidderFlagSnapshot,
    materialize_flag_snapshot,
)
from infrastructure.jobs.models import Job
from infrastructure.jobs.queue import InMemoryJobQueue, JobQueue
from infrastructure.persistence.memory import _Store
from infrastructure.persistence.records import (
    ComplianceResultRecord,
    EvidenceRecord,
    FlagSnapshotRecord,
    VerificationRecord,
    FindingRecord,
)
from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork
from infrastructure.pipeline import ProcessingStage
from infrastructure.processing import IngestedDocument, ProcessingCoordinator

from application.flag_projection import (
    compliance_finding_id,
    compliance_result_id,
    identity_finding_id,
    project_flag_states,
)
from application.models import (
    ApplicationResult,
    BidderSubmission,
    CompliancePayload,
    ExplanationSummary,
    FindingSummary,
    ProcessingSummary,
    RequirementOutcome,
    SubmissionDocument,
    VerificationSummary,
)

#: Queue job type for asynchronous submission processing.
COMPLIANCE_JOB_TYPE = "COMPLIANCE_RUN"


class ComplianceApplicationService:
    """Orchestrates a bidder submission through the existing engines.

    Dependencies (engines, persistence, queue) are constructor-injected.
    By default the service runs entirely in memory: the in-memory unit of
    work and job queue satisfy the same contracts as the PostgreSQL and
    Redis adapters, so the demo/test path exercises the real flow without
    any external service.
    """

    def __init__(
        self,
        *,
        compliance_engine: ComplianceEngine,
        verification_engine: VerificationEngine | None = None,
        explanation_engine: ExplanationEngine | None = None,
        uow_factory: Callable[[], Any] | None = None,
        queue: JobQueue | None = None,
        artifact_store: ArtifactStore | None = None,
        known_flag_ids: Iterable[str] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock or time.time
        self._store = _Store()
        self._uow_factory = (
            uow_factory or (lambda: InMemoryUnitOfWork(self._store))
        )
        self._queue = queue or InMemoryJobQueue(clock=self._clock)
        self._coordinator = ProcessingCoordinator(
            self._uow_factory,
            self._queue,
            artifact_store=artifact_store,
            clock=self._clock,
        )
        self._compliance_engine = compliance_engine
        self._verification_engine = verification_engine
        self._explanation_engine = explanation_engine or ExplanationEngine()
        # ``None`` => the full canonical registry is the flag universe:
        # every known flag appears in the snapshot, defaulting to ``false``.
        self._known_flag_ids = (
            sorted(FLAG_REGISTRY) if known_flag_ids is None else known_flag_ids
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @property
    def queue(self) -> JobQueue:
        return self._queue

    def process_bid(self, submission: BidderSubmission) -> ApplicationResult:
        """Synchronous end-to-end processing of one bidder submission.

        Idempotent at submission granularity: re-submitting a submission
        that already reached ``COMPLETE`` returns the persisted result
        without re-running the engines.
        """
        submission = BidderSubmission.validate_or_raise(submission)
        existing = self._get_submission(submission.submission_id)
        if existing is not None:
            if existing.stage == ProcessingStage.COMPLETE.value:
                return self._reconstruct(
                    existing.bidder_id, submission.submission_id
                )
            raise ProcessingError(
                f"Submission {submission.submission_id!r} already exists "
                f"at stage {existing.stage}; resubmit it as a new "
                "submission_id or resume via the coordinator.",
                kind=FailureKind.PERMANENT_VALIDATION,
            )
        correlation_id = submission.correlation_id or self._new_correlation_id()
        self._ingest(submission, correlation_id=correlation_id)
        return self._process_existing_submission(
            submission, correlation_id=correlation_id
        )

    def _process_existing_submission(
        self, submission: BidderSubmission, *, correlation_id: str | None = None
    ) -> ApplicationResult:
        """Run the pipeline for an already-ingested submission, marking it
        FAILED (with the classified error kind) on any exception."""
        correlation_id = (
            correlation_id or submission.correlation_id
            or self._new_correlation_id()
        )
        try:
            return self._run_pipeline(
                submission, correlation_id=correlation_id
            )
        except Exception as exc:
            self._fail_submission(submission.submission_id, exc, correlation_id)
            raise

    def enqueue_submission(
        self, submission: BidderSubmission
    ) -> Job:
        """Ingest + enqueue a submission for asynchronous processing.

        The durable submission row is created immediately; the job is
        enqueued with a deterministic idempotency key, so a duplicate
        enqueue returns the existing job rather than duplicating work.
        """
        submission = BidderSubmission.validate_or_raise(submission)
        correlation_id = submission.correlation_id or self._new_correlation_id()
        existing = self._get_submission(submission.submission_id)
        if existing is not None:
            if existing.stage == ProcessingStage.COMPLETE.value:
                raise ProcessingError(
                    f"Submission {submission.submission_id!r} is already "
                    "COMPLETE.",
                    kind=FailureKind.PERMANENT_VALIDATION,
                )
        else:
            self._ingest(submission, correlation_id=correlation_id)

        payload = submission.model_dump(
            mode="json",
            # The binaries live in the artifact store, never in the queue.
            exclude={"documents": {"__all__": {"content"}}},
        )
        from infrastructure.jobs.idempotency import make_idempotency_key

        idempotency_key = make_idempotency_key(
            submission_id=submission.submission_id,
            stage=COMPLIANCE_JOB_TYPE,
            logical_input={"submission": payload},
        )
        existing_job = self._queue.find_by_idempotency_key(idempotency_key)
        if existing_job is not None:
            # Idempotent redelivery: the same logical work item returns
            # the original job instead of a duplicate.
            return existing_job
        return self._coordinator.enqueue_stage_job(
            submission.submission_id,
            COMPLIANCE_JOB_TYPE,
            bidder_id=submission.bidder_id,
            job_id=f"job:compliance:{submission.submission_id}",
            payload={"submission": payload},
            correlation_id=correlation_id,
        )

    def reconstruct_result(self, bidder_id: str) -> ApplicationResult | None:
        """Re-read the persisted result for a bidder (review retrieval)."""
        uow = self._uow_factory()
        with uow:
            submissions = uow.repos.submissions.list_by_bidder(bidder_id)
        if not submissions:
            return None
        latest = max(submissions, key=lambda s: s.updated_at)
        return self._reconstruct(bidder_id, latest.submission_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_submission(self, submission_id: str):
        uow = self._uow_factory()
        with uow:
            return uow.repos.submissions.get(submission_id)

    @staticmethod
    def _new_correlation_id() -> str:
        return f"corr:{uuid.uuid4().hex}"

    def _ingest(
        self, submission: BidderSubmission, *, correlation_id: str
    ) -> None:
        self._coordinator.ingest_submission(
            submission.bidder_id,
            submission.submission_id,
            [
                IngestedDocument(
                    document_id=doc.document_id,
                    document_type=doc.document_type,
                    content=doc.content,
                    metadata=dict(doc.metadata),
                )
                for doc in submission.documents
            ],
            correlation_id=correlation_id,
        )

    def _fail_submission(
        self, submission_id: str, exc: BaseException, correlation_id: str
    ) -> None:
        kind = classify_failure(exc)
        try:
            self._coordinator.fail_submission(
                submission_id,
                error=str(exc)[:1000],
                error_kind=kind.value,
                correlation_id=correlation_id,
            )
        except Exception:  # never mask the original failure
            pass

    def _advance(
        self, submission_id: str, stage: ProcessingStage, correlation_id: str
    ) -> None:
        self._coordinator.advance_stage(
            submission_id, stage, correlation_id=correlation_id
        )

    def _run_pipeline(
        self, submission: BidderSubmission, *, correlation_id: str
    ) -> ApplicationResult:
        """Run the pipeline for an already-ingested submission.

        Raises on any engine/persistence failure; the caller is
        responsible for marking the submission FAILED.
        """
        bidder_id = submission.bidder_id
        sid = submission.submission_id

        # 1. NORMALIZED: persist the evidence rows.
        self._advance(sid, ProcessingStage.NORMALIZED, correlation_id)
        self._persist_evidence(submission)

        # 2. VERIFICATION: deterministic rule + provider evaluation.
        self._advance(sid, ProcessingStage.VERIFICATION_PENDING, correlation_id)
        engine_result = self._compliance_engine.run(
            submission.evidence, submission.requirements
        )
        self._persist_engine_outputs(
            bidder_id, engine_result, correlation_id=correlation_id
        )
        self._advance(sid, ProcessingStage.VERIFIED, correlation_id)

        # 3. AI ANALYSIS: cross-document + cross-bidder findings only.
        self._advance(sid, ProcessingStage.AI_ANALYSIS_PENDING, correlation_id)
        verification_findings: list[VerificationFinding] = []
        if self._verification_engine is not None:
            ai_result = self._verification_engine.run(
                VerificationInput(
                    bidder_id=bidder_id,
                    evidence=list(submission.evidence),
                    compliance_results=list(engine_result.compliance_results),
                    identity_findings=list(engine_result.identity_findings),
                    verification_records=list(engine_result.verification_records),
                    bidder_corpus=list(submission.bidder_corpus),
                )
            )
            verification_findings = list(ai_result.findings)
        self._persist_verification_findings(
            bidder_id, verification_findings
        )
        self._advance(sid, ProcessingStage.AI_ANALYZED, correlation_id)

        # 4. EXPLANATION: boolean flag projection + snapshot + grounded
        #    explanations. Flags come only from engine outputs.
        self._advance(sid, ProcessingStage.EXPLANATION_PENDING, correlation_id)
        now = self._clock()
        states = project_flag_states(
            bidder_id=bidder_id,
            compliance_results=list(engine_result.compliance_results),
            verification_findings=verification_findings,
            identity_findings=list(engine_result.identity_findings),
            correlation_id=correlation_id,
            updated_at=now,
        )
        snapshot = self._persist_flags_and_snapshot(
            bidder_id, states, correlation_id=correlation_id
        )
        explanations = self._explain_flags(
            bidder_id,
            states,
            engine_result=engine_result,
            verification_findings=verification_findings,
            correlation_id=correlation_id,
        )
        self._advance(sid, ProcessingStage.EXPLANATION_READY, correlation_id)
        self._advance(sid, ProcessingStage.COMPLETE, correlation_id)

        return self._assemble_result(
            bidder_id=bidder_id,
            submission_id=sid,
            correlation_id=correlation_id,
            snapshot=snapshot,
            engine_result=engine_result,
            verification_findings=verification_findings,
            explanations=explanations,
        )

    def _persist_evidence(self, submission: BidderSubmission) -> None:
        """Persist evidence rows; idempotent so a retried job is safe."""
        uow = self._uow_factory()
        with uow:
            for item in submission.evidence:
                if uow.repos.evidence.get(item.evidence_id) is not None:
                    continue
                uow.repos.evidence.add(
                    EvidenceRecord(
                        evidence_id=item.evidence_id,
                        bidder_id=item.bidder_id,
                        document_id=item.document_id,
                        field_name=item.field_name,
                        document_type=item.document_type,
                        value=item.value,
                        confidence=item.confidence,
                        page=item.page,
                        bbox=list(item.bbox) if item.bbox else None,
                        created_at=self._clock(),
                    )
                )

    def _persist_engine_outputs(
        self,
        bidder_id: str,
        engine_result: EngineResult,
        *,
        correlation_id: str,
    ) -> None:
        now = self._clock()
        uow = self._uow_factory()
        with uow:
            for verification in engine_result.verification_records:
                uow.repos.verifications.save(
                    VerificationRecord(
                        verification_id=verification.verification_id,
                        bidder_id=verification.bidder_id,
                        capability=verification.capability,
                        source=verification.source,
                        queried_identifier=verification.queried_identifier,
                        status=verification.status.value,
                        data=dict(verification.data),
                        query=verification.query,
                        raw_response=verification.raw_response,
                        retrieved_at=verification.retrieved_at.timestamp(),
                        latency_ms=verification.latency_ms,
                        correlation_id=verification.correlation_id
                        or correlation_id,
                        transport_status_code=verification.transport_status_code,
                        evidence_id=verification.evidence_id,
                        document_id=verification.document_id,
                        created_at=now,
                    )
                )
            for result in engine_result.compliance_results:
                uow.repos.compliance_results.save(
                    ComplianceResultRecord(
                        result_id=compliance_result_id(
                            bidder_id, result.requirement_id
                        ),
                        bidder_id=bidder_id,
                        requirement_id=result.requirement_id,
                        capability=result.capability,
                        status=result.status.value,
                        reason=result.reason,
                        expected=result.expected,
                        actual=result.actual,
                        rule_id=result.rule_id,
                        evidence_refs=list(result.evidence_refs),
                        verification_refs=list(result.verification_refs),
                        flags=list(result.flags),
                        created_at=now,
                        updated_at=now,
                    )
                )
                for flag_id in result.flags:
                    uow.repos.findings.save(
                        FindingRecord(
                            finding_id=compliance_finding_id(
                                bidder_id, result.requirement_id, flag_id
                            ),
                            bidder_id=bidder_id,
                            finding_type="COMPLIANCE",
                            flag_id=flag_id,
                            payload={
                                "requirement_id": result.requirement_id,
                                "rule_id": result.rule_id,
                                "status": result.status.value,
                                "reason": result.reason,
                            },
                            evidence_refs=list(result.evidence_refs),
                            verification_refs=list(result.verification_refs),
                            created_at=now,
                        )
                    )
            for finding in engine_result.identity_findings:
                uow.repos.findings.save(
                    FindingRecord(
                        finding_id=identity_finding_id(bidder_id, finding),
                        bidder_id=bidder_id,
                        finding_type="IDENTITY",
                        flag_id=finding.flag_id,
                        payload=finding.model_dump(mode="json"),
                        evidence_refs=list(finding.evidence_refs),
                        created_at=now,
                    )
                )

    def _persist_verification_findings(
        self, bidder_id: str, findings: list[VerificationFinding]
    ) -> None:
        if not findings:
            return
        now = self._clock()
        uow = self._uow_factory()
        with uow:
            for finding in findings:
                uow.repos.findings.save(
                    FindingRecord(
                        finding_id=finding.finding_id,
                        bidder_id=bidder_id,
                        finding_type="VERIFICATION",
                        flag_id=finding.flag_id,
                        payload=finding.model_dump(mode="json"),
                        evidence_refs=list(finding.evidence_refs),
                        verification_refs=list(finding.verification_refs),
                        related_bidder_ids=list(finding.related_bidder_ids),
                        created_at=now,
                    )
                )

    def _persist_flags_and_snapshot(
        self,
        bidder_id: str,
        states: list,
        *,
        correlation_id: str,
    ) -> BidderFlagSnapshot:
        now = self._clock()
        snapshot = materialize_flag_snapshot(
            bidder_id,
            states,
            known_flag_ids=self._known_flag_ids,
            clock=self._clock,
        )
        uow = self._uow_factory()
        with uow:
            for state in states:
                uow.repos.flags.save_state(state)
            uow.repos.flags.save_snapshot(
                FlagSnapshotRecord(
                    snapshot_id=snapshot.snapshot_id,
                    bidder_id=bidder_id,
                    snapshot_version=str(snapshot.snapshot_version),
                    flags=dict(snapshot.flags),
                    provenance=dict(snapshot.provenance),
                    content_hash=snapshot.content_hash,
                    correlation_id=correlation_id,
                    created_at=now,
                )
            )
            uow.repos.audit.add(
                audit_event(
                    aggregate_type="FLAG_SNAPSHOT",
                    aggregate_id=snapshot.snapshot_id,
                    event_type="FLAG_SNAPSHOT_MATERIALIZED",
                    payload={
                        "bidder_id": bidder_id,
                        "set_flags": sorted(
                            f for f, v in snapshot.flags.items() if v
                        ),
                    },
                    correlation_id=correlation_id,
                    created_at=now,
                )
            )
        return snapshot

    def _explain_flags(
        self,
        bidder_id: str,
        states: list,
        *,
        engine_result: EngineResult,
        verification_findings: list[VerificationFinding],
        correlation_id: str,
    ) -> dict[str, ExplanationResult]:
        """Generate and persist grounded explanations for set flags.

        The explanation engine never decides the flag state: the boolean
        computed by the deterministic pipeline above is passed in as-is.
        With no model configured the deterministic fallback is used.
        """
        results_by_flag: dict[str, list[ComplianceResult]] = {}
        for result in engine_result.compliance_results:
            for flag_id in result.flags:
                results_by_flag.setdefault(flag_id, []).append(result)

        uow = self._uow_factory()
        with uow:
            document_id_by_evidence = {
                item.evidence_id: item.document_id
                for item in uow.repos.evidence.list_by_bidder(bidder_id)
            }

        explanations: dict[str, ExplanationResult] = {}
        for state in states:
            if not state.is_set:
                continue
            grounding = ExplanationGrounding(
                evidence_refs=tuple(state.evidence_refs),
                verification_refs=tuple(state.verification_refs),
                document_refs=tuple(
                    sorted(
                        {
                            document_id_by_evidence[eid]
                            for eid in state.evidence_refs
                            if eid in document_id_by_evidence
                        }
                    )
                ),
                finding_refs=tuple(state.finding_refs),
            )
            facts = self._facts_for_flag(
                state, results_by_flag.get(state.flag_id, [])
            )
            result = self._explanation_engine.explain(
                bidder_id,
                state.flag_id,
                state.is_set,
                grounding,
                facts=facts,
                correlation_id=correlation_id,
            )
            now = self._clock()
            uow = self._uow_factory()
            with uow:
                uow.repos.explanations.save(
                    to_explanation_record(result, created_at=now)
                )
                uow.repos.audit.add(
                    audit_event(
                        aggregate_type="EXPLANATION",
                        aggregate_id=result.explanation_id,
                        event_type="EXPLANATION_READY",
                        payload={
                            "bidder_id": bidder_id,
                            "flag_id": state.flag_id,
                            "fallback_used": result.fallback_used,
                            "validation_status": result.validation_status.value,
                        },
                        correlation_id=correlation_id,
                        created_at=now,
                    )
                )
            explanations[state.flag_id] = result
        return explanations

    @staticmethod
    def _facts_for_flag(state, results: list[ComplianceResult]):
        """Structured facts for one flag, from its contributing results."""
        facts: list[StructuredFact] = []
        for result in results:
            source_ref = result.evidence_refs[0] if result.evidence_refs else None
            verification_ref = (
                result.verification_refs[0] if result.verification_refs else None
            )
            if isinstance(result.expected, (str, int, float, bool)):
                facts.append(
                    StructuredFact(
                        fact_id=(
                            f"{state.flag_id}:expected:{result.requirement_id}"
                        ),
                        kind=FactKind.EXPECTED_VALUE,
                        value=result.expected,
                        source_ref=source_ref,
                        verification_ref=verification_ref,
                    )
                )
            actual = result.actual
            if isinstance(actual, dict) and actual.get("status") is not None:
                facts.append(
                    StructuredFact(
                        fact_id=(
                            f"{state.flag_id}:status:{result.requirement_id}"
                        ),
                        kind=FactKind.VERIFICATION_STATUS,
                        value=str(actual["status"]),
                        source_ref=source_ref,
                        verification_ref=verification_ref,
                    )
                )
            elif isinstance(actual, (str, int, float, bool)):
                facts.append(
                    StructuredFact(
                        fact_id=f"{state.flag_id}:actual:{result.requirement_id}",
                        kind=FactKind.ACTUAL_VALUE,
                        value=actual,
                        source_ref=source_ref,
                        verification_ref=verification_ref,
                    )
                )
        return facts

    def _assemble_result(
        self,
        *,
        bidder_id: str,
        submission_id: str,
        correlation_id: str,
        snapshot: BidderFlagSnapshot,
        engine_result: EngineResult,
        verification_findings: list[VerificationFinding],
        explanations: dict[str, ExplanationResult],
    ) -> ApplicationResult:
        compliance = CompliancePayload(
            bidder_id=bidder_id,
            flags=dict(snapshot.downstream_payload()["flags"]),
        )
        return ApplicationResult(
            compliance=compliance,
            processing=ProcessingSummary(
                submission_id=submission_id,
                stage=ProcessingStage.COMPLETE.value,
                correlation_id=correlation_id,
                snapshot_id=snapshot.snapshot_id,
            ),
            requirements=[
                RequirementOutcome(
                    requirement_id=r.requirement_id,
                    capability=str(r.capability),
                    status=r.status.value,
                    rule_id=r.rule_id,
                    flags=list(r.flags),
                )
                for r in engine_result.compliance_results
            ],
            verifications=[
                VerificationSummary(
                    verification_id=v.verification_id,
                    capability=str(v.capability),
                    source=v.source,
                    status=v.status.value,
                    queried_identifier=v.queried_identifier,
                )
                for v in engine_result.verification_records
            ],
            findings=(
                [
                    FindingSummary(
                        finding_id=f.finding_id,
                        flag_id=f.flag_id,
                        finding_type="VERIFICATION",
                        related_bidder_ids=list(f.related_bidder_ids),
                    )
                    for f in verification_findings
                ]
                + [
                    FindingSummary(
                        finding_id=identity_finding_id(bidder_id, f),
                        flag_id=f.flag_id,
                        finding_type="IDENTITY",
                    )
                    for f in engine_result.identity_findings
                ]
                + [
                    FindingSummary(
                        finding_id=compliance_finding_id(
                            bidder_id, r.requirement_id, flag_id
                        ),
                        flag_id=flag_id,
                        finding_type="COMPLIANCE",
                    )
                    for r in engine_result.compliance_results
                    for flag_id in r.flags
                ]
            ),
            explanations=[
                ExplanationSummary(
                    explanation_id=e.explanation_id,
                    flag_id=e.flag_id,
                    text=e.content.summary,
                    fallback_used=e.fallback_used,
                    validation_status=e.validation_status.value,
                )
                for e in explanations.values()
            ],
        )

    def _reconstruct(self, bidder_id: str, submission_id: str) -> ApplicationResult:
        """Re-read a persisted result for a COMPLETE submission."""
        uow = self._uow_factory()
        with uow:
            submission = uow.repos.submissions.get(submission_id)
            if submission is None:
                raise LookupError(f"Unknown submission {submission_id!r}.")
            snapshots = uow.repos.flags.list_snapshots(bidder_id)
            if not snapshots:
                raise LookupError(
                    f"No flag snapshot persisted for bidder {bidder_id!r}."
                )
            snapshot = max(snapshots, key=lambda s: s.created_at)
            results = uow.repos.compliance_results.list_by_bidder(bidder_id)
            verifications = uow.repos.verifications.list_by_bidder(bidder_id)
            findings = uow.repos.findings.list_by_bidder(bidder_id)
            explanations = uow.repos.explanations.list_by_bidder(bidder_id)
        return ApplicationResult(
            compliance=CompliancePayload(
                bidder_id=bidder_id, flags=dict(snapshot.flags)
            ),
            processing=ProcessingSummary(
                submission_id=submission_id,
                stage=submission.stage,
                correlation_id=submission.correlation_id,
                snapshot_id=snapshot.snapshot_id,
            ),
            requirements=[
                RequirementOutcome(
                    requirement_id=r.requirement_id,
                    capability=r.capability,
                    status=r.status,
                    rule_id=r.rule_id,
                    flags=list(r.flags),
                )
                for r in sorted(results, key=lambda r: r.requirement_id)
            ],
            verifications=[
                VerificationSummary(
                    verification_id=v.verification_id,
                    capability=v.capability,
                    source=v.source,
                    status=v.status,
                    queried_identifier=v.queried_identifier,
                )
                for v in sorted(verifications, key=lambda v: v.verification_id)
            ],
            findings=[
                FindingSummary(
                    finding_id=f.finding_id,
                    flag_id=f.flag_id,
                    finding_type=f.finding_type,
                    related_bidder_ids=list(f.related_bidder_ids),
                )
                for f in sorted(findings, key=lambda f: f.finding_id)
            ],
            explanations=[
                ExplanationSummary(
                    explanation_id=e.explanation_id,
                    flag_id=e.flag_id,
                    text=e.concise_text,
                    fallback_used=bool(e.fallback_used),
                    validation_status=e.validation_status,
                )
                for e in sorted(explanations, key=lambda e: e.explanation_id)
            ],
        )


__all__ = ["COMPLIANCE_JOB_TYPE", "ComplianceApplicationService"]
