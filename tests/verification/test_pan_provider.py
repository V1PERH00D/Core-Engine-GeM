from datetime import UTC, datetime

from compliance_engine.models import Capability, Verification, VerificationStatus
from compliance_engine.verification import MockPANProvider


def test_provider_verifies_active_pan() -> None:
    result = MockPANProvider().verify("bidder_acme_01", MockPANProvider.PAN_VERIFIED)
    assert isinstance(result, Verification)
    assert result.status is VerificationStatus.VERIFIED
    assert result.capability == Capability.PAN_INCOME_TAX
    assert result.data["pan_status"] == "ACTIVE"
    assert result.data["name_on_pan"] == "ACME ENTERPRISES PRIVATE LIMITED"


def test_provider_not_found_pan() -> None:
    result = MockPANProvider().verify("bidder_acme_01", MockPANProvider.PAN_NOT_FOUND)
    assert result.status is VerificationStatus.NOT_FOUND
    assert result.source == "PAN_MOCK"


def test_provider_invalid_pan() -> None:
    result = MockPANProvider().verify("bidder_acme_01", MockPANProvider.PAN_INVALID)
    assert result.status is VerificationStatus.INVALID


def test_provider_inactive_pan() -> None:
    result = MockPANProvider().verify("bidder_acme_01", MockPANProvider.PAN_INACTIVE)
    assert result.status is VerificationStatus.INACTIVE
    assert result.data["pan_status"] == "INACTIVE"


def test_provider_name_mismatch_pan_still_verifies() -> None:
    result = MockPANProvider().verify("bidder_acme_01", MockPANProvider.PAN_NAME_MISMATCH)
    assert result.status is VerificationStatus.VERIFIED
    assert result.data["name_on_pan"] == "OTHER BIDDER PRIVATE LIMITED"


def test_provider_is_deterministic() -> None:
    first = MockPANProvider().verify("bidder_acme_01", MockPANProvider.PAN_VERIFIED)
    second = MockPANProvider().verify("bidder_acme_01", MockPANProvider.PAN_VERIFIED)
    assert first.verification_id == second.verification_id
    assert first.retrieved_at == second.retrieved_at
    assert first.data == second.data


def test_provider_returns_verification_model() -> None:
    result = MockPANProvider().verify("bidder_acme_01", MockPANProvider.PAN_VERIFIED)
    assert result.model_dump()["status"] == VerificationStatus.VERIFIED
    assert result.retrieved_at.tzinfo == UTC
