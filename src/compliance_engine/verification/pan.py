"""Deterministic PAN verification provider for tests and rule evaluation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from compliance_engine.models import Verification, VerificationStatus
from compliance_engine.verification.base import VerificationProvider


class MockPANProvider(VerificationProvider):
    """In-memory PAN lookup for deterministic tests."""

    SOURCE: Final[str] = "PAN_MOCK"
    CAPABILITY: Final[str] = "PAN"
    RETRIEVED_AT: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)

    PAN_VERIFIED: Final[str] = "AAACI1234F"
    PAN_NOT_FOUND: Final[str] = "AAABBB0000C"
    PAN_INVALID: Final[str] = "ABCDE1234F"
    PAN_INACTIVE: Final[str] = "AAACI9999F"
    PAN_NAME_MISMATCH: Final[str] = "AAACI4321F"

    _RECORDS: Final[dict[str, tuple[VerificationStatus, dict[str, Any]]]] = {
        PAN_VERIFIED: (
            VerificationStatus.VERIFIED,
            {
                "name_on_pan": "ACME ENTERPRISES PRIVATE LIMITED",
                "pan_status": "ACTIVE",
            },
        ),
        PAN_NOT_FOUND: (VerificationStatus.NOT_FOUND, {}),
        PAN_INVALID: (VerificationStatus.INVALID, {}),
        PAN_INACTIVE: (
            VerificationStatus.INACTIVE,
            {
                "name_on_pan": "ACME ENTERPRISES PRIVATE LIMITED",
                "pan_status": "INACTIVE",
            },
        ),
        PAN_NAME_MISMATCH: (
            VerificationStatus.VERIFIED,
            {
                "name_on_pan": "OTHER BIDDER PRIVATE LIMITED",
                "pan_status": "ACTIVE",
            },
        ),
    }

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        """Return the canned PAN record for ``identifier`` if known."""

        status, data = self._RECORDS.get(identifier, (VerificationStatus.NOT_FOUND, {}))
        return Verification(
            verification_id=f"{self.SOURCE}:{identifier}",
            bidder_id=bidder_id,
            capability=self.CAPABILITY,
            source=self.SOURCE,
            queried_identifier=identifier,
            status=status,
            data=dict(data),
            retrieved_at=self.RETRIEVED_AT,
        )
