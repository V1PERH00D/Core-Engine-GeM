"""Configuration / credential seam for the procurement-eligibility
integration.

Design constraints (mirroring the GST / PAN / MCA / Udyam config
modules):

* Never store real secrets in source code.
* Never commit credentials.
* Prefer environment / config-file injection.
* Do not implement a full secrets-management framework.
* Do not implement authentication bypasses.
* Do not require credentials for unit tests.

Production shape
----------------

A real procurement-eligibility / debarment integration will require:

* an HTTPS endpoint (the published service URL, agreed at agency
  onboarding);
* per-tenant client credentials (issued after agency approval);
* a configurable timeout;
* a configurable minimum TLS version.

None of those values are hardcoded here. The objects below expose
typed references for every required field, validate that none of
them are empty when a real transport is enabled, and never persist
them anywhere.

Configuration objects are Pydantic models with ``extra="forbid"``
so typos in environment-driven config surface immediately instead
of being silently ignored.
"""

from __future__ import annotations

import os
from typing import Final

from compliance_engine.verification.debarment_models import (
    DebarmentClientCredentials,
    DebarmentConfig,
    DebarmentEndpointConfig,
)


# Environment selector. ``UAT`` is the safe default so production
# must be opted into explicitly.
DEBARMENT_ENV_UAT: Final[str] = "UAT"
DEBARMENT_ENV_PRODUCTION: Final[str] = "PRODUCTION"
_DEBARMENT_ALLOWED_ENVS: Final[tuple[str, ...]] = (
    DEBARMENT_ENV_UAT,
    DEBARMENT_ENV_PRODUCTION,
)


def from_env(env: dict[str, str] | None = None) -> DebarmentConfig:
    """Build a :class:`DebarmentConfig` from environment variables.

    No real secrets are required for this constructor: if the
    variables are absent, the function returns a config whose
    fields are empty strings so the caller can surface a clear
    "missing" error from
    :meth:`DebarmentConfig.validate_for_real_use`. This function is
    provided for ergonomic environment-driven wiring and is the
    only place that touches ``os.environ``.
    """

    e = env if env is not None else dict(os.environ)
    return DebarmentConfig(
        endpoint=DebarmentEndpointConfig(
            url=e.get("DEBARMENT_ENDPOINT_URL", ""),
            timeout_seconds=float(
                e.get("DEBARMENT_TIMEOUT_SECONDS", "10.0")
            ),
        ),
        client=DebarmentClientCredentials(
            client_id_ref=e.get("DEBARMENT_CLIENT_ID_REF", ""),
            client_secret_ref=e.get("DEBARMENT_CLIENT_SECRET_REF", ""),
        ),
    )


__all__ = [
    "DEBARMENT_ENV_PRODUCTION",
    "DEBARMENT_ENV_UAT",
    "DebarmentClientCredentials",
    "DebarmentConfig",
    "DebarmentEndpointConfig",
    "from_env",
]
