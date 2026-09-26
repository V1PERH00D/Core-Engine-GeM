"""Production-shaped DigiLocker document verification adapter.

DigiLocker is modelled carefully: it establishes provenance/authenticity of
a retrieved digital document when a valid verification result is available.
It is *not* a generic compliance authority, and this adapter does not turn it
into one. The adapter only reports whether a referenced document resolves and
verifies, plus document metadata for the rule to compare against tender
requirements.

No network, credentials, signing, or authentication code lives here, and no
personal Aadhaar/PAN/etc. data is stored or fabricated. Production
integration requires a real DigiLocker (or equivalent) verification API and
its authentication details, which are out of scope.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from compliance_engine.models import Capability, Verification, VerificationStatus
from compliance_engine.verification.base import VerificationProvider
from compliance_engine.verification.transport import (
    InProcessTransport,
    SourceResponseEnvelope,
    TransportError,
    VerificationTransport,
)


class DigiLockerQuery(BaseModel):
    """Typed query for a future DigiLocker document resolution."""

    model_config = ConfigDict(extra="forbid")

    bidder_id: str = Field(..., description="Bidder whose document is resolved.")
    document_access_id: str = Field(..., description="DigiLocker/platform document ID.")
    call_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description="Per-call UUID4 hex for a unique Verification.verification_id.",
    )


DigiLockerResponseEnvelope = SourceResponseEnvelope


class NormalizedDigiLockerData(BaseModel):
    """Minimum metadata a verified digital document exposes."""

    model_config = ConfigDict(extra="forbid")

    document_access_id: str | None = Field(None, description="Resolved document ID.")
    document_type: str | None = Field(None, description="Type of digital document.")
    issuer: str | None = Field(None, description="Issuing authority.")
    issued_on: str | None = Field(None, description="Issue date (ISO).")
    document_hash: str | None = Field(None, description="Integrity hash, when present.")
    verification_result: str | None = Field(
        None,
        description=(
            "Detail of a failed/invalid verification: SIGNATURE_INVALID, "
            "HASH_MISMATCH, REVOKED, EXPIRED, ISSUER_NOT_RECOGNIZED."
        ),
    )


class DigiLockerResponseParser:
    """Map a :class:`SourceResponseEnvelope` to a :class:`Verification`."""

    def parse(
        self,
        envelope: SourceResponseEnvelope,
        *,
        query: DigiLockerQuery,
        bidder_id: str,
    ) -> Verification:
        status, data = self._derive_domain_status(envelope)
        return Verification(
            verification_id=Verification.allocate_id(
                source=DigiLockerAdapter.SOURCE,
                identifier=query.document_access_id,
                call_id=query.call_id,
            ),
            bidder_id=bidder_id,
            capability=Capability.DIGILOCKER,
            source=DigiLockerAdapter.SOURCE,
            queried_identifier=query.document_access_id,
            status=status,
            data=data,
            retrieved_at=datetime.now(UTC),
            query=query.model_dump(),
            raw_response=envelope.raw_response,
            latency_ms=envelope.latency_ms,
            correlation_id=envelope.correlation_id,
            transport_status_code=envelope.status_code,
        )

    @staticmethod
    def _derive_domain_status(
        envelope: SourceResponseEnvelope,
    ) -> tuple[VerificationStatus, dict[str, Any]]:
        raw = envelope.raw_response
        if not isinstance(raw, dict) or not raw:
            return VerificationStatus.NOT_FOUND, {}
        result = raw.get("verification_result")
        if result == "VALID" or result is None:
            return VerificationStatus.VERIFIED, NormalizedDigiLockerData(
                document_access_id=raw.get("document_access_id"),
                document_type=raw.get("document_type"),
                issuer=raw.get("issuer"),
                issued_on=raw.get("issued_on"),
                document_hash=raw.get("document_hash"),
                verification_result=result,
            ).model_dump()
        if result in (
            "SIGNATURE_INVALID",
            "HASH_MISMATCH",
            "REVOKED",
            "EXPIRED",
            "ISSUER_NOT_RECOGNIZED",
            "INVALID",
        ):
            return VerificationStatus.INVALID, NormalizedDigiLockerData(
                document_access_id=raw.get("document_access_id"),
                document_type=raw.get("document_type"),
                issuer=raw.get("issuer"),
                issued_on=raw.get("issued_on"),
                document_hash=raw.get("document_hash"),
                verification_result=result,
            ).model_dump()
        return VerificationStatus.ERROR, {}


class DigiLockerAdapter(VerificationProvider):
    """Production-shaped DigiLocker document adapter over the transport seam."""

    SOURCE: Final[str] = "DIGILOCKER"

    def __init__(
        self,
        transport: VerificationTransport | None = None,
        parser: DigiLockerResponseParser | None = None,
    ) -> None:
        self._transport: VerificationTransport = transport or InProcessTransport()
        self._parser = parser or DigiLockerResponseParser()

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        query = DigiLockerQuery(bidder_id=bidder_id, document_access_id=str(identifier))
        try:
            envelope = self._transport.send_query(query)
        except (TransportError, NotImplementedError):
            return self._unavailable(query)
        return self._parser.parse(envelope, query=query, bidder_id=bidder_id)

    def _unavailable(self, query: DigiLockerQuery) -> Verification:
        return Verification(
            verification_id=Verification.allocate_id(
                source=self.SOURCE,
                identifier=query.document_access_id,
                call_id=query.call_id,
            ),
            bidder_id=query.bidder_id,
            capability=Capability.DIGILOCKER,
            source=self.SOURCE,
            queried_identifier=query.document_access_id,
            status=VerificationStatus.UNAVAILABLE,
            data={},
            retrieved_at=datetime.now(UTC),
            query=query.model_dump(),
            raw_response=None,
            latency_ms=None,
            correlation_id=None,
            transport_status_code=None,
        )


__all__ = [
    "DigiLockerAdapter",
    "DigiLockerQuery",
    "DigiLockerResponseEnvelope",
    "DigiLockerResponseParser",
    "NormalizedDigiLockerData",
]