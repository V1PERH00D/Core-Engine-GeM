"""Shared builders for cross-source identity reconciliation tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from compliance_engine.models.verification import (
    Verification,
    VerificationStatus,
)


def make_verification(
    *,
    verification_id: str,
    bidder_id: str = "bidder-1",
    capability: str,
    source: str,
    status: VerificationStatus,
    data: dict[str, Any] | None = None,
    queried_identifier: Optional[str] = None,
    evidence_id: Optional[str] = None,
    document_id: Optional[str] = None,
) -> Verification:
    """Construct a Verification record with a UTC timestamp."""

    return Verification(
        verification_id=verification_id,
        bidder_id=bidder_id,
        capability=capability,
        source=source,
        status=status,
        data=data or {},
        retrieved_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        evidence_id=evidence_id,
        document_id=document_id,
        queried_identifier=queried_identifier,
    )


def gst_verified(
    *,
    verification_id: str = "GSTN_MOCK:GSTIN:1",
    bidder_id: str = "bidder-1",
    legal_name: Optional[str] = "ACME ENTERPRISES PRIVATE LIMITED",
    queried_identifier: Optional[str] = "27AAAAA0000A1Z5",
    evidence_id: Optional[str] = "ev-gst",
    document_id: Optional[str] = "doc-gst",
) -> Verification:
    """Build a fully-verified GST Verification record."""

    return make_verification(
        verification_id=verification_id,
        bidder_id=bidder_id,
        capability="GST",
        source="GSTN_MOCK",
        status=VerificationStatus.VERIFIED,
        data={"legal_name": legal_name},
        queried_identifier=queried_identifier,
        evidence_id=evidence_id,
        document_id=document_id,
    )


def pan_verified(
    *,
    verification_id: str = "PAN_MOCK:PAN:1",
    bidder_id: str = "bidder-1",
    name_on_pan: Optional[str] = "ACME ENTERPRISES PRIVATE LIMITED",
    queried_identifier: Optional[str] = "AAAAA0000A",
    evidence_id: Optional[str] = "ev-pan",
    document_id: Optional[str] = "doc-pan",
) -> Verification:
    """Build a fully-verified PAN Verification record."""

    return make_verification(
        verification_id=verification_id,
        bidder_id=bidder_id,
        capability="PAN",
        source="PAN_MOCK",
        status=VerificationStatus.VERIFIED,
        data={"name_on_pan": name_on_pan},
        queried_identifier=queried_identifier,
        evidence_id=evidence_id,
        document_id=document_id,
    )


def udyam_verified(
    *,
    verification_id: str = "UDYAM_MOCK:UDYAM:1",
    bidder_id: str = "bidder-1",
    enterprise_name: Optional[str] = "ACME ENTERPRISES PRIVATE LIMITED",
    queried_identifier: Optional[str] = "UDYAM-0001",
    evidence_id: Optional[str] = "ev-udyam",
    document_id: Optional[str] = "doc-udyam",
) -> Verification:
    """Build a fully-verified Udyam Verification record."""

    return make_verification(
        verification_id=verification_id,
        bidder_id=bidder_id,
        capability="UDYAM",
        source="UDYAM_MOCK",
        status=VerificationStatus.VERIFIED,
        data={"enterprise_name": enterprise_name},
        queried_identifier=queried_identifier,
        evidence_id=evidence_id,
        document_id=document_id,
    )


def mca_verified(
    *,
    verification_id: str = "MCA_MOCK:CIN:1",
    bidder_id: str = "bidder-1",
    company_name: Optional[str] = "ACME ENTERPRISES PRIVATE LIMITED",
    queried_identifier: Optional[str] = "U00000AA0000AAA000000",
    evidence_id: Optional[str] = "ev-mca",
    document_id: Optional[str] = "doc-mca",
) -> Verification:
    """Build a fully-verified MCA Verification record."""

    return make_verification(
        verification_id=verification_id,
        bidder_id=bidder_id,
        capability="MCA",
        source="MCA_MOCK",
        status=VerificationStatus.VERIFIED,
        data={"company_name": company_name},
        queried_identifier=queried_identifier,
        evidence_id=evidence_id,
        document_id=document_id,
    )


__all__ = [
    "gst_verified",
    "mca_verified",
    "make_verification",
    "pan_verified",
    "udyam_verified",
]