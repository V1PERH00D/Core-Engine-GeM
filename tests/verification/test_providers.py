from compliance_engine.models import Capability, Verification, VerificationStatus
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
    assert result.capability == Capability.GST
    assert result.queried_identifier == MockGSTProvider.GSTIN_VERIFIED


# ---------------------------------------------------------------------------
# Provider audit-field contract tests
# ---------------------------------------------------------------------------


def test_provider_populates_all_known_audit_fields() -> None:
    """The representative provider must populate the audit fields it has
    genuine information about: ``verification_id``, ``bidder_id``,
    ``capability``, ``source``, ``queried_identifier``, ``status``,
    ``data``, ``retrieved_at``.
    """
    result = MockGSTProvider().verify("bidder_acme_01", MockGSTProvider.GSTIN_VERIFIED)
    assert result.verification_id == "GSTN_MOCK:27AAACI1234F1Z5"
    assert result.bidder_id == "bidder_acme_01"
    assert result.capability == Capability.GST
    assert result.source == "GSTN_MOCK"
    assert result.queried_identifier == MockGSTProvider.GSTIN_VERIFIED
    assert result.status is VerificationStatus.VERIFIED
    assert result.data == {
        "registration_status": "ACTIVE",
        "legal_name": "ACME ENTERPRISES PRIVATE LIMITED",
    }
    # retrieved_at must be a tz-aware datetime.
    assert result.retrieved_at.tzinfo is not None


def test_provider_does_not_fabricate_optional_audit_fields() -> None:
    """Fields the current mock cannot legitimately know
    (``evidence_id``, ``document_id``, ``query``, ``raw_response``,
    ``latency_ms``, ``correlation_id``) must be ``None``, not invented.
    """
    result = MockGSTProvider().verify("bidder_acme_01", MockGSTProvider.GSTIN_VERIFIED)
    assert result.evidence_id is None
    assert result.document_id is None
    assert result.query is None
    assert result.raw_response is None
    assert result.latency_ms is None
    assert result.correlation_id is None


def test_provider_verification_id_is_present_and_stable() -> None:
    """The verification_id must be present on every provider result and
    must be deterministic for the same identifier.
    """
    provider = MockGSTProvider()
    v1 = provider.verify("bidder_1", MockGSTProvider.GSTIN_VERIFIED)
    v2 = provider.verify("bidder_1", MockGSTProvider.GSTIN_VERIFIED)
    assert v1.verification_id
    assert v1.verification_id == v2.verification_id


def test_provider_preserves_failure_status_distinctly() -> None:
    """NOT_FOUND, INVALID, and INACTIVE statuses must be preserved
    exactly by the provider so the rule layer can interpret them
    deterministically. UNAVAILABLE / ERROR are *not* produced by the
    representative mock, but a custom provider must be able to.
    """
    assert MockGSTProvider().verify("b", MockGSTProvider.GSTIN_NOT_FOUND).status is VerificationStatus.NOT_FOUND
    assert MockGSTProvider().verify("b", MockGSTProvider.GSTIN_INVALID).status is VerificationStatus.INVALID
    assert MockGSTProvider().verify("b", MockGSTProvider.GSTIN_INACTIVE).status is VerificationStatus.INACTIVE


def test_provider_does_not_mutate_inputs() -> None:
    """The provider must not mutate any of the input arguments or any
    state on the caller side; it returns a fresh ``Verification``.
    """
    provider = MockGSTProvider()
    identifier = MockGSTProvider.GSTIN_VERIFIED
    before_id = id(identifier)
    result = provider.verify("bidder_1", identifier)
    assert id(identifier) == before_id
    assert result.bidder_id == "bidder_1"

