"""Tests for the DigiLocker document verification rule (DIGILOCKER_VERIFICATION_001)."""

import json
from datetime import datetime, timezone

from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules import DigiLockerVerificationRule

Rule = DigiLockerVerificationRule


def _req(**params):
    return Requirement(
        requirement_id="req-dl-1",
        capability=Capability.DIGILOCKER,
        description="digital document verification",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        parameters=dict(params),
        rule_id="DIGILOCKER_VERIFICATION_001",
    )


def _evidence(value="DOC-1", field="document_access_id"):
    return Evidence(
        evidence_id="doc-1:" + field,
        bidder_id="bidder-1",
        document_id="doc-1",
        document_type="DIGILOCKER",
        field_name=field,
        value=value,
        confidence=0.99,
    )


def _verification(status, data=None):
    return Verification(
        verification_id="DIGILOCKER:DOC-1:call",
        bidder_id="bidder-1",
        capability=Capability.DIGILOCKER,
        source="DIGILOCKER",
        queried_identifier="DOC-1",
        status=status,
        data=data or {},
        retrieved_at=datetime.now(timezone.utc),
    )


class _Provider:
    def __init__(self, verification):
        self.verification = verification

    def verify(self, bidder_id, identifier, **kwargs):
        return self.verification


def _run(evidence, verification, params=None):
    return Rule().evaluate(evidence, _Provider(verification), _req(**(params or {})))


def test_verified_document_passes():
    r = _run([_evidence()], _verification(VerificationStatus.VERIFIED, {"issuer": "DGFT", "document_type": "IEC"}))
    assert r.status is ComplianceStatus.PASS
    assert r.flags == []
    assert r.verification_refs == ["DIGILOCKER:DOC-1:call"]


def test_missing_evidence():
    r = Rule().evaluate([], _Provider(_verification(VerificationStatus.VERIFIED)), _req())
    assert r.status is ComplianceStatus.MISSING
    assert r.flags == ["REQUIRED_FIELD_MISSING"]


def test_not_found_unverifiable():
    r = _run([_evidence()], _verification(VerificationStatus.NOT_FOUND))
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["DIGITAL_DOCUMENT_NOT_FOUND"]


def test_unavailable_unverifiable_not_fail():
    r = _run([_evidence()], _verification(VerificationStatus.UNAVAILABLE))
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["DIGILOCKER_VERIFICATION_UNAVAILABLE"]


def test_signature_invalid_fails():
    r = _run([_evidence()], _verification(VerificationStatus.INVALID, {"verification_result": "SIGNATURE_INVALID"}))
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["DIGITAL_DOCUMENT_SIGNATURE_INVALID"]


def test_hash_mismatch_flag():
    r = _run([_evidence()], _verification(VerificationStatus.INVALID, {"verification_result": "HASH_MISMATCH"}))
    assert r.flags == ["DIGITAL_DOCUMENT_HASH_MISMATCH"]


def test_revoked_flag():
    r = _run([_evidence()], _verification(VerificationStatus.INVALID, {"verification_result": "REVOKED"}))
    assert r.flags == ["DIGITAL_DOCUMENT_REVOKED"]


def test_expired_flag():
    r = _run([_evidence()], _verification(VerificationStatus.INVALID, {"verification_result": "EXPIRED"}))
    assert r.flags == ["DIGITAL_DOCUMENT_EXPIRED"]


def test_issuer_not_recognized_flag():
    r = _run([_evidence()], _verification(VerificationStatus.INVALID, {"verification_result": "ISSUER_NOT_RECOGNIZED"}))
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["ISSUING_AUTHORITY_NOT_RECOGNIZED"]


def test_issuer_mismatch_fails():
    r = _run(
        [_evidence()],
        _verification(VerificationStatus.VERIFIED, {"issuer": "DGFT", "document_type": "IEC"}),
        params={"required_issuer": "MCA"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["ISSUING_AUTHORITY_INVALID"]


def test_document_type_mismatch_fails():
    r = _run(
        [_evidence()],
        _verification(VerificationStatus.VERIFIED, {"issuer": "DGFT", "document_type": "IEC"}),
        params={"required_document_type": "GST_CERT"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == []


def test_document_hash_mismatch_fails():
    r = _run(
        [_evidence(), _evidence("differenthash", field="document_hash")],
        _verification(VerificationStatus.VERIFIED, {"document_hash": "sourcehash"}),
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["DIGITAL_DOCUMENT_HASH_MISMATCH"]


def test_no_sensitive_data_in_result():
    r = _run([_evidence()], _verification(VerificationStatus.VERIFIED, {"issuer": "DGFT"}))
    assert "aadhaar" not in json.dumps(r.actual)