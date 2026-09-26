"""Application service: end-to-end compliance runs over in-memory state.

Covers the integration contract items:

1.  clean synthetic bidder -> deterministic boolean flags
2.  failing synthetic bidder -> expected canonical flags
3.  missing evidence -> missing flags (never a silent PASS)
4.  provider unavailable -> UNVERIFIABLE, never a compliance conclusion
5.  cross-document inconsistency
6.  cross-bidder anomaly through the application path
7.  boolean-only snapshot serialization
8.  explanation generation
9.  explanation fallback when the model is unavailable
10. persistence integration (lineage chain persisted in the store)
11. idempotent repeated submission
12. invalid input rejected at the boundary
13. processing failure marks the submission FAILED
15. no severity/risk fields anywhere in the public compliance output
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from compliance_engine.models import Capability, Verification, VerificationStatus
from compliance_engine.rules import Rule
from compliance_engine.verification.base import MockGSTProvider, VerificationProvider

from application.demo import demo_providers, get_scenario
from application.models import BidderSubmission, InvalidSubmissionError
from infrastructure.audit import build_flag_lineage
from infrastructure.errors import ProcessingError, ProviderUnavailableError
from infrastructure.pipeline import ProcessingStage
from tests.application.conftest import gst_requirement, gst_submission, make_service


class _UnavailableGstProvider(VerificationProvider):
    """A verification provider whose source is down."""

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any):
        return Verification(
            verification_id=f"GSTN_TEST_UNAVAILABLE:{identifier}",
            bidder_id=bidder_id,
            capability=Capability.GST,
            source="GSTN_TEST_UNAVAILABLE",
            queried_identifier=identifier,
            status=VerificationStatus.UNAVAILABLE,
            data={},
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


class _BrokenRule(Rule):
    rule_id = "BROKEN_RULE_TEST"
    name = "rule with a programming error"

    def evaluate(self, evidence, *args, requirement=None, provider=None, **kwargs):
        raise TypeError("intentional programming error")


# ---------------------------------------------------------------------------
# 1. Clean synthetic bidder
# ---------------------------------------------------------------------------


def test_clean_bidder_produces_boolean_flags(store, clock):
    service = make_service(store, clock)
    submission = gst_submission(
        "bidder-clean", gstin=MockGSTProvider.GSTIN_VERIFIED
    )

    result = service.process_bid(submission)

    payload = result.compliance_payload()
    assert payload["bidder_id"] == "bidder-clean"
    assert set(payload["flags"].values()) <= {False}
    assert all(isinstance(v, bool) for v in payload["flags"].values())
    assert result.requirements[0].status == "PASS"
    assert result.processing.stage == ProcessingStage.COMPLETE.value


# ---------------------------------------------------------------------------
# 2. Failing bidder -> expected canonical flags
# ---------------------------------------------------------------------------


def test_failing_bidder_sets_expected_flags(store, clock):
    providers = demo_providers(bis_valid=False, debarment="restricted")
    service = make_service(store, clock, providers=providers)
    submission = get_scenario("failing").submission_factory()

    result = service.process_bid(submission)

    set_flags = result.set_flags()
    assert set_flags["BIS_CERTIFICATE_INVALID"] is True
    assert set_flags["LOCAL_CONTENT_BELOW_THRESHOLD"] is True
    assert set_flags["PROCUREMENT_DEBARMENT_ACTIVE"] is True
    assert set_flags["TURNOVER_BELOW_THRESHOLD"] is True
    statuses = {r.requirement_id: r.status for r in result.requirements}
    assert statuses["demo-req-bis"] == "FAIL"
    assert statuses["demo-req-debarment"] == "FAIL"


# ---------------------------------------------------------------------------
# 3. Missing evidence
# ---------------------------------------------------------------------------


def test_missing_evidence_is_flagged_not_silently_compliant(store, clock):
    service = make_service(store, clock)
    submission = gst_submission(
        "bidder-missing", gstin=None, include_evidence=False
    )

    result = service.process_bid(submission)

    assert result.compliance.flags["GSTIN_MISSING"] is True
    assert result.requirements[0].status == "MISSING"


# ---------------------------------------------------------------------------
# 4. Provider unavailable -> UNVERIFIABLE, never a compliance conclusion
# ---------------------------------------------------------------------------


def test_provider_unavailable_is_unverifiable_not_compliant_or_failing(
    store, clock
):
    providers = demo_providers()
    providers[Capability.GST] = _UnavailableGstProvider()
    service = make_service(store, clock, providers=providers)
    submission = gst_submission(
        "bidder-unavailable", gstin=MockGSTProvider.GSTIN_VERIFIED
    )

    result = service.process_bid(submission)

    assert result.requirements[0].status == "UNVERIFIABLE"
    # No GST-related flag may be raised by an unavailable provider.
    for flag_id, value in result.set_flags().items():
        assert not flag_id.startswith("GSTIN")
    assert result.verifications[0].status == "UNAVAILABLE"
    assert result.processing.stage == ProcessingStage.COMPLETE.value


# ---------------------------------------------------------------------------
# 5. Cross-document inconsistency
# ---------------------------------------------------------------------------


def test_cross_document_inconsistency_sets_identity_flag(store, clock):
    service = make_service(store, clock)
    submission = get_scenario("inconsistent").submission_factory()

    result = service.process_bid(submission)

    assert result.compliance.flags["CROSS_DOCUMENT_IDENTITY_MISMATCH"] is True
    identity_findings = [f for f in result.findings if f.finding_type == "IDENTITY"]
    assert any(
        f.flag_id == "CROSS_DOCUMENT_IDENTITY_MISMATCH" for f in identity_findings
    )


# ---------------------------------------------------------------------------
# 6. Cross-bidder anomaly through the application path
# ---------------------------------------------------------------------------


def test_cross_bidder_anomaly_is_persisted_through_service(store, clock):
    from ai_verification.engine import VerificationEngine

    scenario = get_scenario("cross_bidder")
    engine = VerificationEngine(artifact_store=scenario.document_store)
    service = make_service(store, clock, verification_engine=engine)

    result = service.process_bid(scenario.submission_factory())

    assert result.compliance.flags["CROSS_BIDDER_DOCUMENT_REUSED"] is True
    cross = [f for f in result.findings if f.finding_type == "VERIFICATION"]
    assert any(
        f.flag_id == "CROSS_BIDDER_DOCUMENT_REUSED"
        and f.related_bidder_ids == ["demo-bidder-rival-06"]
        for f in cross
    )


# ---------------------------------------------------------------------------
# 7 + 15. Boolean-only serialization, no severity/risk anywhere
# ---------------------------------------------------------------------------


_FORBIDDEN_KEYS = {"severity", "risk", "risk_score", "level", "score"}


def _walk(value, path=""):
    yield path, value
    if isinstance(value, dict):
        for key, val in value.items():
            yield from _walk(val, f"{path}.{key}")
    elif isinstance(value, list):
        for index, val in enumerate(value):
            yield from _walk(val, f"{path}[{index}]")


def test_compliance_payload_is_boolean_only(store, clock):
    service = make_service(store, clock)
    submission = get_scenario("failing").submission_factory()

    result = service.process_bid(submission)
    payload = json.loads(json.dumps(result.compliance_payload()))

    assert set(payload) == {"bidder_id", "flags"}
    assert all(isinstance(v, bool) for v in payload["flags"].values())
    assert any(payload["flags"].values())  # true flags present
    assert not all(payload["flags"].values())  # explicit false defaults present


def test_no_severity_or_risk_fields_anywhere_in_result_json(store, clock):
    service = make_service(store, clock)
    submission = get_scenario("failing").submission_factory()

    result = service.process_bid(submission)
    data = json.loads(json.dumps(result.to_display_dict()))

    compliance_casefold = {k.lower() for k in data["compliance"]}
    assert not compliance_casefold & _FORBIDDEN_KEYS
    for path, value in _walk(data["compliance"]):
        name = path.rsplit(".", 1)[-1].lower()
        assert name not in _FORBIDDEN_KEYS, f"forbidden key at {path}"


# ---------------------------------------------------------------------------
# 8 + 9. Explanation generation and deterministic fallback
# ---------------------------------------------------------------------------


def test_explanations_are_grounded_and_persisted(store, clock):
    service = make_service(store, clock)
    submission = get_scenario("failing").submission_factory()

    result = service.process_bid(submission)

    set_flags = sorted(result.set_flags())
    explained = sorted(e.flag_id for e in result.explanations)
    assert explained == set_flags
    for explanation in result.explanations:
        assert explanation.fallback_used is True  # no LLM configured
        assert explanation.text

    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    with InMemoryUnitOfWork(store) as uow:
        records = uow.repos.explanations.list_by_bidder(
            "demo-bidder-failing-02"
        )
    assert {r.flag_id for r in records} == set(set_flags)
    assert all(r.fallback_used for r in records)
    assert all(r.evidence_refs or r.verification_refs for r in records)


def test_explanation_fallback_when_model_unavailable(store, clock):
    from ai_verification.explanations.engine import ExplanationEngine
    from ai_verification.explanations.provider import (
        ExplanationModel,
        ExplanationModelUnavailableError,
    )

    class _DownModel(ExplanationModel):
        def generate(self, prompt, *, timeout_seconds=None):
            raise ExplanationModelUnavailableError("demo model is down")

    service = make_service(
        store, clock, explanation_engine=ExplanationEngine(model=_DownModel())
    )
    submission = gst_submission("bidder-fallback", gstin=None, include_evidence=False)

    result = service.process_bid(submission)

    # The boolean outcome is untouched by the explanation failure mode.
    assert result.compliance.flags["GSTIN_MISSING"] is True
    failed = [e for e in result.explanations if e.flag_id == "GSTIN_MISSING"]
    assert len(failed) == 1
    assert failed[0].fallback_used is True
    assert "GSTIN" in failed[0].text


# ---------------------------------------------------------------------------
# 10. Persistence chain
# ---------------------------------------------------------------------------


def test_full_persistence_chain_and_lineage(store, clock):
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    service = make_service(store, clock)
    submission = get_scenario("failing").submission_factory()
    result = service.process_bid(submission)
    bidder_id = submission.bidder_id

    with InMemoryUnitOfWork(store) as uow:
        repos = uow.repos
        assert repos.bidders.get(bidder_id) is not None
        submission_record = repos.submissions.get(submission.submission_id)
        assert submission_record is not None
        assert submission_record.stage == ProcessingStage.COMPLETE.value

        documents = repos.documents.list_by_submission(submission.submission_id)
        assert len(documents) == len(submission.documents)
        evidence = repos.evidence.list_by_bidder(bidder_id)
        assert len(evidence) == len(submission.evidence)
        verifications = repos.verifications.list_by_bidder(bidder_id)
        assert verifications  # provider-backed capabilities ran
        results = repos.compliance_results.list_by_bidder(bidder_id)
        assert len(results) == len(submission.requirements)
        findings = repos.findings.list_by_bidder(bidder_id)
        assert findings

        states = repos.flags.list_states(bidder_id)
        assert {s.flag_id for s in states} == set(result.set_flags())
        for state in states:
            assert isinstance(state.is_set, bool)

        snapshots = repos.flags.list_snapshots(bidder_id)
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_id == result.processing.snapshot_id

        explanations = repos.explanations.list_by_bidder(bidder_id)
        assert {e.flag_id for e in explanations} == set(result.set_flags())

        audit_types = {e.event_type for e in repos.audit.list_by_correlation(submission.correlation_id)}
        assert "SUBMISSION_INGESTED" in audit_types
        assert "FLAG_SNAPSHOT_MATERIALIZED" in audit_types

        # BIS is provider-backed: with the default demo providers the
        # failing scenario's certificate is NOT_FOUND, so this flag has
        # full provider provenance (evidence + verification refs).
        lineage = build_flag_lineage(repos, bidder_id, "BIS_CERTIFICATE_NOT_FOUND")
        assert lineage.flag_state is not None and lineage.flag_state.is_set
        assert lineage.findings
        assert lineage.evidence
        assert lineage.verifications
        assert lineage.explanations


# ---------------------------------------------------------------------------
# 11. Idempotent repeated submission
# ---------------------------------------------------------------------------


def test_repeated_submission_is_idempotent(store, clock):
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    service = make_service(store, clock)
    submission = gst_submission(
        "bidder-idem", gstin=MockGSTProvider.GSTIN_VERIFIED
    )

    first = service.process_bid(submission)
    clock.advance(60.0)
    second = service.process_bid(submission)

    # Same durable result, no re-run: identical snapshot reconstructed.
    assert second.processing.snapshot_id == first.processing.snapshot_id
    assert second.compliance == first.compliance

    with InMemoryUnitOfWork(store) as uow:
        evidence = uow.repos.evidence.list_by_bidder("bidder-idem")
        results = uow.repos.compliance_results.list_by_bidder("bidder-idem")
        snapshots = uow.repos.flags.list_snapshots("bidder-idem")
    assert len(evidence) == len(submission.evidence)
    assert len(results) == 1
    assert len(snapshots) == 1


def test_resubmitting_in_flight_submission_is_rejected(store, clock):
    class _BoomRule(Rule):
        rule_id = "BOOM_RULE"
        name = "boom"

        def evaluate(self, evidence, *args, requirement=None, provider=None, **kwargs):
            raise RuntimeError("transient boom")

    from compliance_engine.engine import ComplianceEngine
    from application.service import ComplianceApplicationService
    from application.demo import demo_rules, demo_providers
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    rules = demo_rules()
    rules["BOOM_RULE"] = _BoomRule()
    service = ComplianceApplicationService(
        compliance_engine=ComplianceEngine(rules=rules, providers=demo_providers()),
        uow_factory=lambda: InMemoryUnitOfWork(store),
        clock=clock,
    )
    from compliance_engine.models import Applicability
    from compliance_engine.models import Requirement
    requirement = Requirement(
        requirement_id="req-boom",
        capability="GST",
        description="boom",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        rule_id="BOOM_RULE",
    )
    submission = gst_submission(
        "bidder-inflight",
        gstin=MockGSTProvider.GSTIN_VERIFIED,
        extra_requirements=[requirement],
    )

    with pytest.raises(RuntimeError):
        service.process_bid(submission)

    with pytest.raises(ProcessingError) as exc_info:
        service.process_bid(submission)
    assert "FAILED" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 12. Invalid input
# ---------------------------------------------------------------------------


def test_invalid_submission_is_rejected_at_the_boundary(store, clock):
    service = make_service(store, clock)

    with pytest.raises(InvalidSubmissionError):
        BidderSubmission.validate_or_raise(
            {
                "bidder_id": "b1",
                "submission_id": "s1",
                "documents": [],  # at least one document is required
            }
        )
    with pytest.raises(InvalidSubmissionError) as exc_info:
        BidderSubmission.validate_or_raise(
            {
                "bidder_id": "b1",
                "submission_id": "s1",
                "documents": [
                    {"document_id": "d1", "document_type": "GST"}
                ],
                "evidence": [
                    {
                        "evidence_id": "d1:gstin",
                        "bidder_id": "somebody-else",
                        "document_id": "d1",
                        "document_type": "GST",
                        "field_name": "gstin",
                        "value": "X",
                    }
                ],
            }
        )
    assert exc_info.value.kind.value == "PERMANENT_VALIDATION"

    # Nothing was persisted or executed.
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    with InMemoryUnitOfWork(store) as uow:
        assert uow.repos.submissions.get("s1") is None


# ---------------------------------------------------------------------------
# 13. Processing failure marks the submission FAILED and propagates
# ---------------------------------------------------------------------------


def test_processing_failure_marks_submission_failed(store, clock):
    from compliance_engine.engine import ComplianceEngine
    from application.service import ComplianceApplicationService
    from application.demo import demo_rules, demo_providers
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    rules = demo_rules()
    rules["BROKEN_RULE_TEST"] = _BrokenRule()
    service = ComplianceApplicationService(
        compliance_engine=ComplianceEngine(rules=rules, providers=demo_providers()),
        uow_factory=lambda: InMemoryUnitOfWork(store),
        clock=clock,
    )
    from compliance_engine.models import Applicability, Requirement

    requirement = Requirement(
        requirement_id="req-broken",
        capability="GST",
        description="triggers a programming error",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        rule_id="BROKEN_RULE_TEST",
    )
    submission = gst_submission(
        "bidder-broken",
        gstin=MockGSTProvider.GSTIN_VERIFIED,
        extra_requirements=[requirement],
    )

    with pytest.raises(TypeError):
        service.process_bid(submission)

    with InMemoryUnitOfWork(store) as uow:
        record = uow.repos.submissions.get(submission.submission_id)
    assert record is not None
    assert record.stage == ProcessingStage.FAILED.value
    assert record.last_error_kind == "PROGRAMMING_ERROR"
    assert "intentional programming error" in record.last_error
