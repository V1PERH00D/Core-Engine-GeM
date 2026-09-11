"""Failure classification and retry policy."""

import pytest
from pydantic import ValidationError

from infrastructure.errors import (
    FailureKind,
    PermanentValidationError,
    ProcessingError,
    ProviderUnavailableError,
    RetryPolicy,
    classify_failure,
    decide_failure,
)


def test_classify_timeout_transient():
    assert classify_failure(TimeoutError()) is FailureKind.TRANSIENT_INFRASTRUCTURE


def test_classify_connection_transient():
    assert classify_failure(ConnectionError()) is FailureKind.TRANSIENT_INFRASTRUCTURE


def test_classify_oserror_transient():
    assert classify_failure(OSError("down")) is FailureKind.TRANSIENT_INFRASTRUCTURE


def test_classify_validation_permanent():
    from pydantic import BaseModel

    class X(BaseModel):
        a: int

    with pytest.raises(ValidationError) as exc_info:
        X(a="not-int")
    assert classify_failure(exc_info.value) is FailureKind.PERMANENT_VALIDATION


def test_classify_value_error_malformed():
    assert classify_failure(ValueError("x")) is FailureKind.MALFORMED_DOMAIN_DATA


def test_classify_runtime_error_programming():
    assert classify_failure(RuntimeError("x")) is FailureKind.PROGRAMMING_ERROR


def test_provider_unavailable_kind():
    err = ProviderUnavailableError("no provider")
    assert err.kind is FailureKind.PROVIDER_UNAVAILABLE


def test_processing_error_passthrough():
    err = ProcessingError("m", kind=FailureKind.PROVIDER_UNAVAILABLE)
    assert classify_failure(err) is FailureKind.PROVIDER_UNAVAILABLE


def test_decide_failure_retryable_first_attempt():
    d = decide_failure(TimeoutError("timeout"), attempt=1)
    assert d.retryable is True
    assert d.kind is FailureKind.TRANSIENT_INFRASTRUCTURE
    assert d.retry_delay_seconds > 0


def test_decide_failure_attempts_exhausted():
    d = decide_failure(TimeoutError("timeout"), attempt=3)
    assert d.retryable is False


def test_decide_failure_programming_not_retryable():
    d = decide_failure(RuntimeError("bug"), attempt=1)
    assert d.retryable is False


def test_retry_policy_delay_exponential_backoff():
    policy = RetryPolicy(base_delay_seconds=1.0, multiplier=2.0)
    assert policy.delay_for_attempt(1) == 1.0
    assert policy.delay_for_attempt(2) == 2.0
    assert policy.delay_for_attempt(3) == 4.0


def test_retry_policy_delay_capped():
    policy = RetryPolicy(base_delay_seconds=10.0, multiplier=2.0, max_delay_seconds=15.0)
    assert policy.delay_for_attempt(5) == 15.0


def test_retry_policy_validation():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)