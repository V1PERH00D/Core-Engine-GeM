"""Engine-level dispatch for the four new capabilities."""

from datetime import datetime, timezone

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    Capability,
    ComplianceStatus,
    Evidence,
    Requirement,
)
from compliance_engine.rules import (
    BisCertificationRule,
    DigiLockerVerificationRule,
    MakeInIndiaRule,
    OemAuthorizationRule,
)
from compliance_engine.verification import BisAdapter, DigiLockerAdapter
from compliance_engine.verification.transport import SourceResponseEnvelope, StaticTransport


def _bis_provider():
    return BisAdapter(
        StaticTransport(
            {"CM/L-1": SourceResponseEnvelope(status_code=200, raw_response={"licence_status": "ACTIVE"})},
            query_key=lambda q: q.certificate_number,
        )
    )


def _dl_provider():
    return DigiLockerAdapter(
        StaticTransport(
            {"DOC-1": SourceResponseEnvelope(status_code=200, raw_response={"verification_result": "VALID", "issuer": "DGFT"})},
            query_key=lambda q: q.document_access_id,
        )
    )


def _bis_evidence():
    return Evidence(
        evidence_id="e-bis", bidder_id="b-1", document_id="d-bis",
        document_type="BIS", field_name="certificate_number", value="CM/L-1",
    )


def _dl_evidence():
    return Evidence(
        evidence_id="e-dl", bidder_id="b-1", document_id="d-dl",
        document_type="DIGILOCKER", field_name="document_access_id", value="DOC-1",
    )


def _oem_evidence():
    return Evidence(
        evidence_id="e-oem", bidder_id="b-1", document_id="d-oem",
        document_type="OEM_AUTHORIZATION", field_name="oem_name", value="Acme Pvt Ltd",
    )


def _mii_evidence():
    return Evidence(
        evidence_id="e-mii", bidder_id="b-1", document_id="d-mii",
        document_type="MAKE_IN_INDIA", field_name="local_content_percentage", value=70.0,
    )


def _req(rid, capability, rule_id, **params):
    return Requirement(
        requirement_id=rid, capability=capability, description=rid,
        mandatory=True, applicability=Applicability.APPLICABLE,
        parameters=dict(params), rule_id=rule_id,
    )


def test_engine_dispatches_all_four_capabilities():
    engine = ComplianceEngine(
        rules={
            "BIS_CERTIFICATION_001": BisCertificationRule(),
            "DIGILOCKER_VERIFICATION_001": DigiLockerVerificationRule(),
            "OEM_AUTHORIZATION_001": OemAuthorizationRule(),
            "MAKE_IN_INDIA_001": MakeInIndiaRule(),
        },
        providers={Capability.BIS: _bis_provider(), Capability.DIGILOCKER: _dl_provider()},
    )
    evidence = [_bis_evidence(), _dl_evidence(), _oem_evidence(), _mii_evidence()]
    requirements = [
        _req("r-bis", Capability.BIS, "BIS_CERTIFICATION_001"),
        _req("r-dl", Capability.DIGILOCKER, "DIGILOCKER_VERIFICATION_001"),
        _req("r-oem", Capability.OEM_AUTHORIZATION, "OEM_AUTHORIZATION_001", required_oem="Acme Pvt Ltd"),
        _req("r-mii", Capability.MAKE_IN_INDIA, "MAKE_IN_INDIA_001", minimum_local_content_percentage=60.0),
    ]
    result = engine.run(evidence, requirements)
    statuses = {r.requirement_id: r.status for r in result.compliance_results}
    assert statuses["r-bis"] is ComplianceStatus.PASS
    assert statuses["r-dl"] is ComplianceStatus.PASS
    assert statuses["r-oem"] is ComplianceStatus.PASS
    assert statuses["r-mii"] is ComplianceStatus.PASS

    # Verification records from the two provider-backed capabilities.
    caps = {v.capability for v in result.verification_records}
    assert caps == {"BIS", "DIGILOCKER"}


def test_missing_bis_provider_unverifiable():
    engine = ComplianceEngine(
        rules={"BIS_CERTIFICATION_001": BisCertificationRule()},
        providers={},
    )
    requirements = [_req("r-bis", Capability.BIS, "BIS_CERTIFICATION_001")]
    result = engine.run([_bis_evidence()], requirements)
    assert result.compliance_results[0].status is ComplianceStatus.UNVERIFIABLE


def test_oem_and_mii_are_provider_free():
    engine = ComplianceEngine(
        rules={
            "OEM_AUTHORIZATION_001": OemAuthorizationRule(),
            "MAKE_IN_INDIA_001": MakeInIndiaRule(),
        },
        providers={},
    )
    requirements = [
        _req("r-oem", Capability.OEM_AUTHORIZATION, "OEM_AUTHORIZATION_001", required_oem="Acme Pvt Ltd"),
        _req("r-mii", Capability.MAKE_IN_INDIA, "MAKE_IN_INDIA_001", minimum_local_content_percentage=60.0),
    ]
    result = engine.run([_oem_evidence(), _mii_evidence()], requirements)
    assert all(r.status is ComplianceStatus.PASS for r in result.compliance_results)
    assert result.verification_records == []