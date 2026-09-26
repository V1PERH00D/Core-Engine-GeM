"""Shared fixtures for the application-layer test suite.

Everything runs against the in-memory persistence store and in-memory
job queue: no PostgreSQL, no Redis, no network, no LLM.
"""

from __future__ import annotations

import pytest

from ai_verification.engine import VerificationEngine
from ai_verification.explanations.engine import ExplanationEngine
from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    Capability,
    Evidence,
    Requirement,
)

from application.demo import demo_providers, demo_rules
from application.models import BidderSubmission, SubmissionDocument
from application.service import ComplianceApplicationService
from infrastructure.jobs.queue import InMemoryJobQueue
from infrastructure.persistence.memory import _Store
from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork


class ManualClock:
    """Deterministic, manually advanced clock."""

    def __init__(self, start: float = 1_780_000_000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += seconds


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def store() -> _Store:
    return _Store()


@pytest.fixture
def queue(clock) -> InMemoryJobQueue:
    return InMemoryJobQueue(clock=clock)


def make_service(
    store: _Store,
    clock: ManualClock,
    *,
    providers: dict | None = None,
    verification_engine: VerificationEngine | None = None,
    explanation_engine: ExplanationEngine | None = None,
    queue: InMemoryJobQueue | None = None,
) -> ComplianceApplicationService:
    """Service wired with demo rules/providers over a given store."""
    return ComplianceApplicationService(
        compliance_engine=ComplianceEngine(
            rules=demo_rules(),
            providers=providers if providers is not None else demo_providers(),
        ),
        verification_engine=verification_engine,
        explanation_engine=explanation_engine,
        uow_factory=lambda: InMemoryUnitOfWork(store),
        queue=queue,
        clock=clock,
    )


def _doc(document_id: str, document_type: str) -> SubmissionDocument:
    return SubmissionDocument(
        document_id=document_id,
        document_type=document_type,
        content=f"synthetic test document {document_id}".encode("utf-8"),
    )


def _ev(
    bidder_id: str,
    document_id: str,
    document_type: str,
    field_name: str,
    value,
) -> Evidence:
    return Evidence(
        evidence_id=f"{document_id}:{field_name}",
        bidder_id=bidder_id,
        document_id=document_id,
        document_type=document_type,
        field_name=field_name,
        value=value,
        confidence=0.99,
    )


def gst_requirement() -> Requirement:
    return Requirement(
        requirement_id="req-gst",
        capability=Capability.GST,
        description="GST registration must be valid and active.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        rule_id="GST_REGISTRATION_001",
    )


def gst_submission(
    bidder_id: str,
    *,
    gstin: str | None,
    include_evidence: bool = True,
    extra_requirements: list[Requirement] | None = None,
) -> BidderSubmission:
    """Minimal one-capability submission for targeted service tests."""
    documents = [_doc(f"doc:{bidder_id}:gst", "GST")]
    evidence = []
    if include_evidence:
        evidence = [
            _ev(bidder_id, f"doc:{bidder_id}:gst", "GST", "gstin", gstin)
        ]
    return BidderSubmission(
        bidder_id=bidder_id,
        submission_id=f"sub:{bidder_id}",
        documents=documents,
        evidence=evidence,
        requirements=[gst_requirement()] + list(extra_requirements or []),
        correlation_id=f"corr:{bidder_id}",
    )
