"""Deterministic Udyam registration verification provider for tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from compliance_engine.models import Verification, VerificationStatus
from compliance_engine.verification.base import VerificationProvider


class MockUdyamProvider(VerificationProvider):
    """In-memory Udyam lookup for deterministic tests."""

    SOURCE: Final[str] = "UDYAM_MOCK"
    CAPABILITY: Final[str] = "UDYAM"
    RETRIEVED_AT: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)

    UDYAM_VERIFIED: Final[str] = "UDYAM-MH-12-0019842"
    UDYAM_NOT_FOUND: Final[str] = "UDYAM-MH-12-9999999"
    UDYAM_INVALID: Final[str] = "UDYAM-INVALID-123"
    UDYAM_INACTIVE: Final[str] = "UDYAM-MH-12-0019843"
    UDYAM_NAME_MISMATCH: Final[str] = "UDYAM-MH-12-0019844"
    UDYAM_CATEGORY_MISMATCH: Final[str] = "UDYAM-MH-12-0019845"

    _RECORDS: Final[dict[str, tuple[VerificationStatus, dict[str, Any]]]] = {
        UDYAM_VERIFIED: (
            VerificationStatus.VERIFIED,
            {
                "registration_status": "ACTIVE",
                "enterprise_name": "ACME ENTERPRISES PRIVATE LIMITED",
                "enterprise_category": "Medium",
            },
        ),
        UDYAM_NOT_FOUND: (VerificationStatus.NOT_FOUND, {}),
        UDYAM_INVALID: (VerificationStatus.INVALID, {}),
        UDYAM_INACTIVE: (
            VerificationStatus.INACTIVE,
            {
                "registration_status": "INACTIVE",
                "enterprise_name": "ACME ENTERPRISES PRIVATE LIMITED",
                "enterprise_category": "Medium",
            },
        ),
        UDYAM_NAME_MISMATCH: (
            VerificationStatus.VERIFIED,
            {
                "registration_status": "ACTIVE",
                "enterprise_name": "OTHER BIDDER PRIVATE LIMITED",
                "enterprise_category": "Medium",
            },
        ),
        UDYAM_CATEGORY_MISMATCH: (
            VerificationStatus.VERIFIED,
            {
                "registration_status": "ACTIVE",
                "enterprise_name": "ACME ENTERPRISES PRIVATE LIMITED",
                "enterprise_category": "Micro",
            },
        ),
    }

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        """Return the canned Udyam record for ``identifier``, if known."""

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
