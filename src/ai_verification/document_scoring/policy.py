"""Centralized, tender-configurable document-importance policy."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import DocumentImportance, DocumentPriority

DEFAULT_DOCUMENT_IMPORTANCE: dict[str, DocumentImportance] = {
    "GST": DocumentImportance(priority=DocumentPriority.CRITICAL, weight=1.00),
    "PAN": DocumentImportance(priority=DocumentPriority.CRITICAL, weight=1.00),
    "UDYAM": DocumentImportance(priority=DocumentPriority.HIGH, weight=0.80),
    "MCA21": DocumentImportance(priority=DocumentPriority.HIGH, weight=0.80),
    "DEBARMENT": DocumentImportance(priority=DocumentPriority.CRITICAL, weight=1.00),
    "BIDDER_IDENTITY": DocumentImportance(
        priority=DocumentPriority.CRITICAL, weight=1.00
    ),
    "BIS": DocumentImportance(priority=DocumentPriority.HIGH, weight=0.80),
    "ITR": DocumentImportance(priority=DocumentPriority.HIGH, weight=0.80),
    "FINANCIAL": DocumentImportance(priority=DocumentPriority.HIGH, weight=0.80),
    "MAKE_IN_INDIA": DocumentImportance(
        priority=DocumentPriority.HIGH, weight=0.80
    ),
    "OEM": DocumentImportance(priority=DocumentPriority.HIGH, weight=0.80),
    "DIGILOCKER": DocumentImportance(
        priority=DocumentPriority.MEDIUM, weight=0.55
    ),
    "EPFO": DocumentImportance(priority=DocumentPriority.MEDIUM, weight=0.55),
    "ESIC": DocumentImportance(priority=DocumentPriority.MEDIUM, weight=0.55),
    "STARTUP": DocumentImportance(
        priority=DocumentPriority.MEDIUM, weight=0.55
    ),
    "NSIC": DocumentImportance(priority=DocumentPriority.MEDIUM, weight=0.55),
    "CA_UDIN": DocumentImportance(
        priority=DocumentPriority.MEDIUM, weight=0.55
    ),
    "UNKNOWN": DocumentImportance(priority=DocumentPriority.LOW, weight=0.25),
}

DEFAULT_DOCUMENT_ALIASES: dict[str, str] = {
    "GSTN": "GST",
    "GST_CERTIFICATE": "GST",
    "GST_REGISTRATION": "GST",
    "PAN_CARD": "PAN",
    "UDYAM_REGISTRATION": "UDYAM",
    "MSME": "UDYAM",
    "MCA": "MCA21",
    "MCA21_REGISTRATION": "MCA21",
    "COMPANY_REGISTRATION": "MCA21",
    "BLACKLIST": "DEBARMENT",
    "PROCUREMENT_ELIGIBILITY": "DEBARMENT",
    "DEBARMENT_REGISTRY": "DEBARMENT",
    "BIS_CERTIFICATION": "BIS",
    "BIS_LICENCE": "BIS",
    "ITR": "FINANCIAL",
    "INCOME_TAX_RETURN": "FINANCIAL",
    "BALANCE_SHEET": "FINANCIAL",
    "FINANCIAL_STATEMENTS": "FINANCIAL",
    "LOCAL_CONTENT": "MAKE_IN_INDIA",
    "MII": "MAKE_IN_INDIA",
    "MAKE_IN_INDIA_DECLARATION": "MAKE_IN_INDIA",
    "OEM_AUTHORIZATION": "OEM",
    "AUTHORIZATION_LETTER": "OEM",
    "DIGILOCKER_DOCUMENT": "DIGILOCKER",
    "DPIIT": "STARTUP",
    "STARTUP_INDIA": "STARTUP",
    "UDIN": "CA_UDIN",
}

DEFAULT_REQUIRED_DOCUMENTS: dict[str, tuple[str, ...]] = {
    "GST": ("GST",),
    "GST_RETURN_FILING": ("GST",),
    "PAN_INCOME_TAX": ("PAN", "FINANCIAL"),
    "UDYAM": ("UDYAM",),
    "FINANCIAL": ("FINANCIAL",),
    "MAKE_IN_INDIA": ("MAKE_IN_INDIA",),
    "BIS": ("BIS",),
    "DIGILOCKER": ("DIGILOCKER",),
    "OEM_AUTHORIZATION": ("OEM",),
    "MCA21": ("MCA21",),
    "DEBARMENT": ("DEBARMENT",),
}


class DocumentScoringPolicy(BaseModel):
    """Importance, required-document, and traffic-light policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    red_threshold: float = Field(default=50.0, ge=0.0, le=100.0)
    yellow_threshold: float = Field(default=80.0, ge=0.0, le=100.0)
    minimum_evidence_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    document_importance: Mapping[str, DocumentImportance] = Field(
        default_factory=lambda: dict(DEFAULT_DOCUMENT_IMPORTANCE)
    )
    document_aliases: Mapping[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_DOCUMENT_ALIASES)
    )
    required_documents: Mapping[str, tuple[str, ...]] = Field(
        default_factory=lambda: dict(DEFAULT_REQUIRED_DOCUMENTS)
    )

    @field_validator("document_importance", "document_aliases", "required_documents")
    @classmethod
    def _copy_mappings(cls, value):
        return dict(value)

    @model_validator(mode="after")
    def _validate_thresholds(self):
        if self.red_threshold >= self.yellow_threshold:
            raise ValueError("red_threshold must be lower than yellow_threshold")
        return self

    def normalize_document_type(self, document_type: str) -> str:
        """Return a canonical upper-case document family identifier."""
        raw = str(document_type).strip().upper().replace("-", "_").replace(" ", "_")
        raw = "_".join(part for part in raw.split("_") if part)
        return self.document_aliases.get(raw, raw)

    def importance_for(self, document_type: str) -> DocumentImportance:
        canonical = self.normalize_document_type(document_type)
        fallback = self.document_importance.get("UNKNOWN")
        if fallback is None:
            fallback = DocumentImportance(
                priority=DocumentPriority.LOW, weight=0.25
            )
        return self.document_importance.get(canonical, fallback)

    def expected_documents_for(self, capability: str) -> tuple[str, ...]:
        capability = str(capability).strip().upper()
        return tuple(
            self.normalize_document_type(item)
            for item in self.required_documents.get(capability, ())
        )


DEFAULT_POLICY = DocumentScoringPolicy()


__all__ = [
    "DEFAULT_DOCUMENT_ALIASES",
    "DEFAULT_DOCUMENT_IMPORTANCE",
    "DEFAULT_POLICY",
    "DEFAULT_REQUIRED_DOCUMENTS",
    "DocumentScoringPolicy",
]
