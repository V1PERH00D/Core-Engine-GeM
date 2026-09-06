"""Configuration / credential seam for the future GSTN integration.

This module defines the typed configuration object a real
``GSTNAdapter`` would consume when wired against the official
Goods and Services Tax Network (GSTN) verification service.

Design constraints
------------------

* Never store real secrets in source code.
* Never commit credentials.
* Prefer environment / config-file injection.
* Do not implement a full secrets-management framework.
* Do not implement authentication bypasses.
* Do not require credentials for unit tests.

What the official GSTN service actually requires is documented
publicly only at a coarse level; the production integration
details (exact endpoint URL, exact auth scheme, exact request /
response fields) are agreed at agency-onboarding time and are
NOT hardcoded here. This module exposes typed *references* for
the configuration fields a real GSTN integration will need, and
validates that none of them are empty when a real transport is
enabled.

Configuration objects are Pydantic models with
``extra="forbid"`` so typos in environment-driven config surface
immediately instead of silently being ignored.
"""

from __future__ import annotations

import os
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, field_validator


GST_ENV_UAT: Final[str] = "UAT"
GST_ENV_PRODUCTION: Final[str] = "PRODUCTION"
_GST_ALLOWED_ENVS: Final[tuple[str, ...]] = (GST_ENV_UAT, GST_ENV_PRODUCTION)


class GstEndpointConfig(BaseModel):
    """HTTPS endpoint configuration for the GSTN service.

    The URL is an opaque reference; this milestone does not
    hardcode any production or UAT endpoint. When the real
    transport is enabled, the URL **must** be ``https://``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(
        ...,
        description=(
            "HTTPS URL of the GSTN verification service. The exact "
            "production / UAT endpoint is agreed at agency "
            "onboarding time and is NOT hardcoded here."
        ),
    )
    timeout_seconds: float = Field(
        default=10.0,
        ge=0.1,
        description="Total request timeout, in seconds.",
    )
    environment: str = Field(
        default=GST_ENV_UAT,
        description=(
            "Environment selector. One of "
            f"{_GST_ALLOWED_ENVS!r}. Defaults to UAT to keep "
            "real-mode wiring safe until production is explicitly "
            "enabled."
        ),
    )

    @field_validator("url")
    @classmethod
    def _https_only(cls, value: str) -> str:
        # An empty URL is allowed so environment-driven config can
        # surface a clear "missing" error from
        # ``GstConfig.validate_for_real_use`` instead of crashing on
        # the field validator. Non-empty values must be HTTPS.
        if value and not value.lower().startswith("https://"):
            raise ValueError(
                "GSTN endpoint must be HTTPS. The official GSTN "
                "service rejects plain-HTTP callers."
            )
        return value

    @field_validator("environment")
    @classmethod
    def _env_known(cls, value: str) -> str:
        if value not in _GST_ALLOWED_ENVS:
            raise ValueError(
                "GSTN environment must be one of "
                f"{_GST_ALLOWED_ENVS!r}; got {value!r}."
            )
        return value


class GstClientCredentials(BaseModel):
    """Opaque references to per-tenant client credentials.

    These are the values a future real GSTN integration would
    include in its signed request envelope. The actual values
    are **never** stored in this object - only opaque references
    (typically environment-variable names) so the secret store
    remains the single source of truth.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    client_id_ref: str = Field(
        ...,
        description=(
            "Opaque reference (e.g. environment variable name) to "
            "the client ID issued by the GSTN. The actual value is "
            "NOT loaded here."
        ),
    )
    client_secret_ref: str = Field(
        ...,
        description=(
            "Opaque reference to the client secret issued by the "
            "GSTN. The actual value is NOT loaded here."
        ),
    )

    @field_validator("client_id_ref", "client_secret_ref")
    @classmethod
    def _no_empty_refs(cls, value: str) -> str:
        if value is not None and value.strip() == "":
            return ""
        if not value or not value.strip():
            raise ValueError(
                "Client credential reference must be a non-empty "
                "opaque name."
            )
        return value.strip()


class GstSigningConfig(BaseModel):
    """References to the signing / encryption key material.

    The actual key material is **never** stored in this object.
    Only opaque references are kept. A real signing implementation
    reads the keystore at request-build time using the references
    below; for this milestone the references are preserved but no
    cryptographic operation is performed.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    keystore_ref: str = Field(
        ...,
        description=(
            "Opaque reference (e.g. environment variable name) to "
            "the keystore / PFX file used for the GSTN request "
            "signature. The keystore itself is NOT loaded here."
        ),
    )
    keystore_password_ref: str = Field(
        ...,
        description=(
            "Opaque reference to the password protecting the "
            "keystore. Never a plaintext password."
        ),
    )
    signing_algorithm: str = Field(
        default="RSA_SHA256",
        description=(
            "Algorithm used to sign the GSTN request envelope. "
            "Preserved for audit; not enforced by this milestone."
        ),
    )

    @field_validator("keystore_ref", "keystore_password_ref")
    @classmethod
    def _no_empty_refs(cls, value: str) -> str:
        if value is not None and value.strip() == "":
            return ""
        if not value or not value.strip():
            raise ValueError(
                "Signing reference must be a non-empty opaque name."
            )
        return value.strip()


class GstConfig(BaseModel):
    """Top-level configuration object for a real GSTN integration.

    The adapter is constructed with one of these and a real
    :class:`GstHttpTransport`. When the real transport is selected
    for real-mode use, ``validate_for_real_use`` MUST be called to
    fail fast on incomplete configuration.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    endpoint: GstEndpointConfig = Field(..., description="HTTPS endpoint config.")
    client: GstClientCredentials = Field(
        ..., description="Opaque references to per-tenant client credentials."
    )
    signing: GstSigningConfig = Field(
        ..., description="Opaque references to signing / encryption key material."
    )

    def validate_for_real_use(self) -> None:
        """Reject obviously incomplete configuration.

        Called only when the real HTTP transport is selected. None
        of the values are logged; only an aggregated error is raised.
        """

        missing: list[str] = []
        if not self.endpoint.url:
            missing.append("endpoint.url")
        if not self.client.client_id_ref:
            missing.append("client.client_id_ref")
        if not self.client.client_secret_ref:
            missing.append("client.client_secret_ref")
        if not self.signing.keystore_ref:
            missing.append("signing.keystore_ref")
        if not self.signing.keystore_password_ref:
            missing.append("signing.keystore_password_ref")
        if missing:
            raise ValueError(
                "GstConfig is incomplete for real transport use; "
                "missing required references: " + ", ".join(missing)
            )


def from_env(env: dict[str, str] | None = None) -> GstConfig:
    """Build a :class:`GstConfig` from environment variables.

    No real secrets are required for this constructor: if the
    variables are absent, the function returns a config whose
    fields are empty strings so the caller can surface a clear
    "missing" error from :meth:`GstConfig.validate_for_real_use`.
    This function is provided for ergonomic environment-driven
    wiring and is the only place that touches ``os.environ``.
    """

    e = env if env is not None else dict(os.environ)
    return GstConfig(
        endpoint=GstEndpointConfig(
            url=e.get("GST_ENDPOINT_URL", ""),
            timeout_seconds=float(e.get("GST_TIMEOUT_SECONDS", "10.0")),
            environment=e.get("GST_ENVIRONMENT", GST_ENV_UAT),
        ),
        client=GstClientCredentials(
            client_id_ref=e.get("GST_CLIENT_ID_REF", ""),
            client_secret_ref=e.get("GST_CLIENT_SECRET_REF", ""),
        ),
        signing=GstSigningConfig(
            keystore_ref=e.get("GST_KEYSTORE_REF", ""),
            keystore_password_ref=e.get("GST_KEYSTORE_PASSWORD_REF", ""),
            signing_algorithm=e.get("GST_SIGNING_ALGORITHM", "RSA_SHA256"),
        ),
    )


__all__ = [
    "GST_ENV_PRODUCTION",
    "GST_ENV_UAT",
    "GstClientCredentials",
    "GstConfig",
    "GstEndpointConfig",
    "GstSigningConfig",
    "from_env",
]
