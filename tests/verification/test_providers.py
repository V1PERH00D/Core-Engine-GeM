from compliance_engine.models import Verification, VerificationStatus
from compliance_engine.verification import MockGSTProvider, VerificationProvider


def test_verified_result() -> None:
    result = MockGSTProvider().verify("bidder_acme_01", MockGSTProvider.GSTIN_VERIFIED)
    assert result.status is VerificationStatus.VERIFIED
    assert result.data["registration_status"] == "ACTIVE"
    assert result.data["legal_name"] == "ACME ENTERPRISES PRIVATE LIMITED"


def test_not_found_result() -> None:
    result = MockGSTProvider().verify("bidder_acme_01", MockGSTProvider.GSTIN_NOT_FOUND)
    assert result.status is VerificationStatus.NOT_FOUND


def test_invalid_result() -> None:
    result = MockGSTProvider().verify("bidder_acme_01", MockGSTProvider.GSTIN_INVALID)
    assert result.status is VerificationStatus.INVALID


def test_inactive_result() -> None:
    result = MockGSTProvider().verify("bidder_acme_01", MockGSTProvider.GSTIN_INACTIVE)
    assert result.status is VerificationStatus.INACTIVE
    assert result.data["registration_status"] == "INACTIVE"


def test_returned_data_is_deterministic() -> None:
    provider = MockGSTProvider()
    first = provider.verify("bidder_acme_01", MockGSTProvider.GSTIN_VERIFIED)
    second = provider.verify("bidder_acme_01", MockGSTProvider.GSTIN_VERIFIED)
    assert first == second
    assert first.verification_id == f"{MockGSTProvider.SOURCE}:{MockGSTProvider.GSTIN_VERIFIED}"
    assert first.retrieved_at == MockGSTProvider.RETRIEVED_AT


def test_provider_returns_verification_model() -> None:
    provider: VerificationProvider = MockGSTProvider()
    result = provider.verify("bidder_acme_01", MockGSTProvider.GSTIN_VERIFIED)
    assert isinstance(result, Verification)
    assert result.bidder_id == "bidder_acme_01"
    assert result.source == "GSTN_MOCK"
    assert result.capability == "GST"
    assert result.queried_identifier == MockGSTProvider.GSTIN_VERIFIED
