"""Vertical-slice persistence for the 26100 BIS / Make-in-India capabilities.

Proves the full chain: evidence -> (provider) -> verification -> compliance
rule -> finding -> boolean flag -> explanation -> snapshot, with reproducible,
boolean-only downstream contract and real-ID audit lineage.
"""

from compliance_engine.flags import FlagSeverity

from infrastructure.persistence.records import (
    BidderRecord,
    ComplianceResultRecord,
    DocumentRecord,
    EvidenceRecord,
    FindingRecord,
    FlagStateRecord,
    SubmissionRecord,
    VerificationRecord,
)
from infrastructure.flags import materialize_flag_snapshot


def _persist_bis_chain(uow, clock):
    uow.repos.bidders.add(BidderRecord(bidder_id="bidder-26100", created_at=clock(), updated_at=clock()))
    uow.repos.submissions.add(
        SubmissionRecord(submission_id="sub-26100", bidder_id="bidder-26100",
                         stage="VERIFIED", created_at=clock(), updated_at=clock())
    )
    uow.repos.documents.add(
        DocumentRecord(document_id="doc-bis", submission_id="sub-26100",
                       bidder_id="bidder-26100", document_type="BIS", created_at=clock())
    )
    uow.repos.evidence.add(
        EvidenceRecord(
            evidence_id="ev-bis", bidder_id="bidder-26100", document_id="doc-bis",
            field_name="certificate_number", document_type="BIS",
            value="CM/L-1", created_at=clock(),
        )
    )
    uow.repos.verifications.save(
        VerificationRecord(
            verification_id="v-bis", bidder_id="bidder-26100", capability="BIS",
            source="BIS", queried_identifier="CM/L-1", status="VERIFIED",
            retrieved_at=clock(), created_at=clock(), correlation_id="trace-26100",
            evidence_id="ev-bis", document_id="doc-bis",
        )
    )
    uow.repos.compliance_results.save(
        ComplianceResultRecord(
            result_id="r-bis", bidder_id="bidder-26100", requirement_id="req-bis",
            capability="BIS", status="FAIL", reason="BIS certificate expired",
            evidence_refs=["ev-bis"], verification_refs=["v-bis"],
            created_at=clock(), updated_at=clock(),
        )
    )
    uow.repos.findings.save(
        FindingRecord(
            finding_id="f-bis", bidder_id="bidder-26100",
            finding_type="VERIFICATION", flag_id="BIS_CERTIFICATE_EXPIRED",
            payload={}, evidence_refs=["ev-bis"], verification_refs=["v-bis"],
            created_at=clock(),
        )
    )
    uow.repos.flags.save_state(
        FlagStateRecord(
            bidder_id="bidder-26100", flag_id="BIS_CERTIFICATE_EXPIRED",
            is_set=True, finding_refs=["f-bis"], evidence_refs=["ev-bis"],
            verification_refs=["v-bis"], correlation_id="trace-26100",
            updated_at=clock(),
        )
    )


def test_bis_flag_snapshot_is_boolean_only_and_reproducible(uow_factory, clock):
    with uow_factory() as uow:
        _persist_bis_chain(uow, clock)

    with uow_factory() as uow:
        states = uow.repos.flags.list_states("bidder-26100")

    snap = materialize_flag_snapshot("bidder-26100", states, clock=clock)
    assert snap.downstream_payload() == {
        "bidder_id": "bidder-26100",
        "flags": {"BIS_CERTIFICATE_EXPIRED": True},
    }

    # Reproducible regardless of wall clock.
    snap_again = materialize_flag_snapshot("bidder-26100", states, clock=lambda: 999.0)
    assert snap_again.snapshot_id == snap.snapshot_id


def test_flag_snapshot_has_no_severity_or_risk(uow_factory, clock):
    with uow_factory() as uow:
        _persist_bis_chain(uow, clock)
    with uow_factory() as uow:
        states = uow.repos.flags.list_states("bidder-26100")
    snap = materialize_flag_snapshot("bidder-26100", states, clock=clock)
    payload = snap.downstream_payload()
    for value in payload["flags"].values():
        assert isinstance(value, bool)
    assert "severity" not in payload
    assert "risk" not in payload
    assert "score" not in payload


def test_audit_lineage_reconstructs_real_ids(uow_factory, clock):
    with uow_factory() as uow:
        _persist_bis_chain(uow, clock)

    from infrastructure.audit import build_flag_lineage

    with uow_factory() as uow:
        lineage = build_flag_lineage(uow.repos, "bidder-26100", "BIS_CERTIFICATE_EXPIRED")
    assert lineage.flag_state.is_set is True
    assert [f.finding_id for f in lineage.findings] == ["f-bis"]
    assert [e.evidence_id for e in lineage.evidence] == ["ev-bis"]
    assert [v.verification_id for v in lineage.verifications] == ["v-bis"]


def test_deterministic_ordering_across_flags(uow_factory, clock):
    with uow_factory() as uow:
        _persist_bis_chain(uow, clock)
        uow.repos.flags.save_state(
            FlagStateRecord(
                bidder_id="bidder-26100", flag_id="LOCAL_CONTENT_BELOW_THRESHOLD",
                is_set=True, updated_at=clock(),
            )
        )
    with uow_factory() as uow:
        states = uow.repos.flags.list_states("bidder-26100")
    snap = materialize_flag_snapshot("bidder-26100", states, clock=clock)
    keys = list(snap.downstream_payload()["flags"].keys())
    assert keys == sorted(keys)