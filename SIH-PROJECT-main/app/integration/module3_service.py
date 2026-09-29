"""Module 3: REAL external-compliance verification wiring.

Module 3 is the existing Core-Engine-GeM compliance engine —
:class:`compliance_engine.engine.ComplianceEngine` — running the
canonical rule set with the REAL provider adapters
(GSTNAdapter / PanAdapter / UdyamAdapter / McaAdapter / BisAdapter /
DigiLockerAdapter / DebarmentAdapter). This module OWNS NO compliance
logic: it only

  * constructs the real engine with the real rules and real adapters;
  * derives, from the bidder's ACTUAL document-level Evidence, the
    minimal set of requirements the rules can honestly evaluate
    (registration validity for identifiers the bidder actually
    submitted). No tender requirement is invented: capabilities with
    no triggering evidence produce no requirement and therefore no
    fabricated ComplianceResult;
  * runs the engine once per bidder and returns the real
    ``ComplianceResult[]`` and the authoritative ``Verification[]``
    records for Module 4 / Module 5.

Provider semantics are preserved exactly: an UNAVAILABLE / ERROR /
NOT_FOUND provider state maps (inside the rules) to UNVERIFIABLE —
never to a fake compliance failure, and never to a fabricated
VERIFIED record. When no real transport is configured, each adapter's
in-process transport raises and the adapter reports UNAVAILABLE; that
honest outcome is what flows downstream.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    Capability,
    Evidence,
    Requirement,
)
from compliance_engine.models.engine_models import EngineResult
from compliance_engine.models.verification import Verification
from compliance_engine.rules import (
    BisCertificationRule,
    DebarmentEligibilityRule,
    DigiLockerVerificationRule,
    FinancialCapacityRule,
    GSTRegistrationRule,
    MakeInIndiaRule,
    McaRegistrationRule,
    OemAuthorizationRule,
    PANValidationRule,
    Rule,
    UdyamRegistrationRule,
)
from compliance_engine.verification import VerificationProvider
from compliance_engine.verification.bis_adapter import BisAdapter
from compliance_engine.verification.debarment_adapter import DebarmentAdapter
from compliance_engine.verification.digilocker_adapter import DigiLockerAdapter
from compliance_engine.verification.gstn_adapter import GSTNAdapter
from compliance_engine.verification.mca_adapter import McaAdapter
from compliance_engine.verification.pan_adapter import PanAdapter
from compliance_engine.verification.udyam_adapter import UdyamAdapter

#: Status recorded on the Module 3 outcome when the engine ran.
STATUS_MODULE3_COMPLETED = "COMPLETED"

# MCA rule's own recognized document types (mirrors
# ``compliance_engine.rules.mca._MCA_DOC_TYPES``; kept in sync with the
# real rule so requirement derivation only fires on evidence the rule
# would actually consume).
_MCA_DOC_TYPES = {"MCA", "MCA21", "MCA21_REGISTRATION", "COMPANY_REGISTRATION"}


def canonical_rules() -> dict[str, Rule]:
    """The canonical Compliance Engine rule set (the engine's own rules)."""
    rules: list[Rule] = [
        GSTRegistrationRule(),
        PANValidationRule(),
        UdyamRegistrationRule(),
        McaRegistrationRule(),
        BisCertificationRule(),
        DigiLockerVerificationRule(),
        DebarmentEligibilityRule(),
        FinancialCapacityRule(),
        MakeInIndiaRule(),
        OemAuthorizationRule(),
    ]
    return {rule.rule_id: rule for rule in rules}


def default_real_providers() -> dict[Capability, VerificationProvider]:
    """The REAL production-shaped provider adapters.

    Constructed without a transport, each adapter's in-process
    transport raises ``NotImplementedError`` on the first query and the
    adapter reports the honest ``UNAVAILABLE`` status — an outage, never
    a fabricated outcome. Deployments with real government credentials
    inject the configured transports through the same adapter classes
    via ``build_compliance_engine(providers=...)``.
    """
    return {
        Capability.GST: GSTNAdapter(),
        Capability.PAN_INCOME_TAX: PanAdapter(),
        Capability.UDYAM: UdyamAdapter(),
        Capability.MCA21: McaAdapter(),
        Capability.BIS: BisAdapter(),
        Capability.DIGILOCKER: DigiLockerAdapter(),
        Capability.DEBARMENT: DebarmentAdapter(),
    }


def build_compliance_engine(
    *,
    rules: Optional[Mapping[str, Rule]] = None,
    providers: Optional[Mapping[Capability, VerificationProvider]] = None,
) -> ComplianceEngine:
    """Construct the REAL ComplianceEngine with its actual constructor."""
    return ComplianceEngine(
        rules=dict(rules) if rules is not None else canonical_rules(),
        providers=dict(providers) if providers is not None else default_real_providers(),
    )


def _requirement(
    requirement_id: str,
    capability: Capability,
    description: str,
    rule_id: str,
    *,
    expected: Any = None,
) -> Requirement:
    return Requirement(
        requirement_id=requirement_id,
        capability=capability,
        description=description,
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected=expected,
        parameters={},
        rule_id=rule_id,
    )


def derive_requirements(
    evidence: Sequence[Evidence],
    *,
    extra_requirements: Sequence[Requirement] = (),
) -> list[Requirement]:
    """Derive the requirements the rules can honestly evaluate.

    A requirement is created ONLY when the bidder actually submitted
    the triggering evidence for its rule (the exact (document_type,
    field_name) pair the real rule consumes). Capabilities with no such
    evidence produce no requirement and therefore no fabricated
    ComplianceResult. No tender thresholds (financial capacity, local
    content minimums, OEM parameters) are invented — those rules need
    explicit tender parameters this pipeline does not own; real tender
    requirements can be passed via ``extra_requirements``.
    """
    evidence_list = list(evidence)

    def has(doc_type: str, field_name: str) -> bool:
        return any(
            item.document_type == doc_type
            and item.field_name == field_name
            and item.value is not None
            for item in evidence_list
        )

    has_mca_cin = any(
        item.document_type.upper() in _MCA_DOC_TYPES
        and item.field_name == "cin"
        and item.value is not None
        for item in evidence_list
    )

    requirements: list[Requirement] = []
    if has("GST", "gstin"):
        requirements.append(
            _requirement(
                "m3-req-gst-registration",
                Capability.GST,
                "GST registration must be valid and active "
                "(the bidder submitted a GSTIN on a GST certificate).",
                "GST_REGISTRATION_001",
                expected="ACTIVE",
            )
        )
    if has("PAN", "pan_number"):
        requirements.append(
            _requirement(
                "m3-req-pan-validation",
                Capability.PAN_INCOME_TAX,
                "The submitted PAN must be valid and active "
                "(the bidder submitted a PAN on a PAN card).",
                "PAN_VALIDATION_001",
                expected="ACTIVE",
            )
        )
    if has("UDYAM", "udyam_registration_number"):
        requirements.append(
            _requirement(
                "m3-req-udyam-registration",
                Capability.UDYAM,
                "Udyam registration must be valid and active "
                "(the bidder submitted an Udyam registration number).",
                "UDYAM_REGISTRATION_001",
                expected="ACTIVE",
            )
        )
    if has_mca_cin:
        requirements.append(
            _requirement(
                "m3-req-mca-registration",
                Capability.MCA21,
                "MCA21 company registration must be valid and active "
                "(the bidder submitted a CIN on an MCA21 document).",
                "MCA21_REGISTRATION_001",
                expected="ACTIVE",
            )
        )
    requirements.extend(extra_requirements)
    return requirements


def run_module3_for_bidder(
    bidder_id: str,
    evidence: Sequence[Evidence],
    *,
    submission_id: Optional[str] = None,
    compliance_engine: Optional[ComplianceEngine] = None,
    requirements: Optional[Sequence[Requirement]] = None,
) -> dict[str, Any]:
    """Run the REAL compliance engine for one bidder's document Evidence.

    Returns the engine's actual ``ComplianceResult[]`` and the
    authoritative ``Verification[]`` records (model dumps, JSON-safe),
    plus the live model objects under the ``_..._objects`` keys for
    in-process consumers (Module 4 / Module 5). The engine's semantics
    are untouched: provider outages stay UNVERIFIABLE and nothing is
    fabricated. Engine errors propagate to the caller so the pipeline
    can record a MODULE3_FAILED state instead of a fake clean outcome.
    """
    engine = compliance_engine or build_compliance_engine()
    requirement_list = (
        list(requirements)
        if requirements is not None
        else derive_requirements(evidence)
    )
    result: EngineResult = engine.run(
        evidence=list(evidence),
        requirements=requirement_list,
        submission_id=submission_id,
    )
    return {
        "bidder_id": str(bidder_id),
        "status": STATUS_MODULE3_COMPLETED,
        "requirements_derived": len(requirement_list),
        "compliance_results": [
            r.model_dump(mode="json") for r in result.compliance_results
        ],
        "verification_records": [
            v.model_dump(mode="json") for v in result.verification_records
        ],
        # Live model objects for in-process consumers; never serialized.
        "_compliance_result_objects": list(result.compliance_results),
        "_verification_record_objects": list(result.verification_records),
    }


__all__ = [
    "STATUS_MODULE3_COMPLETED",
    "build_compliance_engine",
    "canonical_rules",
    "default_real_providers",
    "derive_requirements",
    "run_module3_for_bidder",
]
