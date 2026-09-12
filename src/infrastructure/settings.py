"""Environment-driven infrastructure configuration.

No credentials are fabricated here. Every field the platform needs is
read from the environment (optional, ``None`` when absent) so local
development and tests run against in-memory backends with zero
configuration, while production wiring stays explicit and traceable.

Retention is *configurable*, not hardcoded: this module never invents
legal retention periods.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class InfrastructureSettings:
    database_url: str | None = None
    redis_url: str | None = None
    artifact_root: str | None = None

    lease_seconds: float = 60.0
    max_attempts: int = 3
    base_retry_delay_seconds: float = 1.0

    redis_state_ttl_seconds: float = 86400.0

    # Retention policies (None = retain indefinitely).
    artifact_retention_days: int | None = None
    audit_retention_days: int | None = None

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        *,
        prefix: str = "GEM_",
    ) -> "InfrastructureSettings":
        env = env if env is not None else dict(os.environ)

        def get(name: str, default: str | None = None) -> str | None:
            return env.get(prefix + name, default)

        def get_float(name: str, default: float) -> float:
            raw = get(name)
            return default if raw is None else float(raw)

        def get_int(name: str, default: int) -> int:
            raw = get(name)
            return default if raw is None else int(raw)

        def get_opt_int(name: str) -> int | None:
            raw = get(name)
            return None if raw is None else int(raw)

        return cls(
            database_url=get("DATABASE_URL"),
            redis_url=get("REDIS_URL"),
            artifact_root=get("ARTIFACT_ROOT"),
            lease_seconds=get_float("LEASE_SECONDS", 60.0),
            max_attempts=get_int("MAX_ATTEMPTS", 3),
            base_retry_delay_seconds=get_float("RETRY_BASE_DELAY_SECONDS", 1.0),
            redis_state_ttl_seconds=get_float("REDIS_STATE_TTL_SECONDS", 86400.0),
            artifact_retention_days=get_opt_int("ARTIFACT_RETENTION_DAYS"),
            audit_retention_days=get_opt_int("AUDIT_RETENTION_DAYS"),
        )

    def require_database_url(self) -> str:
        """Return the database URL or raise with a clear message."""
        if not self.database_url:
            raise RuntimeError(
                "GEM_DATABASE_URL is not configured; provide a PostgreSQL "
                "connection string or use the in-memory unit of work."
            )
        return self.database_url

    def require_redis_url(self) -> str:
        if not self.redis_url:
            raise RuntimeError(
                "GEM_REDIS_URL is not configured; provide a Redis URL or "
                "use the in-memory queue."
            )
        return self.redis_url


__all__ = ["InfrastructureSettings"]