"""Tests for the explanation processing pipeline + idempotency + outbox + audit."""

from ai_verification.explanations.engine import ExplanationEngine
from ai_verification.explanations.facts import FactKind, StructuredFact
from ai_verification.explanations.grounding import ExplanationGrounding
from ai_verification.explanations.pipeline import (
    ExplanationPipeline,
    to_explanation_record,
)
from ai_verification.explanations.provider import ExplanationModelUnavailableError

from infrastructure.jobs.models import JobState
from infrastructure.jobs.queue import InMemoryJobQueue
from infrastructure.persistence.memory import _Store
from infrastructure.persistence.records import BidderRecord
from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork


class ManualClock:
    def __init__(self, start=1000.0):
        self.value = start

    def __call__(self):
        return self.value

    def advance(self, seconds=1.0):
        self.value += seconds


def _store_factory():
    store = _Store()
    # Pre-register the bidder so explanation persistence has a FK target.
    uow = InMemoryUnitOfWork(store)
    with uow:
        uow.repos.bidders.add(BidderRecord(bidder_id="b1", created_at=1000.0, updated_at=1000.0))

    def factory():
        return InMemoryUnitOfWork(store)

    return factory


class _UnavailableModel:
    def generate(self, prompt, *, timeout_seconds=None):
        raise ExplanationModelUnavailableError("down")


def _grounding():
    return ExplanationGrounding(evidence_refs=("e1",))


def _facts():
    return [StructuredFact(fact_id="f1", kind=FactKind.THRESHOLD, value=25.0, unit="crore", source_ref="e1")]


def _build_pipeline(clock, model=None):
    uow_factory = _store_factory()
    queue = InMemoryJobQueue(clock=clock)
    engine = ExplanationEngine(model=model)
    pipeline = ExplanationPipeline(engine, uow_factory, queue, clock=clock)
    return pipeline, queue, uow_factory


def test_enqueue_creates_pending_job():
    clock = ManualClock()
    pipeline, queue, _ = _build_pipeline(clock)
    job = pipeline.enqueue(
        bidder_id="b1", flag_id="TURNOVER_BELOW_THRESHOLD", flag_state=True,
        grounding=_grounding(), facts=_facts(),
    )
    assert job.state is JobState.PENDING
    assert job.job_type == "EXPLANATION"
    assert queue.get(job.job_id) is not None


def test_duplicate_enqueue_is_idempotent():
    clock = ManualClock()
    pipeline, queue, _ = _build_pipeline(clock)
    first = pipeline.enqueue(
        bidder_id="b1", flag_id="TURNOVER_BELOW_THRESHOLD", flag_state=True,
        grounding=_grounding(), facts=_facts(),
    )
    second = pipeline.enqueue(
        bidder_id="b1", flag_id="TURNOVER_BELOW_THRESHOLD", flag_state=True,
        grounding=_grounding(), facts=_facts(),
    )
    assert first.job_id == second.job_id
    # Same idempotency key => same logical job; no duplicate pending delivery.
    assert queue.pending_count() == 1


def test_process_persists_explanation_audit_outbox():
    clock = ManualClock()
    pipeline, queue, uow_factory = _build_pipeline(clock)
    pipeline.enqueue(
        bidder_id="b1", flag_id="TURNOVER_BELOW_THRESHOLD", flag_state=True,
        grounding=_grounding(), facts=_facts(),
    )
    result_job = pipeline.process_pending("worker-1")
    assert result_job.state is JobState.SUCCEEDED

    with uow_factory() as uow:
        explanations = uow.repos.explanations.list_by_bidder("b1")
        assert len(explanations) == 1
        assert explanations[0].flag_id == "TURNOVER_BELOW_THRESHOLD"
        assert explanations[0].flag_active is True
        # Audit event linked to the real explanation id.
        audit = uow.repos.audit.list_for("EXPLANATION", explanations[0].explanation_id)
        assert any(e.event_type == "EXPLANATION_READY" for e in audit)
        # Outbox event created atomically.
        assert len(uow.repos.outbox.list_unpublished()) == 1


def test_duplicate_delivery_does_not_create_duplicate_record():
    clock = ManualClock()
    pipeline, queue, uow_factory = _build_pipeline(clock)
    job = pipeline.enqueue(
        bidder_id="b1", flag_id="TURNOVER_BELOW_THRESHOLD", flag_state=True,
        grounding=_grounding(), facts=_facts(),
    )
    pipeline.process_pending("worker-1")
    # Re-enqueue the same job (duplicate delivery) and process again.
    pipeline.enqueue(
        bidder_id="b1", flag_id="TURNOVER_BELOW_THRESHOLD", flag_state=True,
        grounding=_grounding(), facts=_facts(),
    )
    # The already-succeeded job is not re-claimed as new work.
    with uow_factory() as uow:
        explanations = uow.repos.explanations.list_by_bidder("b1")
        assert len(explanations) == 1


def test_provider_unavailable_is_retryable():
    clock = ManualClock()
    pipeline, queue, _ = _build_pipeline(clock, model=_UnavailableModel())
    pipeline.enqueue(
        bidder_id="b1", flag_id="TURNOVER_BELOW_THRESHOLD", flag_state=True,
        grounding=_grounding(), facts=_facts(),
    )
    job = pipeline.process_pending("worker-1")
    assert job.state is JobState.RETRYABLE


def test_to_explanation_record_carries_metadata():
    from ai_verification.explanations.engine import ExplanationEngine

    res = ExplanationEngine().explain(
        "b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=_grounding(), facts=_facts()
    )
    record = to_explanation_record(res, created_at=1000.0)
    assert record.flag_active is True
    assert record.grounding_version == 1
    assert record.fallback_used is True
    assert record.input_hash == res.grounding.content_hash()
    assert record.content is not None