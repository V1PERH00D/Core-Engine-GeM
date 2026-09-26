"""Tests for the Make-in-India / local content rule (MAKE_IN_INDIA_001)."""

import pytest

from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules import MakeInIndiaRule

Rule = MakeInIndiaRule


def _req(**params):
    return Requirement(
        requirement_id="req-mii-1",
        capability=Capability.MAKE_IN_INDIA,
        description="local content",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        parameters=dict(params),
        rule_id="MAKE_IN_INDIA_001",
    )


def _ev(field, value):
    return Evidence(
        evidence_id="doc-1:" + field,
        bidder_id="bidder-1",
        document_id="doc-1",
        document_type="MAKE_IN_INDIA",
        field_name=field,
        value=value,
        confidence=0.97,
    )


def _pct(value):
    return [_ev("local_content_percentage", value)]


def _run(evidence, params=None):
    return Rule().evaluate(evidence, requirement=_req(**(params or {})))


def test_threshold_pass():
    r = _run(_pct(70.0), params={"minimum_local_content_percentage": 60.0})
    assert r.status is ComplianceStatus.PASS
    assert r.flags == []


def test_threshold_fail():
    r = _run(_pct(50.0), params={"minimum_local_content_percentage": 60.0})
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["LOCAL_CONTENT_BELOW_THRESHOLD"]


@pytest.mark.parametrize(
    "operator,value,threshold,expected",
    [
        (">=", 60.0, 60.0, True),
        (">", 60.0, 60.0, False),
        ("=", 60.0, 60.0, True),
        ("<=", 60.0, 60.0, True),
        ("<", 60.0, 60.0, False),
    ],
)
def test_all_operators(operator, value, threshold, expected):
    r = _run(
        _pct(value),
        params={
            "minimum_local_content_percentage": threshold,
            "local_content_operator": operator,
        },
    )
    assert (r.status is ComplianceStatus.PASS) is expected


def test_missing_evidence():
    r = _run([])
    assert r.status is ComplianceStatus.MISSING
    assert r.flags == ["LOCAL_CONTENT_EVIDENCE_MISSING"]


def test_malformed_percentage_unverifiable():
    r = _run(_pct("seventy"))
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == []


def test_numeric_string_percentage_accepted():
    r = _run(_pct("65"), params={"minimum_local_content_percentage": 60.0})
    assert r.status is ComplianceStatus.PASS


def test_inconsistent_evidence_flag():
    r = _run([_ev("local_content_percentage", 50.0), _ev("local_content_percentage", 60.0)])
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == ["LOCAL_CONTENT_CLAIM_INCONSISTENT"]


def test_no_universal_threshold():
    r = _run(_pct(50.0))
    assert r.status is ComplianceStatus.NOT_CHECKED
    assert r.flags == []


def test_country_of_origin_mismatch_fails():
    r = _run(
        [_ev("local_content_percentage", 70.0), _ev("country_of_origin", "China")],
        params={"required_country_of_origin": "India"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["SOURCING_LOCATION_MISMATCH"]


def test_manufacturing_location_mismatch_fails():
    r = _run(
        [_ev("local_content_percentage", 70.0), _ev("manufacturing_location", "Pune")],
        params={"required_manufacturing_location": "Chennai"},
    )
    assert r.status is ComplianceStatus.FAIL
    assert r.flags == ["MANUFACTURING_LOCATION_INELIGIBLE"]


def test_required_certificate_missing():
    r = _run(
        _pct(70.0),
        params={"required_certificate": "local_sourcing_certificate"},
    )
    assert r.status is ComplianceStatus.MISSING
    assert r.flags == ["LOCAL_CONTENT_EVIDENCE_MISSING"]


def test_required_certificate_present():
    r = _run(
        [
            _ev("local_content_percentage", 70.0),
            _ev("local_sourcing_certificate", "CERT-1"),
        ],
        params={"required_certificate": "local_sourcing_certificate", "minimum_local_content_percentage": 60.0},
    )
    assert r.status is ComplianceStatus.PASS


def test_unsupported_operator_unverifiable():
    r = _run(
        _pct(70.0),
        params={"minimum_local_content_percentage": 60.0, "local_content_operator": "~"},
    )
    assert r.status is ComplianceStatus.UNVERIFIABLE
    assert r.flags == []


def test_indian_company_name_does_not_imply_origin():
    """No country-of-origin requirement present -> no origin inference."""
    r = _run(
        [_ev("local_content_percentage", 70.0), _ev("manufacturing_location", "India")],
        params={"minimum_local_content_percentage": 60.0},
    )
    assert r.status is ComplianceStatus.PASS