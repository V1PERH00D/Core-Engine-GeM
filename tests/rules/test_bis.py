"""Tests for the BIS product certification rule (BIS_CERTIFICATION_001)."""

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
from compliance_engine.rules import BisCertificationRule

Rule = BisCertificationRule


def _req(**params):
    return Requirement(
        requirement_id="req-bis-1",
        capability=Capability.BIS,
        description="BIS certification required",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="ACTIVE",
        parameters=dict(params),
        rule_id="BIS_CERTIFICATION_001",
    )


def _evidence(value="CM/L-1"):
    return Evidence(
        evidence_id="doc-1:certificate_number",
        bidder_id="bidder-1",
        document_id="doc-1",
        document_type="BIS",
        field_name="certificate_number",
        value=value,
        confidence=0.99,
    )


def _verification(status, data=None):
    return Verification(
        verification_id="BIS:CM/L-1:call",
        bidder_id="bidder-1",
        capability=Capability.BIS,
        source="BIS",
        queried_identifier="CM/L-1",
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
    return Rule().evaluate([evidence], _Provider(verification), _req(**(params or {})))


def test_verified_certificate_passes():
    r = _run(_evidence(), _verification(VerificationStatus.VERIFIED, {"licence_status": "ACTIVE"}))
    assert r.status is ComplianceStatus.PASS
    assert r.flags == []
    assert r.evidence_refs == ["doc-1:certificate_number"]
    assert r.verification_refs == ["BIS:CM/L-1:call"]


def test_missing_certificate_is_missing():
    r = Rule().evaluate([], _Provider(_verification(VerificationStatus.VERIFIED)), _req())
    assert r.status is ComplianceStatus.MISSING
    assert r.flags == ["REQUIRED_FIELD_MISSING"]


def test_null_certificate_is_missing():
    r = _run(_evidence(None), _verification(VerificationStatus.VERIFIED))
    assert r.status is ComplianceStatus.MISSING
    assert r.flags == ["REQUIRED_FIELD_MISSING"]


def test_invalid_certificate_fails():
    r = _run(_evidence(), _verification(VerificationStatus.INVALID))
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["BIS_CERTIFICATE_INVALID"]


def test_not_found_unverifiable():
    r = _run(_evidence(), _verification(VerificationStatus.NOT_FOUND))
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["BIS_CERTIFICATE_NOT_FOUND"]


def test_unavailable_unverifiable_not_fail():
    r = _run(_evidence(), _verification(VerificationStatus.UNAVAILABLE))
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["BIS_VERIFICATION_UNAVAILABLE"]


def test_error_unverifiable_not_fail():
    r = _run(_evidence(), _verification(VerificationStatus.ERROR))
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["BIS_VERIFICATION_UNAVAILABLE"]


def test_suspended_revoked_fails():
    for status in ("SUSPENDED", "REVOKED"):
        r = _run(_evidence(), _verification(VerificationStatus.VERIFIED, {"licence_status": status}))
        assert r.status is ComplianceStatus.FAIL
        assert r.flags == ["BIS_CERTIFICATE_SUSPENDED_REVOKED"]


def test_status_mismatch_fails():
    r = _run(
        _evidence(),
        _verification(VerificationStatus.VERIFIED, {"licence_status": "ACTIVE"}),
        params={"required_status": "INACTIVE"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["BIS_CERTIFICATE_INVALID"]


def test_status_match_case_insensitive_passes():
    r = _run(
        _evidence(),
        _verification(VerificationStatus.VERIFIED, {"licence_status": "ACTIVE"}),
        params={"required_status": "active"},
    )
    assert r.status is ComplianceStatus.PASS


def test_product_scope_mismatch_fails():
    r = _run(
        _evidence(),
        _verification(VerificationStatus.VERIFIED, {"licence_status": "ACTIVE", "product_description": "Steel Pipes"}),
        params={"required_product": "Electrical Cables"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["BIS_PRODUCT_SCOPE_MISMATCH"]


def test_product_scope_covered_passes():
    r = _run(
        _evidence(),
        _verification(VerificationStatus.VERIFIED, {"licence_status": "ACTIVE", "scope_of_certification": ["Steel Pipes", "Tubes"]}),
        params={"required_product": "steel pipes"},
    )
    assert r.status is ComplianceStatus.PASS


def test_manufacturer_mismatch_fails_without_flag():
    r = _run(
        _evidence(),
        _verification(VerificationStatus.VERIFIED, {"licence_status": "ACTIVE", "manufacturer": "Acme Pvt Ltd"}),
        params={"required_manufacturer": "Other Ltd"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == []


def test_manufacturer_normalized_match_passes():
    r = _run(
        _evidence(),
        _verification(VerificationStatus.VERIFIED, {"licence_status": "ACTIVE", "manufacturer": "Acme Pvt. Ltd."}),
        params={"required_manufacturer": "ACME PRIVATE LIMITED"},
    )
    assert r.status is ComplianceStatus.PASS


def test_standard_mismatch_fails():
    r = _run(
        _evidence(),
        _verification(VerificationStatus.VERIFIED, {"licence_status": "ACTIVE", "standard": "IS 1234"}),
        params={"required_standard": "IS 9999"},
    )
    assert r.status is ComplianceStatus.FAIL


def test_facility_location_mismatch_fails():
    r = _run(
        _evidence(),
        _verification(VerificationStatus.VERIFIED, {"licence_status": "ACTIVE", "manufacturing_location": "Pune"}),
        params={"required_facility_location": "Chennai"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["BIS_FACILITY_LOCATION_INELIGIBLE"]


def test_expired_certificate_fails():
    r = _run(
        _evidence(),
        _verification(
            VerificationStatus.VERIFIED,
            {"licence_status": "ACTIVE", "valid_from": "2020-01-01", "valid_until": "2021-01-01"},
        ),
        params={"evaluation_date": "2022-01-01"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["BIS_CERTIFICATE_EXPIRED"]


def test_future_certificate_fails():
    r = _run(
        _evidence(),
        _verification(
            VerificationStatus.VERIFIED,
            {"licence_status": "ACTIVE", "valid_from": "2030-01-01", "valid_until": "2031-01-01"},
        ),
        params={"evaluation_date": "2022-01-01"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["BIS_CERTIFICATE_INVALID"]


def test_valid_window_passes():
    r = _run(
        _evidence(),
        _verification(
            VerificationStatus.VERIFIED,
            {"licence_status": "ACTIVE", "valid_from": "2020-01-01", "valid_until": "2030-01-01"},
        ),
        params={"evaluation_date": "2022-01-01"},
    )
    assert r.status is ComplianceStatus.PASS


def test_malformed_dates_unverifiable():
    r = _run(
        _evidence(),
        _verification(
            VerificationStatus.VERIFIED,
            {"licence_status": "ACTIVE", "valid_from": "not-a-date", "valid_until": "2030-01-01"},
        ),
        params={"evaluation_date": "2022-01-01"},
    )
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == []


def test_require_bis_false_not_applicable():
    r = _run(_evidence(), _verification(VerificationStatus.VERIFIED), params={"require_bis": False})
    assert r.status is ComplianceStatus.NOT_APPLICABLE


def test_extra_parameter_rejected():
    import pytest
    from pydantic import ValidationError

    req = _req()
    req = req.model_copy(update={"parameters": {"required_product": "x", "bogus_param": "y"}})
    with pytest.raises(ValidationError):
        Rule().evaluate([_evidence()], _Provider(_verification(VerificationStatus.VERIFIED)), req)