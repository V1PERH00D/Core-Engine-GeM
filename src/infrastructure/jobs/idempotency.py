"""Deterministic idempotency keys and the idempotency-store contract.

A logical unit of work is identified by::

    (submission_id, stage, logical_input)

The logical input is the JSON-serialisable data that fully determines the
stage's work (e.g. document IDs and their content hashes). The key is a
SHA-256 digest of a canonical JSON encoding of that tuple, so the same
logical work always produces the same key and re-delivery can never
create duplicate durable outputs.

Redis may act as a *fast-path* deduplication layer, but durable
idempotency is enforced by the PostgreSQL unique constraint on
``processing_jobs.idempotency_key`` (and by upsert semantics on domain
repositories). Never rely on Redis alone for durable correctness.
"""

from __future__ import annotations

import hashlib
import json
import threading
from typing import Any, Mapping, Protocol

from pydantic import BaseModel, Field

IDEMPOTENCY_KEY_SCHEMA_VERSION: int = 1


def _canonical_json(value: Any) -> str:
    """Serialise ``value`` deterministically (sorted keys, compact)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def make_idempotency_key(
    *,
    submission_id: str,
    stage: str,
    logical_input: Mapping[str, Any],
) -> str:
    """Return the deterministic idempotency key for one logical work item.

    The same ``(submission_id, stage, logical_input)`` triple always maps
    to the same key regardless of process or time.
    """
    canonical = _canonical_json(
        {
            "schema_version": IDEMPOTENCY_KEY_SCHEMA_VERSION,
            "submission_id": submission_id,
            "stage": stage,
            "logical_input": logical_input,
        }
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"idem:{digest}"


class IdempotencyRecord(BaseModel):
    """Registration of one idempotency key."""

    key: str
    job_id: str
    created_at: float = Field(..., description="Epoch seconds (UTC).")


class IdempotencyStore(Protocol):
    """Fast-path deduplication of job delivery.

    ``get_or_create`` is atomic: concurrent callers racing on the same
    key observe exactly one winner. Returns ``(job_id, created)`` where
    ``created`` is True iff this call registered the key.
    """

    def get_or_create(
        self, key: str, job_id: str, *, now: float
    ) -> tuple[str, bool]: ...

    def get(self, key: str) -> IdempotencyRecord | None: ...

    def delete(self, key: str) -> None: ...


class InMemoryIdempotencyStore:
    """Thread-safe in-memory :class:`IdempotencyStore`."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._records: dict[str, IdempotencyRecord] = {}

    def get_or_create(
        self, key: str, job_id: str, *, now: float
    ) -> tuple[str, bool]:
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                return existing.job_id, False
            self._records[key] = IdempotencyRecord(
                key=key, job_id=job_id, created_at=now
            )
            return job_id, True

    def get(self, key: str) -> IdempotencyRecord | None:
        with self._lock:
            record = self._records.get(key)
            return None if record is None else record.model_copy(deep=True)

    def delete(self, key: str) -> None:
        with self._lock:
            self._records.pop(key, None)


__all__ = [
    "IDEMPOTENCY_KEY_SCHEMA_VERSION",
    "IdempotencyRecord",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "make_idempotency_key",
]
