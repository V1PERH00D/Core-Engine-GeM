"""Boolean flag snapshot materialization."""

import pytest

from compliance_engine.flags import UnknownFlagError

from infrastructure.flags import BidderFlagSnapshot, materialize_flag_snapshot
from infrastructure.persistence.records import FlagStateRecord


def _state(flag_id, is_set=True, **kw):
    return FlagStateRecord(
        bidder_id="b1", flag_id=flag_id, is_set=is_set, updated_at=1.0, **kw
    )


def test_downstream_payload_shape():
    snap = materialize_flag_snapshot(
        "b1", [_state("GSTIN_MISSING", True)], clock=lambda: 1.0
    )
    payload = snap.downstream_payload()
    assert payload == {"bidder_id": "b1", "flags": {"GSTIN_MISSING": True}}


def test_boolean_only_no_severity_or_risk():
    snap = materialize_flag_snapshot(
        "b1", [_state("GSTIN_MISSING", True)], clock=lambda: 1.0
    )
    payload = snap.downstream_payload()
    assert set(payload.keys()) == {"bidder_id", "flags"}
    for value in payload["flags"].values():
        assert isinstance(value, bool)


def test_deterministic_ordering():
    snap = materialize_flag_snapshot(
        "b1",
        [_state("RISK_LEVEL_HIGH", True), _state("ADDRESS_MISMATCH", True)],
        clock=lambda: 1.0,
    )
    keys = list(snap.downstream_payload()["flags"].keys())
    assert keys == sorted(keys)


def test_snapshot_reproducible():
    a = materialize_flag_snapshot(
        "b1", [_state("GSTIN_MISSING", True)], clock=lambda: 1.0
    )
    b = materialize_flag_snapshot(
        "b1", [_state("GSTIN_MISSING", True)], clock=lambda: 999.0
    )
    assert a.snapshot_id == b.snapshot_id
    assert a.content_hash == b.content_hash


def test_unknown_flag_rejected():
    with pytest.raises(UnknownFlagError):
        materialize_flag_snapshot("b1", [_state("NOT_A_REAL_FLAG", True)])


def test_known_flags_absent_default_false():
    snap = materialize_flag_snapshot(
        "b1",
        [_state("GSTIN_MISSING", True)],
        known_flag_ids=["GSTIN_MISSING", "ADDRESS_MISMATCH"],
        clock=lambda: 1.0,
    )
    assert snap.flags["ADDRESS_MISMATCH"] is False
    assert snap.flags["GSTIN_MISSING"] is True


def test_duplicate_state_last_wins():
    snap = materialize_flag_snapshot(
        "b1",
        [_state("GSTIN_MISSING", True), _state("GSTIN_MISSING", False)],
        clock=lambda: 1.0,
    )
    assert snap.flags["GSTIN_MISSING"] is False


def test_provenance_retained_internally():
    snap = materialize_flag_snapshot(
        "b1",
        [_state("GSTIN_MISSING", True, finding_refs=["f1"], source="COMPLIANCE")],
        clock=lambda: 1.0,
    )
    provenance = snap.provenance["GSTIN_MISSING"]
    assert provenance["finding_refs"] == ["f1"]
    assert provenance["source"] == "COMPLIANCE"
    assert "provenance" not in snap.downstream_payload()


def test_flag_value_must_be_boolean():
    # A non-coercible value is rejected (int 0/1 would silently coerce).
    with pytest.raises(ValueError):
        BidderFlagSnapshot(
            snapshot_id="s", bidder_id="b1", snapshot_version=1,
            flags={"GSTIN_MISSING": "MEDIUM"}, content_hash="x", created_at=1.0,
        )