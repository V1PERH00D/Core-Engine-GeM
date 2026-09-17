"""Deterministic, fully synthetic demo scenarios.

Everything in this module is demo-only data:

* Government-side providers are **static demo providers** whose
  ``source`` IDs end in ``_DEMO``. They represent the *integration
  seams* where adapters for GSTN / PAN / Udyam / MCA21 / BIS /
  DigiLocker / debarment sources plug in; they are NOT live government
  responses and are never used as production data.
* All identifiers (GSTIN, PAN, CIN, BIS licence numbers, ...) are
  clearly synthetic values invented for this demo. They do not belong to
  any real person or company.
* No network access, government API credentials, or LLM API key is
  required. Explanations use the deterministic built-in fallback.

The demo tender is a fixed :func:`demo_requirements()` set reusing the
canonical rule IDs of the Compliance Engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Callable, Final

from ai_verification.cross_bidder.document_artifact_store import (
    DocumentMeta,
    InMemoryDocumentArtifactStore,
)
from ai_verification.engine import VerificationEngine
from ai_verification.explanations.engine import ExplanationEngine
from ai_verification.models.contracts import BidderSummary
from compliance_engine.engine import ComplianceEngine
from compliance_engine.models import (
    Applicability,
    Capability,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
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
from compliance_engine.verification.base import (
    MockGSTProvider,
    VerificationProvider,
)
from compliance_engine.verification.pan import MockPANProvider
from compliance_engine.verification.udyam import MockUdyamProvider

from application.models import BidderSubmission, SubmissionDocument
from application.service import ComplianceApplicationService

#: Fixed demo clock so every demo run produces identical snapshots.
DEMO_TIME: Final[float] = 1_780_000_000.0
DEMO_RETRIEVED_AT: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)
DEMO_EVALUATION_DATE: Final[str] = "2026-06-01"

#: Clearly synthetic demo identities (no real person/company data).
DEMO_LEGAL_NAME: Final[str] = "ACME ENTERPRISES PRIVATE LIMITED"
DEMO_OEM_NAME: Final[str] = "FICTIONAL SYSTEMS PRIVATE LIMITED"
DEMO_CIN: Final[str] = "U27310KA2012PTC091234"
DEMO_BIS_CERT_VALID: Final[str] = "CM/L-DEMO-1001"
DEMO_BIS_CERT_INVALID: Final[str] = "CM/L-DEMO-9BAD"
DEMO_DLOCKER_DOC_ID: Final[str] = "DL-DEMO-0001"


class StaticDemoProvider(VerificationProvider):
    """Deterministic demo lookup over a canned identifier table.

    This is the same pattern as the existing ``Mock*Provider`` classes:
    a ``VerificationProvider`` that never performs I/O. The ``source``
    string always ends in ``_DEMO`` so any record produced by it is
    visibly synthetic and can never be mistaken for an authoritative
    government response.
    """

    def __init__(
        self,
        *,
        capability: Capability,
        source: str,
        records: dict[str, tuple[VerificationStatus, dict[str, Any]]],
    ) -> None:
        if not source.endswith("_DEMO"):
            raise ValueError("Demo providers must use an *_DEMO source id.")
        self._capability = capability
        self._source = source
        self._records = dict(records)
        self._counter = 0

    def verify(
        self, bidder_id: str, identifier: str, **kwargs: Any
    ) -> Verification:
        self._counter += 1
        status, data = self._records.get(
            identifier, (VerificationStatus.NOT_FOUND, {})
        )
        return Verification(
            verification_id=f"{self._source}:{identifier}:{self._counter}",
            bidder_id=bidder_id,
            capability=self._capability,
            source=self._source,
            queried_identifier=identifier,
            status=status,
            data=dict(data),
            retrieved_at=DEMO_RETRIEVED_AT,
        )


# ---------------------------------------------------------------------------
# Demo tenders, rules and providers
# ---------------------------------------------------------------------------


def demo_rules() -> dict[str, Rule]:
    """The canonical rule set of the Compliance Engine for the demo tender."""
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


def demo_providers(
    *,
    bis_valid: bool = True,
    debarment: str = "clear",
) -> dict[Capability, VerificationProvider]:
    """Static demo providers for all provider-backed capabilities.

    ``bis_valid=False`` makes the BIS source report the licence as
    INVALID; ``debarment="restricted"`` makes the debarment source
    report an identifier-matched active restriction.
    """
    bis_records: dict[str, tuple[VerificationStatus, dict[str, Any]]] = (
        {DEMO_BIS_CERT_VALID: (VerificationStatus.VERIFIED, {"licence_status": "ACTIVE"})}
        if bis_valid
        else {DEMO_BIS_CERT_INVALID: (VerificationStatus.INVALID, {})}
    )
    if debarment == "restricted":
        # Normalized date objects, exactly as the real debarment adapter
        # emits after parsing an authoritative response.
        debarment_data: dict[str, Any] = {
            "restriction_status": "RESTRICTED",
            "restriction_type": "DEBARMENT",
            "match_method": "EXACT_IDENTIFIER",
            "effective_date": date(2025, 1, 1),
            "end_date": date(2027, 12, 31),
        }
    else:
        debarment_data = {
            "restriction_status": "CLEAR",
            "match_method": "EXACT_IDENTIFIER",
        }
    return {
        Capability.GST: MockGSTProvider(),
        Capability.PAN_INCOME_TAX: MockPANProvider(),
        Capability.UDYAM: MockUdyamProvider(),
        Capability.MCA21: StaticDemoProvider(
            capability=Capability.MCA21,
            source="MCA21_DEMO",
            records={
                DEMO_CIN: (
                    VerificationStatus.VERIFIED,
                    {
                        "company_status": "ACTIVE",
                        "company_name": DEMO_LEGAL_NAME,
                    },
                )
            },
        ),
        Capability.BIS: StaticDemoProvider(
            capability=Capability.BIS,
            source="BIS_DEMO",
            records=bis_records,
        ),
        Capability.DIGILOCKER: StaticDemoProvider(
            capability=Capability.DIGILOCKER,
            source="DIGILOCKER_DEMO",
            records={
                DEMO_DLOCKER_DOC_ID: (
                    VerificationStatus.VERIFIED,
                    {
                        "issuer": "DEMO DOCUMENT ISSUER",
                        "document_type": "GST_CERTIFICATE",
                    },
                )
            },
        ),
        Capability.DEBARMENT: StaticDemoProvider(
            capability=Capability.DEBARMENT,
            source="DEBARMENT_DEMO",
            records={
                MockGSTProvider.GSTIN_VERIFIED: (
                    VerificationStatus.VERIFIED,
                    debarment_data,
                )
            },
        ),
    }


def demo_requirements() -> list[Requirement]:
    """The fixed synthetic tender requirement set used by every scenario."""

    def req(
        requirement_id: str,
        capability: Capability,
        description: str,
        rule_id: str,
        *,
        expected: Any = None,
        parameters: dict[str, Any] | None = None,
    ) -> Requirement:
        return Requirement(
            requirement_id=requirement_id,
            capability=capability,
            description=description,
            mandatory=True,
            applicability=Applicability.APPLICABLE,
            expected=expected,
            parameters=parameters or {},
            rule_id=rule_id,
        )

    return [
        req(
            "demo-req-gst",
            Capability.GST,
            "GST registration must be valid and active.",
            "GST_REGISTRATION_001",
            expected="ACTIVE",
        ),
        req(
            "demo-req-pan",
            Capability.PAN_INCOME_TAX,
            "PAN must be valid and active.",
            "PAN_VALIDATION_001",
            expected="ACTIVE",
        ),
        req(
            "demo-req-udyam",
            Capability.UDYAM,
            "Udyam (MSME) registration must be valid.",
            "UDYAM_REGISTRATION_001",
            expected="ACTIVE",
        ),
        req(
            "demo-req-mca21",
            Capability.MCA21,
            "MCA21 company registration must be active.",
            "MCA21_REGISTRATION_001",
            expected="ACTIVE",
        ),
        req(
            "demo-req-bis",
            Capability.BIS,
            "BIS product certification must be active.",
            "BIS_CERTIFICATION_001",
            expected="ACTIVE",
        ),
        req(
            "demo-req-digilocker",
            Capability.DIGILOCKER,
            "Submitted documents must verify through DigiLocker.",
            "DIGILOCKER_VERIFICATION_001",
        ),
        req(
            "demo-req-debarment",
            Capability.DEBARMENT,
            "Bidder must not be under an active debarment order.",
            "DEBARMENT_ELIGIBILITY_001",
            expected="CLEAR",
            parameters={"evaluation_date": DEMO_EVALUATION_DATE},
        ),
        req(
            "demo-req-financial",
            Capability.FINANCIAL,
            "Average annual turnover must be at least INR 20 crore.",
            "FINANCIAL_CAPACITY_001",
            parameters={
                "focus": "TURNOVER",
                "minimum_turnover_inr_cr": 20.0,
                "turnover_operator": ">=",
                "turnover_mode": "AVERAGE_ANNUAL",
                "required_financial_years": ["2021-22", "2022-23", "2023-24"],
            },
        ),
        req(
            "demo-req-mii",
            Capability.MAKE_IN_INDIA,
            "Local content must be at least 50%.",
            "MAKE_IN_INDIA_001",
            parameters={"minimum_local_content_percentage": 50.0},
        ),
        req(
            "demo-req-oem",
            Capability.OEM_AUTHORIZATION,
            "A valid OEM authorization naming the bidder is required.",
            "OEM_AUTHORIZATION_001",
            parameters={
                "required_oem": DEMO_OEM_NAME,
                "required_bidder": DEMO_LEGAL_NAME,
            },
        ),
    ]


# ---------------------------------------------------------------------------
# Scenario construction
# ---------------------------------------------------------------------------


def _doc(document_id: str, document_type: str) -> SubmissionDocument:
    return SubmissionDocument(
        document_id=document_id,
        document_type=document_type,
        content=(
            f"Synthetic demo document {document_id} ({document_type}). "
            "No real government record or personal data."
        ).encode("utf-8"),
    )


def _ev(
    bidder_id: str,
    document_id: str,
    document_type: str,
    field_name: str,
    value: Any,
) -> Evidence:
    return Evidence(
        evidence_id=f"{document_id}:{field_name}",
        bidder_id=bidder_id,
        document_id=document_id,
        document_type=document_type,
        field_name=field_name,
        value=value,
        confidence=0.99,
    )


#: Logical document slots shared by every scenario; the durable IDs are
#: prefixed with the bidder ID so scenarios sharing one store never clash.
_DOC_SLOTS: Final[tuple[tuple[str, str], ...]] = (
    ("gst-cert", "GST"),
    ("pan-card", "PAN"),
    ("udyam-cert", "UDYAM"),
    ("mca-profile", "MCA"),
    ("bis-licence", "BIS"),
    ("digilocker-doc", "DIGILOCKER"),
    ("debarment-declaration", "DEBARMENT"),
    ("fin-fy2021", "ITR"),
    ("fin-fy2022", "ITR"),
    ("fin-fy2023", "ITR"),
    ("mii-declaration", "MAKE_IN_INDIA"),
    ("oem-authorization", "OEM"),
)


def _doc_id(bidder_id: str, slot: str) -> str:
    return f"demo-doc:{bidder_id}:{slot}"


def _documents(bidder_id: str) -> list[SubmissionDocument]:
    return [
        _doc(_doc_id(bidder_id, slot), document_type)
        for slot, document_type in _DOC_SLOTS
    ]


def _business_evidence(
    bidder_id: str,
    *,
    legal_name: str = DEMO_LEGAL_NAME,
    bis_certificate: str = DEMO_BIS_CERT_VALID,
    local_content: float = 62.0,
    turnovers: tuple[float, float, float] = (30.0, 32.0, 35.0),
) -> list[Evidence]:
    doc = lambda slot: _doc_id(bidder_id, slot)
    evidence = [
        _ev(bidder_id, doc("gst-cert"), "GST", "gstin", MockGSTProvider.GSTIN_VERIFIED),
        _ev(bidder_id, doc("gst-cert"), "GST", "legal_name", legal_name),
        _ev(bidder_id, doc("pan-card"), "PAN", "pan_number", MockPANProvider.PAN_VERIFIED),
        _ev(bidder_id, doc("pan-card"), "PAN", "name_on_pan", DEMO_LEGAL_NAME),
        _ev(bidder_id, doc("udyam-cert"), "UDYAM", "udyam_registration_number", MockUdyamProvider.UDYAM_VERIFIED),
        _ev(bidder_id, doc("udyam-cert"), "UDYAM", "enterprise_name", DEMO_LEGAL_NAME),
        _ev(bidder_id, doc("mca-profile"), "MCA", "cin", DEMO_CIN),
        _ev(bidder_id, doc("bis-licence"), "BIS", "certificate_number", bis_certificate),
        _ev(bidder_id, doc("digilocker-doc"), "DIGILOCKER", "document_access_id", DEMO_DLOCKER_DOC_ID),
        _ev(bidder_id, doc("debarment-declaration"), "DEBARMENT", "debarment_identifier", MockGSTProvider.GSTIN_VERIFIED),
        _ev(bidder_id, doc("mii-declaration"), "MAKE_IN_INDIA", "local_content_percentage", local_content),
        _ev(bidder_id, doc("mii-declaration"), "MAKE_IN_INDIA", "country_of_origin", "India"),
        _ev(bidder_id, doc("oem-authorization"), "OEM", "oem_name", DEMO_OEM_NAME),
        _ev(bidder_id, doc("oem-authorization"), "OEM", "authorized_bidder", DEMO_LEGAL_NAME),
    ]
    years = ("2021-22", "2022-23", "2023-24")
    slots = ("fin-fy2021", "fin-fy2022", "fin-fy2023")
    for slot, year, turnover in zip(slots, years, turnovers):
        evidence.append(_ev(bidder_id, doc(slot), "ITR", "financial_year", year))
        evidence.append(_ev(bidder_id, doc(slot), "ITR", "turnover_inr_cr", turnover))
    return evidence


@dataclass(frozen=True)
class DemoScenario:
    """One deterministic demo scenario."""

    name: str
    description: str
    submission_factory: Callable[[], BidderSubmission]
    providers_factory: Callable[[], dict] = demo_providers
    document_store: InMemoryDocumentArtifactStore | None = None


def _submission(
    bidder_id: str,
    *,
    evidence: list[Evidence],
    corpus: list[BidderSummary] | None = None,
    extra_documents: list[SubmissionDocument] | None = None,
) -> BidderSubmission:
    return BidderSubmission(
        bidder_id=bidder_id,
        submission_id=f"sub:{bidder_id}",
        documents=_documents(bidder_id) + list(extra_documents or []),
        evidence=evidence,
        requirements=demo_requirements(),
        bidder_corpus=list(corpus or []),
        correlation_id=f"corr:{bidder_id}",
    )


def _clean_submission() -> BidderSubmission:
    bidder_id = "demo-bidder-clean-01"
    return _submission(bidder_id, evidence=_business_evidence(bidder_id))


def _failing_submission() -> BidderSubmission:
    bidder_id = "demo-bidder-failing-02"
    return _submission(
        bidder_id,
        evidence=_business_evidence(
            bidder_id,
            bis_certificate=DEMO_BIS_CERT_INVALID,
            local_content=35.0,
            turnovers=(4.0, 5.0, 6.0),
        ),
    )


def _missing_submission() -> BidderSubmission:
    """Only PAN/Udyam evidence: every other capability lacks evidence."""
    bidder_id = "demo-bidder-missing-03"
    evidence = [
        _ev(bidder_id, _doc_id(bidder_id, "pan-card"), "PAN", "pan_number", MockPANProvider.PAN_VERIFIED),
        _ev(bidder_id, _doc_id(bidder_id, "pan-card"), "PAN", "name_on_pan", DEMO_LEGAL_NAME),
        _ev(bidder_id, _doc_id(bidder_id, "udyam-cert"), "UDYAM", "udyam_registration_number", MockUdyamProvider.UDYAM_VERIFIED),
        _ev(bidder_id, _doc_id(bidder_id, "udyam-cert"), "UDYAM", "enterprise_name", DEMO_LEGAL_NAME),
    ]
    return _submission(bidder_id, evidence=evidence)


def _inconsistent_submission() -> BidderSubmission:
    """GST legal name disagrees with PAN/Udyam names across documents."""
    bidder_id = "demo-bidder-inconsistent-04"
    return _submission(
        bidder_id,
        evidence=_business_evidence(
            bidder_id, legal_name="UNRELATED DEMO TRADING COMPANY LIMITED"
        ),
    )


# -- cross-bidder scenario --------------------------------------------------

_CROSS_BIDDER_TEXT = (
    "This synthetic OEM authorization letter is identical across two demo "
    "bidders to demonstrate cross-bidder document-reuse detection."
)
_CROSS_BIDDER_HASH = "sha256:" + "ab" * 31


def _cross_bidder_document_store() -> InMemoryDocumentArtifactStore:
    def meta(document_type: str, evidence_id: str, bidder_name: str) -> DocumentMeta:
        return DocumentMeta(
            document_type=document_type,
            evidence_id=evidence_id,
            ocr_confidence=0.95,
            document_type_confidence=0.9,
            issuer="FICTIONAL OEM REGISTRY",
            authorization_number="AUTH-DEMO-1",
            issue_date=date(2025, 1, 1),
            valid_until=date(2027, 1, 1),
            bidder_name=bidder_name,
        )

    return InMemoryDocumentArtifactStore(
        raw_texts={
            "demo-doc-oem-a": _CROSS_BIDDER_TEXT,
            "demo-doc-oem-b": _CROSS_BIDDER_TEXT,
        },
        file_hashes={
            "demo-doc-oem-a": _CROSS_BIDDER_HASH,
            "demo-doc-oem-b": _CROSS_BIDDER_HASH,
        },
        metadata={
            "demo-doc-oem-a": meta("PDF", "ev-xb-a", "DEMO BIDDER A"),
            "demo-doc-oem-b": meta("PDF", "ev-xb-b", "DEMO BIDDER B"),
        },
    )


def _cross_bidder_submission() -> BidderSubmission:
    bidder_id = "demo-bidder-crossbidder-05"
    rival_id = "demo-bidder-rival-06"
    evidence = _business_evidence(bidder_id) + [
        _ev(bidder_id, "demo-doc-oem-a", "PDF", "attachment", "oem-letter")
    ]
    corpus = BidderSummary(
        bidder_id=rival_id,
        evidence=[
            _ev(rival_id, "demo-doc-oem-b", "PDF", "attachment", "oem-letter")
        ],
    )
    return _submission(
        bidder_id,
        evidence=evidence,
        corpus=[corpus],
        extra_documents=[_doc("demo-doc-oem-a", "PDF")],
    )


# ---------------------------------------------------------------------------
# Scenario registry and runner
# ---------------------------------------------------------------------------

_SCENARIOS: dict[str, DemoScenario] = {
    "clean": DemoScenario(
        name="clean",
        description=(
            "Fully compliant synthetic bidder: every check passes, no "
            "flag is set."
        ),
        submission_factory=_clean_submission,
    ),
    "failing": DemoScenario(
        name="failing",
        description=(
            "Deterministic compliance failures: invalid BIS licence, "
            "local content below 50%, active debarment restriction, "
            "turnover below the financial threshold."
        ),
        submission_factory=_failing_submission,
        providers_factory=lambda: demo_providers(
            bis_valid=False, debarment="restricted"
        ),
    ),
    "missing": DemoScenario(
        name="missing",
        description=(
            "Missing / insufficient evidence: only PAN and Udyam "
            "evidence is supplied, everything else is absent."
        ),
        submission_factory=_missing_submission,
    ),
    "inconsistent": DemoScenario(
        name="inconsistent",
        description=(
            "Cross-document inconsistency: the GST legal name disagrees "
            "with the PAN and Udyam names."
        ),
        submission_factory=_inconsistent_submission,
    ),
    "cross_bidder": DemoScenario(
        name="cross_bidder",
        description=(
            "Cross-bidder anomaly: two synthetic bidders submitted byte-"
            "identical OEM authorization documents."
        ),
        submission_factory=_cross_bidder_submission,
        document_store=_cross_bidder_document_store(),
    ),
}


def scenario_names() -> list[str]:
    """The demo scenario names, in a stable order."""
    return sorted(_SCENARIOS)


def get_scenario(name: str) -> DemoScenario:
    try:
        return _SCENARIOS[name]
    except KeyError:
        raise KeyError(
            f"Unknown demo scenario {name!r}. "
            f"Available: {scenario_names()}."
        ) from None


def build_demo_service(
    scenario: DemoScenario,
    *,
    store,
    clock: Callable[[], float],
) -> ComplianceApplicationService:
    """Build the wired application service for one demo scenario.

    All state lives in the shared in-memory store, so flag lineage can be
    reconstructed across scenarios by the caller if desired.
    """
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    compliance_engine = ComplianceEngine(
        rules=demo_rules(),
        providers=scenario.providers_factory(),
    )
    verification_engine = VerificationEngine(
        artifact_store=scenario.document_store
    )
    explanation_engine = ExplanationEngine()  # deterministic fallback, no LLM
    return ComplianceApplicationService(
        compliance_engine=compliance_engine,
        verification_engine=verification_engine,
        explanation_engine=explanation_engine,
        uow_factory=lambda: InMemoryUnitOfWork(store),
        clock=clock,
    )


def run_demo(
    names: list[str] | None = None,
    *,
    clock: Callable[[], float] | None = None,
):
    """Run demo scenarios end-to-end; return ``{scenario: ApplicationResult}``.

    Fully deterministic and offline: fixed clock, static demo providers,
    deterministic explanation fallback. Adds no credentials, performs no
    network access, and produces no severity or risk data.
    """
    from infrastructure.persistence.memory import _Store

    if clock is None:
        clock = lambda: DEMO_TIME
    store = _Store()
    results = {}
    for name in names or scenario_names():
        scenario = get_scenario(name)
        service = build_demo_service(scenario, store=store, clock=clock)
        results[name] = service.process_bid(scenario.submission_factory())
    return results


__all__ = [
    "DEMO_BIS_CERT_INVALID",
    "DEMO_BIS_CERT_VALID",
    "DEMO_CIN",
    "DEMO_EVALUATION_DATE",
    "DEMO_LEGAL_NAME",
    "DEMO_OEM_NAME",
    "DEMO_TIME",
    "DemoScenario",
    "StaticDemoProvider",
    "build_demo_service",
    "demo_providers",
    "demo_requirements",
    "demo_rules",
    "get_scenario",
    "run_demo",
    "scenario_names",
]
