"""Normalized models for procurement blacklist / debarment verification.

This module defines the typed data contract the rest of the
engine consumes for debarment / blacklist / suspension /
procurement-eligibility checks:

* enums for restriction status and restriction type,
* the canonical ``DebarmentQuery`` request envelope,
* ``NormalizedDebarmentData`` (the minimum the rule reads),
* configuration objects for the future HTTPS integration.

The shape is intentionally narrow: the rest of the source payload
stays on ``Verification.raw_response`` and is never interpreted.

Production limitations
----------------------

* No live government endpoint is included. The repository does
  not contain authoritative endpoint / authentication / response
  documentation for an official procurement-blacklist / debarment
  source. The default transport raises ``NotImplementedError``;
  tests inject a static transport.
* ``CLEAR`` means the queried source returned no applicable
  restriction. It does NOT mean "legally eligible everywhere".
  Procurement eligibility depends on the tender's declared
  authority scope and the source's contract, both of which the
  engine preserves verbatim.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Final, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DebarmentRestrictionStatus(StrEnum):
    """Domain restriction status reported by the debarment source.

    * ``CLEAR`` -- the source has no applicable restriction for the
      queried subject (positive "no match" result).
    * ``RESTRICTED`` -- the source has an active or pending
      blacklist / debarment / suspension / procurement-restriction
      record for the queried subject.
    * ``UNKNOWN`` -- the source could not produce a reliable
      conclusion (incomplete payload, ambiguous subject match,
      malformed response, etc.).
    """

    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


class DebarmentRestrictionType(StrEnum):
    """Controlled taxonomy of restriction categories reported by sources."""

    BLACKLIST = "BLACKLIST"
    DEBARMENT = "DEBARMENT"
    SUSPENSION = "SUSPENSION"
    PROCUREMENT_RESTRICTION = "PROCUREMENT_RESTRICTION"
    OTHER = "OTHER"


class SubjectType(StrEnum):
    """What kind of legal subject the source record describes."""

    INDIVIDUAL = "INDIVIDUAL"
    ORGANIZATION = "ORGANIZATION"
    DIRECTOR = "DIRECTOR"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Identifier normalisation helper
# ---------------------------------------------------------------------------


def normalize_identifier(value: Optional[str]) -> Optional[str]:
    """Deterministic, conservative identifier normalization.

    Steps:

    1. ``None`` -> ``None``.
    2. Strip surrounding whitespace.
    3. Collapse internal whitespace runs to single.
    4. Uppercase.

    The function is deliberately conservative: it never rewrites
    PAN / GSTIN / CIN / DIN / LLPIN internals, never strips
    punctuation that is part of the official format, and never
    substitutes one identifier type for another.

    The output is comparable for equality with another value that
    was normalized by the same rules. It is NOT a fuzzy match;
    "similar" identifiers remain distinct.
    """

    if value is None:
        return None
    text = " ".join(value.split()).strip()
    if not text:
        return None
    return text.upper()


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------


class DebarmentQuery(BaseModel):
    """Typed query for a future debarment / blacklist lookup.

    The query carries:

    * the bidder being verified,
    * the primary identifier being looked up (GSTIN / PAN / CIN /
      DIN / LLPIN / name),
    * an optional ``subject_name`` for sources that match on name
      in addition to identifier,
    * the per-call audit ids (see ``GstQuery``).
    """

    model_config = ConfigDict(extra="forbid")

    bidder_id: str = Field(
        ..., description="Bidder whose restriction status is being verified."
    )
    identifier: str = Field(
        ...,
        description=(
            "Primary identifier used for the lookup. May be a GSTIN, "
            "PAN, CIN, DIN, LLPIN, or a name when only name-match "
            "is possible. The matching strategy is recorded on the "
            "normalized response."
        ),
    )
    subject_name: str | None = Field(
        default=None,
        description=(
            "Optional name of the subject being looked up. Carried "
            "in the audit trail even when only an identifier match "
            "is performed."
        ),
    )
    call_id: str = Field(
        default_factory=lambda: uuid4().hex,
        description=(
            "Per-call UUID4 hex. Combined with ``source`` and "
            "``identifier`` to produce a unique "
            "``Verification.verification_id`` even when the "
            "same source + identifier is queried more than once."
        ),
    )
    verification_id: str | None = Field(
        default=None,
        description=(
            "Pre-allocated verification ID, when the engine "
            "already knows the audit ID it wants to attach."
        ),
    )
    correlation_id: str | None = Field(
        default=None,
        description="End-to-end correlation ID, shared with other systems.",
    )
    evaluation_date: Optional[date] = Field(
        default=None,
        description=(
            "Caller-supplied evaluation date. Passed through into "
            "the normalized data and used by the rule to compute "
            "the active-status window. ``None`` means the rule "
            "must use a date supplied in ``Requirement.parameters`` "
            "or fall back to a strict UNKNOWN. The transport never "
            "invokes a machine clock."
        ),
    )


# ---------------------------------------------------------------------------
# Matching strategy (audit-only taxonomy)
# ---------------------------------------------------------------------------


class MatchMethod(StrEnum):
    """How the source record was matched against the queried subject.

    Identifier-based matches are preferred over name-based matches.
    The rule treats ``MatchMethod.INSUFFICIENT_EVIDENCE`` as
    "no legal match established" and never uses it to assert a
    compliance conclusion.
    """

    EXACT_IDENTIFIER = "EXACT_IDENTIFIER"
    NORMALIZED_IDENTIFIER = "NORMALIZED_IDENTIFIER"
    EXACT_NAME = "EXACT_NAME"
    NORMALIZED_NAME = "NORMALIZED_NAME"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


# ---------------------------------------------------------------------------
# Normalized data
# ---------------------------------------------------------------------------


class NormalizedDebarmentData(BaseModel):
    """Minimum normalized data the debarment compliance rule reads.

    All fields below are the ONLY data the rule consumes from
    ``Verification.data``. Anything the source returns beyond these
    fields stays on ``Verification.raw_response`` and is not
    interpreted by the rule.

    Domain semantics
    ----------------

    * ``restriction_status`` is the business restriction status
      (``CLEAR`` / ``RESTRICTED`` / ``UNKNOWN``) as reported by the
      source. It is deliberately distinct from
      ``VerificationStatus``, which encodes the transport-layer
      outcome.
    * ``restriction_type`` is the controlled restriction category.
      ``OTHER`` covers anything not in the controlled vocabulary.
    * ``effective_date`` and ``end_date`` are the source-reported
      dates. ``None`` is preserved as "unknown". The rule computes
      active-status using these plus the caller-supplied
      ``evaluation_date``.
    * ``match_method`` is the deterministic strategy that produced
      the source-side match against the queried subject.
    """

    model_config = ConfigDict(extra="forbid")

    restriction_status: DebarmentRestrictionStatus = Field(
        ...,
        description=(
            "Business restriction status reported by the source: "
            "CLEAR (no applicable restriction), RESTRICTED (a "
            "restriction record exists), or UNKNOWN (ambiguous / "
            "incomplete)."
        ),
    )
    restriction_type: DebarmentRestrictionType | None = Field(
        default=None,
        description=(
            "Controlled restriction category. None when no "
            "restriction applies (CLEAR)."
        ),
    )
    effective_date: Optional[date] = Field(
        default=None,
        description="Date the restriction took effect. None when unreported.",
    )
    end_date: Optional[date] = Field(
        default=None,
        description=(
            "Date the restriction ends. None when the source "
            "did not report one or the restriction is open-ended."
        ),
    )
    issuing_authority: str | None = Field(
        default=None,
        description=(
            "Authority that issued the restriction (e.g. GeM, "
            "CBI, MCA). None when no restriction applies."
        ),
    )
    reference_number: str | None = Field(
        default=None,
        description=(
            "Authority-issued reference number for the restriction "
            "record. None when no restriction applies."
        ),
    )
    source_reference: str | None = Field(
        default=None,
        description=(
            "Opaque, source-supplied reference (URL, docket id, "
            "etc.) pointing back at the original record. Preserved "
            "verbatim."
        ),
    )
    subject_type: SubjectType = Field(
        default=SubjectType.UNKNOWN,
        description="What kind of legal subject the record describes.",
    )
    subject_identifier: str | None = Field(
        default=None,
        description=(
            "Identifier of the subject on the source side, after "
            "the matching strategy was applied. None when no "
            "restriction applies."
        ),
    )
    subject_name_original: str | None = Field(
        default=None,
        description=(
            "Original subject name as reported by the source, "
            "preserved verbatim for audit."
        ),
    )
    subject_name_normalized: str | None = Field(
        default=None,
        description=(
            "Deterministic normalized subject name. None when no "
            "restriction applies or the source did not return one."
        ),
    )
    match_method: MatchMethod = Field(
        default=MatchMethod.INSUFFICIENT_EVIDENCE,
        description=(
            "How the source record was matched against the queried "
            "subject. INSUFFICIENT_EVIDENCE means no legal match "
            "was established."
        ),
    )

    @field_validator("effective_date", "end_date")
    @classmethod
    def _preserve_none_dates(cls, value: Optional[date]) -> Optional[date]:
        """Allow ``None``; Pydantic already rejects non-date values."""
        return value


# ---------------------------------------------------------------------------
# Configuration / credential seam
# ---------------------------------------------------------------------------


DEBARMENT_MIN_TLS_VERSION: Final[str] = "TLSv1_2"


class DebarmentEndpointConfig(BaseModel):
    """HTTPS endpoint configuration for a real debarment source.

    The URL is an opaque reference; this module does not hardcode
    any production or UAT endpoint. When a real transport is
    enabled, the URL MUST be ``https://``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(
        ...,
        description=(
            "HTTPS URL of the debarment / eligibility source. The "
            "exact production / UAT endpoint is agreed at agency "
            "onboarding time and is NOT hardcoded here."
        ),
    )
    timeout_seconds: float = Field(
        default=10.0,
        ge=0.1,
        description="Total request timeout, in seconds.",
    )
    min_tls_version: str = Field(
        default=DEBARMENT_MIN_TLS_VERSION,
        description=(
            "Minimum TLS version the client requires. Defaults to "
            "TLSv1_2; the value is preserved for audit, not enforced "
            "by this milestone."
        ),
    )

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        if value and not value.lower().startswith("https://"):
            raise ValueError(
                "Debarment endpoint must be HTTPS. Plain-HTTP callers "
                "are rejected so the eligibility check can never be "
                "performed over an unauthenticated channel."
            )
        return value


class DebarmentClientCredentials(BaseModel):
    """Opaque references to per-tenant client credentials."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id_ref: str = Field(
        ...,
        description=(
            "Opaque reference (e.g. environment-variable name) to "
            "the issued client id. The actual value is never "
            "stored in this object."
        ),
    )
    client_secret_ref: str = Field(
        ...,
        description=(
            "Opaque reference (e.g. environment-variable name) to "
            "the issued client secret. The actual value is never "
            "stored in this object."
        ),
    )

    @field_validator("client_id_ref", "client_secret_ref")
    @classmethod
    def _no_empty_refs(cls, value: str) -> str:
        if value is None or not value.strip():
            raise ValueError(
                "Client-credential reference must be a non-empty "
                "opaque name (e.g. an env-var name)."
            )
        return value.strip()


class DebarmentConfig(BaseModel):
    """Top-level configuration object for a real debarment integration.

    Constructed when a real transport is wired in.
    ``validate_for_real_use`` MUST be called before the real
    transport is used so incomplete configuration fails fast.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: DebarmentEndpointConfig
    client: DebarmentClientCredentials

    def validate_for_real_use(self) -> None:
        """Reject obviously incomplete configuration."""
        missing: list[str] = []
        if not self.endpoint.url:
            missing.append("endpoint.url")
        if not self.client.client_id_ref:
            missing.append("client.client_id_ref")
        if not self.client.client_secret_ref:
            missing.append("client.client_secret_ref")
        if missing:
            raise ValueError(
                "DebarmentConfig is incomplete for real transport use; "
                "missing required references: " + ", ".join(missing)
            )


# ---------------------------------------------------------------------------
# Source identity constants
# ---------------------------------------------------------------------------


DEBARMENT_SOURCE: Final[str] = "DEBARMENT_REGISTRY"
DEBARMENT_CAPABILITY: Final[str] = "PROCUREMENT_ELIGIBILITY"


__all__ = [
    "DEBARMENT_CAPABILITY",
    "DEBARMENT_MIN_TLS_VERSION",
    "DEBARMENT_SOURCE",
    "DebarmentClientCredentials",
    "DebarmentConfig",
    "DebarmentEndpointConfig",
    "DebarmentQuery",
    "DebarmentRestrictionStatus",
    "DebarmentRestrictionType",
    "MatchMethod",
    "NormalizedDebarmentData",
    "SubjectType",
    "normalize_identifier",
]
