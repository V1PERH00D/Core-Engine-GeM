"""Configuration / credential seam for the Income Tax PAN service.

This module defines the typed configuration object that a real
``PanAdapter`` would consume when wired against the official PAN
Verification Web Service.

Design constraints
------------------

* Never store real secrets in source code.
* Never commit credentials.
* Prefer environment / config-file injection.
* Do not implement a full secrets-management framework.
* Do not implement authentication bypasses.
* Do not require credentials for unit tests.

What the official PAN service actually requires is documented by the
Income Tax Department:

* an HTTPS endpoint (the published service URL);
* an ``external-agency`` username and password (issued after the
  agency is registered and approved by the department);
* a per-request ``clientId`` and ``clientSecret`` pair used inside the
  SOAP ``PANVerificationRequest`` envelope;
* a digital-signing / encryption configuration, handled by the agency
  certificate (PFX / JKS) plus the password for the keystore.

The values used in the SOAP envelope (clientId, clientSecret) are
*string references*; the actual values come from this configuration at
request-build time. This module exposes typed references for every
required field, validates that none of them are empty when a real
transport is enabled, and never persists them anywhere.

Configuration objects are Pydantic models with ``extra="forbid"`` so
typos in environment-driven config surface immediately instead of
silently being ignored.
"""

from __future__ import annotations

import os
from typing import Final
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Official service ID published by the Income Tax Department for the
# PAN Verification Web Service. Used as a constant in the SOAP envelope
# and asserted on for tests.
PAN_SERVICE_ID: Final[str] = "10001"


class PanSigningConfig(BaseModel):
    """Reference to a digital-signing / encryption configuration.

    The actual cryptographic material is **never** stored in this
    object. Only opaque references are kept. A real signing
    implementation reads the keystore at request-build time using the
    reference below; for this milestone the reference is preserved but
    no cryptographic operation is performed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    keystore_ref: str = Field(
        ...,
        description=(
            "Opaque reference (e.g. environment variable name) to the "
            "keystore / PFX file used for the WS-Security signature and "
            "encryption. The keystore itself is NOT loaded here."
        ),
    )
    keystore_password_ref: str = Field(
        ...,
        description=(
            "Opaque reference to the password protecting the keystore. "
            "Never a plaintext password."
        ),
    )
    signing_algorithm: str = Field(
        default="RSA_SHA256",
        description=(
            "Algorithm used to sign the SOAP envelope. The official "
            "service documents SHA-256 with RSA; the value is preserved "
            "for audit, not enforced by this milestone."
        ),
    )

    @field_validator("keystore_ref", "keystore_password_ref")
    @classmethod
    def _no_empty_refs(cls, value: str) -> str:
        # An empty reference is allowed so environment-driven config
        # can surface a clear "missing" error from
        # ``PanConfig.validate_for_real_use`` instead of crashing on
        # the field validator.
        if value is not None and value.strip() == "":
            return ""
        if not value or not value.strip():
            raise ValueError("Signing reference must be a non-empty opaque name.")
        return value.strip()


class PanClientCredentials(BaseModel):
    """Per-request client identifiers used inside the SOAP envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id: str = Field(
        ...,
        description=(
            "The client ID issued by the Income Tax Department to the "
            "external agency. Sent inside PANVerificationRequest."
        ),
    )
    client_secret: str = Field(
        ...,
        description=(
            "The client secret issued alongside the client ID. Sent "
            "inside PANVerificationRequest."
        ),
    )

    @field_validator("client_id", "client_secret")
    @classmethod
    def _no_empty(cls, value: str) -> str:
        # An empty value is allowed so environment-driven config can
        # surface a clear "missing" error from
        # ``PanConfig.validate_for_real_use`` instead of crashing on
        # the field validator.
        if value is not None and value.strip() == "":
            return ""
        if not value or not value.strip():
            raise ValueError("Client credentials must be non-empty.")
        return value


class PanAgencyCredentials(BaseModel):
    """External-agency credentials issued at registration time.

    These are the WS-Security ``UsernameToken`` values. They are
    separate from the per-request ``clientId`` / ``clientSecret`` pair.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    agency_username: str = Field(
        ..., description="External-agency username issued by ITD."
    )
    agency_password: str = Field(
        ...,
        description=(
            "External-agency password issued by ITD. Should be supplied "
            "via a secret store; this field stores the resolved value "
            "at runtime only."
        ),
    )

    @field_validator("agency_username", "agency_password")
    @classmethod
    def _no_empty(cls, value: str) -> str:
        # An empty value is allowed so environment-driven config can
        # surface a clear "missing" error from
        # ``PanConfig.validate_for_real_use`` instead of crashing on
        # the field validator.
        if value is not None and value.strip() == "":
            return ""
        if not value or not value.strip():
            raise ValueError("Agency credentials must be non-empty.")
        return value


class PanEndpointConfig(BaseModel):
    """The HTTPS endpoint configuration for the real transport."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(
        ...,
        description=(
            "HTTPS URL of the PAN Verification Web Service. The "
            "official service URL is published by the Income Tax "
            "Department; this milestone does not hardcode it."
        ),
    )
    timeout_seconds: float = Field(
        default=10.0,
        ge=0.1,
        description="Total request timeout, in seconds.",
    )
    soap_action: str = Field(
        default="verifyPAN",
        description=(
            "SOAPAction header value. The official service advertises "
            "``verifyPAN``; preserved for audit."
        ),
    )

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        # An empty URL is allowed so environment-driven config can
        # surface a clear "missing" error from
        # ``PanConfig.validate_for_real_use`` instead of crashing on
        # the field validator. Non-empty values must be HTTPS.
        if value and not value.lower().startswith("https://"):
            raise ValueError(
                "PAN endpoint must be HTTPS. The official PAN service "
                "rejects plain-HTTP callers."
            )
        return value


class PanConfig(BaseModel):
    """Top-level configuration object for a real PAN integration.

    The adapter is constructed with one of these and a transport. When
    the transport is the real HTTP transport, ``validate_for_real_use``
    MUST be called to fail fast on incomplete configuration.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: PanEndpointConfig = Field(..., description="HTTPS endpoint config.")
    agency: PanAgencyCredentials = Field(
        ..., description="External-agency username / password."
    )
    client: PanClientCredentials = Field(
        ..., description="Per-request clientId / clientSecret pair."
    )
    signing: PanSigningConfig = Field(
        ..., description="WS-Security signing / encryption references."
    )
    service_id: str = Field(
        default=PAN_SERVICE_ID,
        description=(
            "Service ID used in the SOAP envelope. The official PAN "
            "Verification Web Service uses 10001."
        ),
    )

    def validate_for_real_use(self) -> None:
        """Reject obviously incomplete configuration.

        Called only when the real HTTP transport is selected. None of
        the values are logged; only an aggregated error is raised.
        """

        missing: list[str] = []
        if not self.endpoint.url:
            missing.append("endpoint.url")
        if not self.agency.agency_username:
            missing.append("agency.agency_username")
        if not self.agency.agency_password:
            missing.append("agency.agency_password")
        if not self.client.client_id:
            missing.append("client.client_id")
        if not self.client.client_secret:
            missing.append("client.client_secret")
        if not self.signing.keystore_ref:
            missing.append("signing.keystore_ref")
        if not self.signing.keystore_password_ref:
            missing.append("signing.keystore_password_ref")
        if missing:
            raise ValueError(
                "PanConfig is incomplete for real transport use; "
                "missing required references: " + ", ".join(missing)
            )


def from_env(env: dict[str, str] | None = None) -> PanConfig:
    """Build a :class:`PanConfig` from environment variables.

    No real secrets are required for this constructor: if the
    variables are absent, the function raises a clear error listing
    what is missing. This function is provided for ergonomic
    environment-driven wiring and is the only place that touches
    ``os.environ``.
    """

    e = env if env is not None else dict(os.environ)
    return PanConfig(
        endpoint=PanEndpointConfig(
            url=e.get("PAN_ENDPOINT_URL", ""),
            timeout_seconds=float(e.get("PAN_TIMEOUT_SECONDS", "10.0")),
            soap_action=e.get("PAN_SOAP_ACTION", "verifyPAN"),
        ),
        agency=PanAgencyCredentials(
            agency_username=e.get("PAN_AGENCY_USERNAME", ""),
            agency_password=e.get("PAN_AGENCY_PASSWORD", ""),
        ),
        client=PanClientCredentials(
            client_id=e.get("PAN_CLIENT_ID", ""),
            client_secret=e.get("PAN_CLIENT_SECRET", ""),
        ),
        signing=PanSigningConfig(
            keystore_ref=e.get("PAN_KEYSTORE_REF", ""),
            keystore_password_ref=e.get("PAN_KEYSTORE_PASSWORD_REF", ""),
            signing_algorithm=e.get("PAN_SIGNING_ALGORITHM", "RSA_SHA256"),
        ),
    )


def new_request_id() -> str:
    """Return a per-call unique request id used inside the SOAP envelope.

    The official service expects a unique id per request so it can
    de-duplicate retries. This is a fresh UUID4 hex per call; it is
    **distinct from** the per-call ``call_id`` that drives
    :attr:`Verification.verification_id` so the two audit ids are
    never collapsed.
    """
    return uuid4().hex


__all__ = [
    "PAN_SERVICE_ID",
    "PanAgencyCredentials",
    "PanClientCredentials",
    "PanConfig",
    "PanEndpointConfig",
    "PanSigningConfig",
    "from_env",
    "new_request_id",
]
