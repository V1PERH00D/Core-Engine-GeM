"""Persistence-focused tests for the extended explanation record + migration."""

from ai_verification.explanations.engine import ExplanationEngine
from ai_verification.explanations.facts import FactKind, StructuredFact
from ai_verification.explanations.grounding import ExplanationGrounding
from ai_verification.explanations.pipeline import to_explanation_record

from infrastructure.persistence.memory import _Store
from infrastructure.persistence.records import BidderRecord, ExplanationRecord
from infrastructure.persistence.schema import MIGRATIONS
from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork


def test_schema_migration_includes_explanation_metadata_columns():
    sql = "\n".join(m.sql for m in MIGRATIONS)
    for col in (
        "schema_version",
        "grounding_version",
        "validation_status",
        "fallback_used",
        "input_hash",
        "evidence_refs",
        "verification_refs",
        "document_refs",
        "comparison_refs",
        "trace_refs",
        "content",
        "uncertainties",
        "review_actions",
    ):
        assert col in sql


def test_migrations_include_v2():
    assert MIGRATIONS[-1].version == 2
    assert MIGRATIONS[-1].name == "explanation_metadata"


def test_explanation_record_roundtrip_metadata():
    grounding = ExplanationGrounding(evidence_refs=("e1",), finding_refs=("f1",))
    facts = [StructuredFact(fact_id="f1", kind=FactKind.THRESHOLD, value=25.0, unit="crore", source_ref="e1")]
    result = ExplanationEngine().explain("b1", "TURNOVER_BELOW_THRESHOLD", True, grounding=grounding, facts=facts)
    record = to_explanation_record(result, created_at=1.0)

    store = _Store()
    uow = InMemoryUnitOfWork(store)
    with uow:
        uow.repos.bidders.add(BidderRecord(bidder_id="b1", created_at=1.0, updated_at=1.0))
        from infrastructure.persistence.records import FindingRecord

        uow.repos.findings.save(FindingRecord(finding_id="f1", bidder_id="b1", finding_type="V", flag_id="TURNOVER_BELOW_THRESHOLD", created_at=1.0))
        uow.repos.explanations.save(record)

    with uow:
        loaded = uow.repos.explanations.get(record.explanation_id)
    assert loaded is not None
    assert loaded.grounding_version == 1
    assert loaded.validation_status == "VALID"
    assert loaded.fallback_used is True
    assert loaded.input_hash == grounding.content_hash()
    assert loaded.evidence_refs == ["e1"]
    assert loaded.review_actions


def test_explanation_record_idempotent_upsert():
    record = ExplanationRecord(
        explanation_id="x",
        bidder_id="b1",
        flag_id="GSTIN_MISSING",
        flag_active=True,
        concise_text="first",
        created_at=1.0,
    )
    store = _Store()
    uow = InMemoryUnitOfWork(store)
    with uow:
        uow.repos.bidders.add(BidderRecord(bidder_id="b1", created_at=1.0, updated_at=1.0))
        uow.repos.explanations.save(record)
        updated = record.model_copy(update={"concise_text": "second"})
        uow.repos.explanations.save(updated)

    with uow:
        assert len(uow.repos.explanations.list_by_bidder("b1")) == 1
        assert uow.repos.explanations.get("x").concise_text == "second"