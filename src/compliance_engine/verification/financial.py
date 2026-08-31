"""Deterministic Financial Capacity verification provider for tests.

This is intentionally test-only and is not a real government or MCA adapter.
Any future real verification integration should live in a separate provider
implementation outside this module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from compliance_engine.models import Capability, Verification, VerificationStatus
from compliance_engine.verification.base import VerificationProvider


class MockFinancialProvider(VerificationProvider):
    """In-memory financial capacity lookup for deterministic tests."""

    SOURCE: Final[str] = "FINANCIAL_MOCK"
    CAPABILITY: Final[Capability] = Capability.FINANCIAL
    RETRIEVED_AT: Final[datetime] = datetime(2026, 1, 1, tzinfo=UTC)

    # Test data: turnover amounts (in currency units)
    TURNOVER_VERIFIED: Final[str] = "5000000"  # 50 lakh
    TURNOVER_NOT_FOUND: Final[str] = "0"
    TURNOVER_INVALID: Final[str] = "-1000"
    TURNOVER_BELOW_THRESHOLD: Final[str] = "500000"  # 5 lakh (below typical thresholds)
    TURNOVER_MEETS_THRESHOLD: Final[str] = "2500000"  # 25 lakh

    _RECORDS: Final[dict[str, tuple[VerificationStatus, dict[str, Any]]]] = {
        TURNOVER_VERIFIED: (
            VerificationStatus.VERIFIED,
            {
                "turnover": 5000000,
                "financial_year": 2023,
                "net_worth": 2000000,
                "audited_status": "AUDITED",
                "data_source": "FINANCIAL_MOCK",
            },
        ),
        TURNOVER_NOT_FOUND: (VerificationStatus.NOT_FOUND, {}),
        TURNOVER_INVALID: (VerificationStatus.INVALID, {}),
        TURNOVER_BELOW_THRESHOLD: (
            VerificationStatus.VERIFIED,
            {
                "turnover": 500000,
                "financial_year": 2023,
                "net_worth": 100000,
                "audited_status": "AUDITED",
                "data_source": "FINANCIAL_MOCK",
            },
        ),
        TURNOVER_MEETS_THRESHOLD: (
            VerificationStatus.VERIFIED,
            {
                "turnover": 2500000,
                "financial_year": 2023,
                "net_worth": 1000000,
                "audited_status": "AUDITED",
                "data_source": "FINANCIAL_MOCK",
            },
        ),
    }

    def verify(self, bidder_id: str, identifier: str, **kwargs: Any) -> Verification:
        """Return the canned financial record for ``identifier`` (turnover), if known."""

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
