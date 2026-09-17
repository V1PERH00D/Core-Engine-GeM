"""Tests for the production-shaped BIS verification adapter."""

from compliance_engine.models import Capability, VerificationStatus
from compliance_engine.verification import BisAdapter
from compliance_engine.verification.transport import (
    InProcessTransport,
    SourceResponseEnvelope,
    TransportError,
)


def _adapter(raw):
    from compliance_engine.verification.transport import StaticTransport

    return BisAdapter(
        StaticTransport(
            {"CM/L-1": SourceResponseEnvelope(status_code=200, raw_response=raw)},
            default_response=SourceResponseEnvelope(status_code=404, raw_response=None),
            query_key=lambda q: q.certificate_number,
        )
    )


def test_verified_certificate_is_verified_and_carries_normalized_data():
    v = _adapter(
        {
            "licence_status": "ACTIVE",
            "certificate_number": "CM/L-1",
            "product_description": "Steel Pipes",
            "scope_of_certification": ["Steel Pipes", "Tubes"],
            "manufacturer": "Acme Pvt Ltd",
            "valid_from": "2024-01-01",
            "valid_until": "2026-12-31",
        }
    ).verify("bidder-1", "CM/L-1")
    assert v.status is VerificationStatus.VERIFIED
    assert v.capability == Capability.BIS
    assert v.source == BisAdapter.SOURCE
    assert v.queried_identifier == "CM/L-1"
    assert v.data["licence_status"] == "ACTIVE"
    assert v.data["scope_of_certification"] == ["Steel Pipes", "Tubes"]
    assert v.transport_status_code == 200
    assert v.raw_response["licence_status"] == "ACTIVE"
    assert v.query["certificate_number"] == "CM/L-1"


def test_not_found_when_no_payload():
    v = _adapter({}).verify("bidder-1", "OTHER")
    assert v.status is VerificationStatus.NOT_FOUND
    assert v.transport_status_code == 404


def test_not_found_when_payload_missing():
    v = _adapter({}).verify("bidder-1", "CM/L-1")
    assert v.status is VerificationStatus.NOT_FOUND


def test_invalid_certificate():
    v = _adapter({"licence_status": "INVALID"}).verify("bidder-1", "CM/L-1")
    assert v.status is VerificationStatus.INVALID


def test_suspended_and_revoked_still_verified_with_status_recorded():
    for status in ("SUSPENDED", "REVOKED", "EXPIRED"):
        v = _adapter({"licence_status": status}).verify("bidder-1", "CM/L-1")
        assert v.status is VerificationStatus.VERIFIED
        assert v.data["licence_status"] == status


def test_unavailable_when_transport_raises():
    class Boom:
        def send_query(self, query):
            raise TransportError("boom")

    v = BisAdapter(Boom()).verify("bidder-1", "CM/L-1")
    assert v.status is VerificationStatus.UNAVAILABLE


def test_unavailable_when_no_transport():
    v = BisAdapter(InProcessTransport()).verify("bidder-1", "CM/L-1")
    assert v.status is VerificationStatus.UNAVAILABLE
    assert v.transport_status_code is None


def test_unique_verification_ids_for_repeated_calls():
    adapter = _adapter({"licence_status": "ACTIVE"})
    a = adapter.verify("bidder-1", "CM/L-1")
    b = adapter.verify("bidder-1", "CM/L-1")
    assert a.verification_id != b.verification_id
    assert a.verification_id.startswith("BIS:CM/L-1:")


def test_query_and_raw_response_preserved():
    raw = {"licence_status": "ACTIVE", "standard": "IS 1234"}
    adapter = _adapter(raw)
    v = adapter.verify("bidder-1", "CM/L-1")
    assert v.query["certificate_number"] == "CM/L-1"
    assert v.raw_response == raw