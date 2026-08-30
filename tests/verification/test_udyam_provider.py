from compliance_engine.models import Verification, VerificationStatus
from compliance_engine.verification import MockUdyamProvider


def test_provider_verified_active_udyam() -> None:
    result = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_VERIFIED)
    assert isinstance(result, Verification)
    assert result.status is VerificationStatus.VERIFIED
    assert result.capability == "UDYAM"
    assert result.data["registration_status"] == "ACTIVE"
    assert result.data["enterprise_name"] == "ACME ENTERPRISES PRIVATE LIMITED"
    assert result.data["enterprise_category"] == "Medium"


def test_provider_not_found_udyam() -> None:
    result = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_NOT_FOUND)
    assert result.status is VerificationStatus.NOT_FOUND
    assert result.source == "UDYAM_MOCK"


def test_provider_invalid_udyam() -> None:
    result = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_INVALID)
    assert result.status is VerificationStatus.INVALID


def test_provider_inactive_udyam() -> None:
    result = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_INACTIVE)
    assert result.status is VerificationStatus.INACTIVE
    assert result.data["registration_status"] == "INACTIVE"


def test_provider_name_mismatch_udyam_is_verified() -> None:
    result = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_NAME_MISMATCH)
    assert result.status is VerificationStatus.VERIFIED
    assert result.data["enterprise_name"] == "OTHER BIDDER PRIVATE LIMITED"


def test_provider_category_mismatch_udyam_is_verified() -> None:
    result = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_CATEGORY_MISMATCH)
    assert result.status is VerificationStatus.VERIFIED
    assert result.data["enterprise_category"] == "Micro"


def test_provider_is_deterministic() -> None:
    first = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_VERIFIED)
    second = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_VERIFIED)
    assert first.verification_id == second.verification_id
    assert first.retrieved_at == second.retrieved_at
    assert first.data == second.data


def test_provider_returns_verification_model() -> None:
    result = MockUdyamProvider().verify("bidder_acme_01", MockUdyamProvider.UDYAM_VERIFIED)
    assert result.model_dump()["status"] == VerificationStatus.VERIFIED
    assert result.retrieved_at.tzinfo is not None
