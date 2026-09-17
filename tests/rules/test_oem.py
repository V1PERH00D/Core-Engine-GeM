"""Tests for the OEM authorization rule (OEM_AUTHORIZATION_001)."""

from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules import OemAuthorizationRule

Rule = OemAuthorizationRule


def _req(**params):
    return Requirement(
        requirement_id="req-oem-1",
        capability=Capability.OEM_AUTHORIZATION,
        description="OEM authorization required",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        parameters=dict(params),
        rule_id="OEM_AUTHORIZATION_001",
    )


def _ev(field, value):
    return Evidence(
        evidence_id="doc-1:" + field,
        bidder_id="bidder-1",
        document_id="doc-1",
        document_type="OEM_AUTHORIZATION",
        field_name=field,
        value=value,
        confidence=0.98,
    )


def _evidence(**fields):
    return [_ev(k, v) for k, v in fields.items()]


def _run(evidence, params=None):
    return Rule().evaluate(evidence, requirement=_req(**(params or {})))


def test_missing_authorization():
    r = _run([])
    assert r.status is ComplianceStatus.MISSING
    assert r.flags == ["OEM_AUTHORIZATION_NOT_PROVIDED"]


def test_valid_authorization_passes():
    r = _run(_evidence(oem_name="Acme Pvt Ltd", authorization_type="Distributor", authorized_product_range=["Laptops"]))
    assert r.status is ComplianceStatus.PASS
    assert r.flags == []


def test_oem_name_mismatch_fails():
    r = _run(
        _evidence(oem_name="Acme Pvt Ltd"),
        params={"required_oem": "Other Corp"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["OEM_NAME_MISMATCH"]


def test_oem_name_normalized_match():
    r = _run(
        _evidence(oem_name="Acme Pvt. Ltd."),
        params={"required_oem": "ACME PRIVATE LIMITED"},
    )
    assert r.status is ComplianceStatus.PASS


def test_required_bidder_mismatch_fails():
    r = _run(
        _evidence(oem_name="Acme Pvt Ltd", authorized_bidder="Bidder X"),
        params={"required_bidder": "Bidder Y"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["OEM_NAME_MISMATCH"]


def test_authorization_type_mismatch_fails():
    r = _run(
        _evidence(oem_name="Acme", authorization_type="Reseller"),
        params={"required_authorization_type": "Distributor"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["AUTHORIZATION_TYPE_MISMATCH"]


def test_product_range_insufficient_fails():
    r = _run(
        _evidence(oem_name="Acme", authorized_product_range=["Printers"]),
        params={"required_product": "Laptops"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["AUTHORIZED_PRODUCT_RANGE_INSUFFICIENT"]


def test_territory_mismatch_fails():
    r = _run(
        _evidence(oem_name="Acme", authorization_territory="Delhi NCR"),
        params={"required_territory": "Mumbai"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["AUTHORIZATION_TERRITORY_MISMATCH"]


def test_expired_authorization_fails():
    r = _run(
        _evidence(oem_name="Acme", valid_from="2020-01-01", valid_until="2021-01-01"),
        params={"evaluation_date": "2022-01-01"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["OEM_AUTHORIZATION_EXPIRED"]


def test_future_authorization_fails():
    r = _run(
        _evidence(oem_name="Acme", valid_from="2030-01-01", valid_until="2031-01-01"),
        params={"evaluation_date": "2022-01-01"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["OEM_AUTHORIZATION_INVALID"]


def test_malformed_validity_unverifiable():
    r = _run(
        _evidence(oem_name="Acme", valid_from="garbage", valid_until="2031-01-01"),
        params={"evaluation_date": "2022-01-01"},
    )
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == []


def test_require_authorization_false():
    r = _run(_evidence(oem_name="Acme"), params={"require_authorization": False})
    assert r.status is ComplianceStatus.NOT_APPLICABLE


def test_name_similarity_does_not_fail_when_no_oem_param():
    """A bare authorization with no required_oem parameter passes; similarity is not authorization."""
    r = _run(_evidence(oem_name="Acme Pvt Ltd"))
    assert r.status is ComplianceStatus.PASS