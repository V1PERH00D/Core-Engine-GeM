"""Failure classification and deterministic retry policy.

Processing failures and compliance outcomes are different concepts:
a failed job must never be converted into a compliance ``FAIL``, and a
provider outage must never masquerade as missing evidence. Only
transient infrastructure failures and provider-unavailable failures
are retryable; programming errors are never retried automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class FailureKind(StrEnum):
    """Classification of a processing failure."""

    TRANSIENT_INFRASTRUCTURE = "TRANSIENT_INFRASTRUCTURE"
    """Network blip, connection reset, Redis/Postgres momentarily down."""

    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    """An authoritative verification provider is down or timed out."""

    MALFORMED_DOMAIN_DATA = "MALFORMED_DOMAIN_DATA"
    """Input artefact is structurally unusable (bad JSON, wrong shape)."""

    PERMANENT_VALIDATION = "PERMANENT_VALIDATION"
    """Input failed validation and retrying can never change the outcome."""

    PROGRAMMING_ERROR = "PROGRAMMING_ERROR"
    """A bug: TypeError/AttributeError/assertion failures etc."""


#: Kinds whose retry is meaningful.
RETRYABLE_KINDS: frozenset[FailureKind] = frozenset(
    {FailureKind.TRANSIENT_INFRASTRUCTURE, FailureKind.PROVIDER_UNAVAILABLE}
)


class ProcessingError(Exception):
    """Domain-meaningful processing failure with an explicit kind."""

    def __init__(
        self,
        message: str,
        *,
        kind: FailureKind = FailureKind.TRANSIENT_INFRASTRUCTURE,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.cause = cause


class ProviderUnavailableError(ProcessingError):
    """An authoritative provider could not be reached or was unavailable.

    Retryable. Must never be reinterpreted as a domain compliance
    outcome (e.g. not converted into a compliance ``FAIL``).
    """

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(
            message, kind=FailureKind.PROVIDER_UNAVAILABLE, cause=cause
        )


class PermanentValidationError(ProcessingError):
    """Input failed validation; retrying cannot change the outcome."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(
            message, kind=FailureKind.PERMANENT_VALIDATION, cause=cause
        )


def classify_failure(exc: BaseException) -> FailureKind:
    """Classify an exception into a :class:`FailureKind`.

    Deterministic mapping; unknown exception types are treated as
    programming errors so they are *not* retried blindly.
    """

    if isinstance(exc, ProcessingError):
        return exc.kind
    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return FailureKind.TRANSIENT_INFRASTRUCTURE
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        return FailureKind.PERMANENT_VALIDATION
    if isinstance(exc, ValueError):
        return FailureKind.MALFORMED_DOMAIN_DATA
    return FailureKind.PROGRAMMING_ERROR
@dataclass(frozen=True)
class RetryPolicy:
    """Deterministic retry policy (no jitter, reproducible)."""

    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    multiplier: float = 2.0
    max_delay_seconds: float = 60.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.base_delay_seconds < 0:
            raise ValueError("base_delay_seconds must be >= 0")
        if self.multiplier < 1.0:
            raise ValueError("multiplier must be >= 1.0")

    def delay_for_attempt(self, attempt: int) -> float:
        """Delay before retry number ``attempt`` (1-based, capped)."""
        if attempt < 1:
            raise ValueError("attempt must be >= 1")
        delay = self.base_delay_seconds * (self.multiplier ** (attempt - 1))
        return min(delay, self.max_delay_seconds)


@dataclass(frozen=True)
class FailureDecision:
    """Outcome of classifying one job failure."""

    kind: FailureKind
    retryable: bool
    retry_delay_seconds: float
    message: str


def decide_failure(
    exc: BaseException,
    *,
    attempt: int,
    policy: RetryPolicy | None = None,
) -> FailureDecision:
    """Combine classification and policy into a retry decision.

    ``attempt`` is the attempt that just failed (1-based). A retryable
    failure is only retryable while another attempt remains under
    ``policy.max_attempts``.
    """

    policy = policy or RetryPolicy()
    kind = classify_failure(exc)
    retryable = kind in RETRYABLE_KINDS and attempt < policy.max_attempts
    delay = policy.delay_for_attempt(attempt) if retryable else 0.0
    return FailureDecision(
        kind=kind,
        retryable=retryable,
        retry_delay_seconds=delay,
        message=str(exc),
    )


__all__ = [
    "FailureDecision",
    "FailureKind",
    "PermanentValidationError",
    "ProcessingError",
    "ProviderUnavailableError",
    "RETRYABLE_KINDS",
    "RetryPolicy",
    "classify_failure",
    "decide_failure",
]
