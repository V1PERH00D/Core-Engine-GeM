"""Tests for the production-shaped DigiLocker document adapter."""

from compliance_engine.models import Capability, VerificationStatus
from compliance_engine.verification import DigiLockerAdapter
from compliance_engine.verification.transport import (
    InProcessTransport,
    SourceResponseEnvelope,
    StaticTransport,
    TransportError,
)


def _adapter(raw):
    return DigiLockerAdapter(
        StaticTransport(
            {"DOC-1": SourceResponseEnvelope(status_code=200, raw_response=raw)},
            default_response=SourceResponseEnvelope(status_code=404, raw_response=None),
            query_key=lambda q: q.document_access_id,
        )
    )


def test_verified_document():
    v = _adapter(
        {
            "verification_result": "VALID",
            "document_access_id": "DOC-1",
            "document_type": "IEC",
            "issuer": "DGFT",
            "document_hash": "abc123",
            "issued_on": "2023-06-01",
        }
    ).verify("bidder-1", "DOC-1")
    assert v.status is VerificationStatus.VERIFIED
    assert v.capability == Capability.DIGILOCKER
    assert v.data["issuer"] == "DGFT"
    assert v.data["document_hash"] == "abc123"
    assert v.transport_status_code == 200


def test_not_found():
    v = _adapter({}).verify("bidder-1", "DOC-1")
    assert v.status is VerificationStatus.NOT_FOUND


def test_invalid_document_signature():
    v = _adapter({"verification_result": "SIGNATURE_INVALID"}).verify("bidder-1", "DOC-1")
    assert v.status is VerificationStatus.INVALID
    assert v.data["verification_result"] == "SIGNATURE_INVALID"


def test_issuer_not_recognized_is_invalid_and_carries_detail():
    v = _adapter({"verification_result": "ISSUER_NOT_RECOGNIZED"}).verify("bidder-1", "DOC-1")
    assert v.status is VerificationStatus.INVALID
    assert v.data["verification_result"] == "ISSUER_NOT_RECOGNIZED"


def test_no_sensitive_identifiers_stored():
    """DigiLocker adapter must not fabricate personal identifier fields."""
    v = _adapter({"verification_result": "VALID", "issuer": "DGFT"}).verify("bidder-1", "DOC-1")
    assert "aadhaar" not in v.data
    assert "pan" not in v.data


def test_unavailable_when_transport_raises():
    class Boom:
        def send_query(self, query):
            raise TransportError("boom")

    assert DigiLockerAdapter(Boom()).verify("bidder-1", "DOC-1").status is VerificationStatus.UNAVAILABLE


def test_unavailable_when_no_transport():
    assert (
        DigiLockerAdapter(InProcessTransport()).verify("bidder-1", "DOC-1").status
        is VerificationStatus.UNAVAILABLE
    )


def test_unique_verification_ids():
    adapter = _adapter({"verification_result": "VALID"})
    a = adapter.verify("bidder-1", "DOC-1")
    b = adapter.verify("bidder-1", "DOC-1")
    assert a.verification_id != b.verification_id
    assert a.verification_id.startswith("DIGILOCKER:DOC-1:")


def test_query_and_raw_response_preserved():
    raw = {"verification_result": "VALID", "document_type": "IEC"}
    v = _adapter(raw).verify("bidder-1", "DOC-1")
    assert v.query["document_access_id"] == "DOC-1"
    assert v.raw_response == raw