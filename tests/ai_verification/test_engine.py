from datetime import UTC

from ai_verification import VerificationEngine
from ai_verification.models import VerificationInput, VerificationResult


def test_engine_returns_verification_result() -> None:
    input_data = VerificationInput(bidder_id="bidder-1")
    result = VerificationEngine().run(input_data)

    assert isinstance(result, VerificationResult)
    assert result.bidder_id == "bidder-1"
    assert result.findings == []
    assert result.generated_at.tzinfo == UTC


def test_engine_does_not_mutate_input() -> None:
    input_data = VerificationInput(bidder_id="bidder-1")

    before = input_data.model_dump()
    VerificationEngine().run(input_data)
    after = input_data.model_dump()

    assert after == before
