"""Shared builders for cross-document consistency tests."""

from __future__ import annotations

from typing import Optional

from compliance_engine.models import Evidence


def make_evidence(
    *,
    bidder_id: str = "bidder-1",
    document_id: str,
    document_type: str,
    field_name: str,
    value,
    confidence: float = 0.95,
) -> Evidence:
    """Construct a typed Evidence record with stable evidence_id."""

    return Evidence(
        evidence_id=f"{document_id}:{field_name}",
        bidder_id=bidder_id,
        document_id=document_id,
        document_type=document_type,
        field_name=field_name,
        value=value,
        confidence=confidence,
    )


def gst_evidence(
    *,
    document_id: str = "doc-gst",
    bidder_id: str = "bidder-1",
    gstin: Optional[str] = "27AAACI1234F1Z5",
    legal_name: Optional[str] = None,
    registered_address: Optional[str] = None,
) -> list[Evidence]:
    """Build the canonical GST evidence bundle."""
    out: list[Evidence] = []
    if gstin is not None:
        out.append(make_evidence(
            bidder_id=bidder_id,
            document_id=document_id,
            document_type="GST",
            field_name="gstin",
            value=gstin,
        ))
    if legal_name is not None:
        out.append(make_evidence(
            bidder_id=bidder_id,
            document_id=document_id,
            document_type="GST",
            field_name="legal_name",
            value=legal_name,
        ))
    if registered_address is not None:
        out.append(make_evidence(
            bidder_id=bidder_id,
            document_id=document_id,
            document_type="GST",
            field_name="registered_address",
            value=registered_address,
        ))
    return out


def pan_evidence(
    *,
    document_id: str = "doc-pan",
    bidder_id: str = "bidder-1",
    pan_number: Optional[str] = "AAACI1234F",
    name_on_pan: Optional[str] = None,
) -> list[Evidence]:
    out: list[Evidence] = []
    if pan_number is not None:
        out.append(make_evidence(
            bidder_id=bidder_id,
            document_id=document_id,
            document_type="PAN",
            field_name="pan_number",
            value=pan_number,
        ))
    if name_on_pan is not None:
        out.append(make_evidence(
            bidder_id=bidder_id,
            document_id=document_id,
            document_type="PAN",
            field_name="name_on_pan",
            value=name_on_pan,
        ))
    return out


def udyam_evidence(
    *,
    document_id: str = "doc-udyam",
    bidder_id: str = "bidder-1",
    udyam_registration_number: Optional[str] = "UDYAM-MH-12-0019842",
    enterprise_name: Optional[str] = None,
) -> list[Evidence]:
    out: list[Evidence] = []
    if udyam_registration_number is not None:
        out.append(make_evidence(
            bidder_id=bidder_id,
            document_id=document_id,
            document_type="UDYAM",
            field_name="udyam_registration_number",
            value=udyam_registration_number,
        ))
    if enterprise_name is not None:
        out.append(make_evidence(
            bidder_id=bidder_id,
            document_id=document_id,
            document_type="UDYAM",
            field_name="enterprise_name",
            value=enterprise_name,
        ))
    return out


def itr_evidence(
    *,
    document_id: str = "doc-itr",
    bidder_id: str = "bidder-1",
    filing_date: Optional[str] = "2024-07-28",
) -> list[Evidence]:
    out: list[Evidence] = []
    if filing_date is not None:
        out.append(make_evidence(
            bidder_id=bidder_id,
            document_id=document_id,
            document_type="ITR",
            field_name="filing_date",
            value=filing_date,
        ))
    return out


def oem_evidence(
    *,
    document_id: str = "doc-oem",
    bidder_id: str = "bidder-1",
    manufacturer: Optional[str] = "Acme Industries Ltd",
) -> list[Evidence]:
    out: list[Evidence] = []
    if manufacturer is not None:
        out.append(make_evidence(
            bidder_id=bidder_id,
            document_id=document_id,
            document_type="OEM",
            field_name="manufacturer",
            value=manufacturer,
        ))
    return out


__all__ = [
    "gst_evidence",
    "itr_evidence",
    "make_evidence",
    "oem_evidence",
    "pan_evidence",
    "udyam_evidence",
]
