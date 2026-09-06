"""End-to-end audit flow tests for the representative provider path.

These tests cover the canonical integration:

    provider.verify(...) -> Verification
        -> GSTRegistrationRule
        -> ComplianceResult (with verification_refs)
        -> ComplianceEngine
        -> EngineResult (with verification_records)

The goal is to verify that, at each stage, the same ``verification_id``
is consistently carried, that ``evidence_id`` and ``document_id`` are
propagated when the rule legitimately knows them, and that the rule
does **not** treat UNAVAILABLE / ERROR as a verified negative.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Capability,
    ComplianceStatus,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules import GSTRegistrationRule
from compliance_engine.verification import MockGSTProvider, VerificationProvider

from ._builders import gst_evidence, gst_requirement


# ---------------------------------------------------------------------------
# Custom providers used in this test module
# ---------------------------------------------------------------------------


class _UnavailableGSTProvider(VerificationProvider):
    """A provider that always reports the source as unavailable."""

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        return Verification(
            verification_id=f"GSTN_MOCK:{identifier}",
            bidder_id=bidder_id,
            capability=Capability.GST,
            source="GSTN_MOCK",
            queried_identifier=identifier,
            status=VerificationStatus.UNAVAILABLE,
            data={},
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


class _ErrorGSTProvider(VerificationProvider):
    """A provider that returns an ERROR status."""

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        return Verification(
            verification_id=f"GSTN_MOCK:{identifier}",
            bidder_id=bidder_id,
            capability=Capability.GST,
            source="GSTN_MOCK",
            queried_identifier=identifier,
            status=VerificationStatus.ERROR,
            data={},
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


class _CustomGSTProvider(VerificationProvider):
    """A user-defined provider, showing that the engine accepts any
    implementation of ``VerificationProvider`` without modification.
    """

    SOURCE = "CUSTOM_GST"
    CAPABILITY = Capability.GST

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        return Verification(
            verification_id=f"{self.SOURCE}:{identifier}",
            bidder_id=bidder_id,
            capability=self.CAPABILITY,
            source=self.SOURCE,
            queried_identifier=identifier,
            status=VerificationStatus.VERIFIED,
            data={"registration_status": "ACTIVE", "legal_name": "CUSTOM CO"},
            retrieved_at=datetime(2026, 6, 1, tzinfo=UTC),
        )


# ---------------------------------------------------------------------------
# 1. Verified GST result -> PASS, verification_id in both layers
# ---------------------------------------------------------------------------


def test_verified_gst_end_to_end_audit_flow() -> None:
    """A verified GST provider result must produce a PASS compliance
    result whose ``verification_refs`` contains the exact
    ``verification_id`` carried into ``EngineResult.verification_records``.
    """
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )

    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )

    assert len(result.compliance_results) == 1
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert len(cr.verification_refs) == 1

    expected_verification_id = "GSTN_MOCK:27AAACI1234F1Z5"
    assert cr.verification_refs == [expected_verification_id]

    # EngineResult.verification_records must contain the exact object
    # the provider returned, identified by its verification_id.
    assert len(result.verification_records) == 1
    v = result.verification_records[0]
    assert isinstance(v, Verification)
    assert v.verification_id == expected_verification_id
    # And it must be the *same* ID that lives in the compliance result.
    assert v.verification_id == cr.verification_refs[0]


# ---------------------------------------------------------------------------
# 2. NOT_FOUND -> UNVERIFIABLE (not PASS, not FAIL)
# ---------------------------------------------------------------------------


def test_not_found_gst_does_not_become_pass() -> None:
    """NOT_FOUND must not be interpreted as a verified negative; the
    rule must map it to UNVERIFIABLE.
    """
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )

    result = engine.run(
        evidence=[gst_evidence(MockGSTProvider.GSTIN_NOT_FOUND)],
        requirements=[gst_requirement()],
    )

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.NOT_FOUND
    # verification_refs must still carry the provider's id so the audit
    # trail is complete.
    assert cr.verification_refs == [
        f"GSTN_MOCK:{MockGSTProvider.GSTIN_NOT_FOUND}"
    ]


# ---------------------------------------------------------------------------
# 3. UNAVAILABLE / ERROR -> UNVERIFIABLE, not a verified negative
# ---------------------------------------------------------------------------


def test_unavailable_provider_does_not_become_pass_or_fail() -> None:
    """UNAVAILABLE must not be treated as a verified negative."""
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: _UnavailableGSTProvider()},
    )

    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.UNAVAILABLE
    # verification_refs still populated, audit trail intact.
    assert cr.verification_refs == [f"GSTN_MOCK:{MockGSTProvider.GSTIN_VERIFIED}"]
    # And EngineResult.verification_records still carries the same id.
    assert [v.verification_id for v in result.verification_records] == cr.verification_refs


def test_error_provider_does_not_become_pass_or_fail() -> None:
    """ERROR must not be treated as a verified negative."""
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: _ErrorGSTProvider()},
    )

    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.UNVERIFIABLE
    assert cr.actual["status"] is VerificationStatus.ERROR
    assert cr.verification_refs == [f"GSTN_MOCK:{MockGSTProvider.GSTIN_VERIFIED}"]


# ---------------------------------------------------------------------------
# 4. Evidence linkage propagation (evidence_id, document_id)
# ---------------------------------------------------------------------------


def test_evidence_id_and_document_id_propagated_to_verification() -> None:
    """When the rule has unambiguous knowledge of the triggering
    Evidence / Document, the resulting Verification must carry
    ``evidence_id`` and ``document_id`` and the same Verification must
    appear in ``EngineResult.verification_records``.
    """
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )

    ev = gst_evidence()
    result = engine.run(evidence=[ev], requirements=[gst_requirement()])

    cr = result.compliance_results[0]
    assert cr.evidence_refs == [ev.evidence_id]

    v = result.verification_records[0]
    assert v.verification_id == cr.verification_refs[0]
    assert v.evidence_id == ev.evidence_id
    assert v.document_id == ev.document_id


def test_provider_audit_fields_not_fabricated_for_unknown_identifiers() -> None:
    """The provider must not invent ``query`` / ``raw_response`` /
    ``latency_ms`` / ``correlation_id`` when it has no genuine source
    for them.
    """
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )

    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )

    v = result.verification_records[0]
    # evidence_id and document_id are supplied by the rule (which knows).
    assert v.evidence_id == "doc-gst-001:gstin"
    assert v.document_id == "doc-gst-001"
    # The provider did not supply these; they must remain None.
    assert v.query is None
    assert v.raw_response is None
    assert v.latency_ms is None
    assert v.correlation_id is None


# ---------------------------------------------------------------------------
# 5. No mismatch between ComplianceResult.verification_refs and
#    EngineResult.verification_records
# ---------------------------------------------------------------------------


def test_compliance_result_and_engine_result_reference_same_object() -> None:
    """Every ``verification_refs`` id on a ComplianceResult must
    correspond to a Verification with that exact id in
    ``EngineResult.verification_records``.
    """
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )

    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )

    record_ids = {v.verification_id for v in result.verification_records}
    for cr in result.compliance_results:
        for ref in cr.verification_refs:
            assert ref in record_ids, (
                f"ComplianceResult {cr.requirement_id} references "
                f"verification_id={ref!r} which is not present in "
                f"EngineResult.verification_records"
            )


def test_missing_evidence_keeps_verification_records_empty() -> None:
    """When the rule short-circuits because there is no GSTIN evidence,
    the engine must not produce any verification_records and the
    compliance result's ``verification_refs`` must be empty.
    """
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: MockGSTProvider()},
    )

    result = engine.run(evidence=[], requirements=[gst_requirement()])

    assert len(result.compliance_results) == 1
    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.MISSING
    assert cr.verification_refs == []
    assert result.verification_records == []


# ---------------------------------------------------------------------------
# 6. Extensibility: a custom VerificationProvider can be dropped in
# ---------------------------------------------------------------------------


def test_engine_accepts_arbitrary_verification_provider_subclass() -> None:
    """The engine must accept any ``VerificationProvider`` subclass for a
    capability; no engine-side changes are required to wire a new
    adapter.
    """
    engine = ComplianceEngine(
        rules={"GST_REGISTRATION_001": GSTRegistrationRule()},
        providers={Capability.GST: _CustomGSTProvider()},
    )

    result = engine.run(
        evidence=[gst_evidence()],
        requirements=[gst_requirement()],
    )

    cr = result.compliance_results[0]
    assert cr.status is ComplianceStatus.PASS
    assert cr.verification_refs == [f"CUSTOM_GST:{MockGSTProvider.GSTIN_VERIFIED}"]
    v = result.verification_records[0]
    assert v.source == "CUSTOM_GST"
    # The rule still knows the evidence so evidence_id/document_id are
    # propagated onto the custom provider's verification object.
    assert v.evidence_id == "doc-gst-001:gstin"
    assert v.document_id == "doc-gst-001"
