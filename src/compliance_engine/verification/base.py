"""Generic interface for authoritative verification providers."""

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Final

from compliance_engine.models import Verification, VerificationStatus


class VerificationProvider(ABC):
    """Look up an identifier against an authoritative source.

    Implementations must not evaluate tender rules, raise flags, or decide
    PASS/FAIL. They only return a ``Verification`` record.
    """

    @abstractmethod
    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        """Query the source for ``identifier`` belonging to ``bidder_id``."""


class MockGSTProvider(VerificationProvider):
    """In-memory GST lookup for tests. Does not call any network API."""

    SOURCE: Final[str] = "GSTN_MOCK"
    CAPABILITY: Final[str] = "GST"
    RETRIEVED_AT: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)

    GSTIN_VERIFIED: Final[str] = "27AAACI1234F1Z5"
    GSTIN_NOT_FOUND: Final[str] = "27AAAAA0000A1Z5"
    GSTIN_INVALID: Final[str] = "27XXXXX9999X1Z5"
    GSTIN_INACTIVE: Final[str] = "27AAACI9999F1Z5"
    GSTIN_NAME_MISMATCH: Final[str] = "29OTHERS1234F1Z5"

    _RECORDS: Final[dict[str, tuple[VerificationStatus, dict[str, Any]]]] = {
        GSTIN_VERIFIED: (
            VerificationStatus.VERIFIED,
            {
                "registration_status": "ACTIVE",
                "legal_name": "ACME ENTERPRISES PRIVATE LIMITED",
            },
        ),
        GSTIN_NOT_FOUND: (VerificationStatus.NOT_FOUND, {}),
        GSTIN_INVALID: (VerificationStatus.INVALID, {}),
        GSTIN_INACTIVE: (
            VerificationStatus.INACTIVE,
            {
                "registration_status": "INACTIVE",
                "legal_name": "ACME ENTERPRISES PRIVATE LIMITED",
            },
        ),
        GSTIN_NAME_MISMATCH: (
            VerificationStatus.VERIFIED,
            {
                "registration_status": "ACTIVE",
                "legal_name": "OTHER BIDDER PRIVATE LIMITED",
            },
        ),
    }

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        """Return the canned GSTN record for ``identifier``, if any."""

        status, data = self._RECORDS.get(
            identifier, (VerificationStatus.NOT_FOUND, {})
        )
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
