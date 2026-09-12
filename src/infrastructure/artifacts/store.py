"""Artifact/blob storage abstraction for large immutable files.

Large documents (scanned PDFs, images, provider dumps) are *not* stored
in PostgreSQL: Postgres holds only the artifact reference (``artifact_id``)
and the content hash. The binary lives in an injected backend.

Artifacts are immutable and content-addressed: ``artifact_id`` is
``"sha256:<hex>"``. Writing the same bytes twice yields the same ID and
is idempotent. Deletion is allowed only where the lifecycle policy
permits (an explicit ``allow_delete`` on the backend), which keeps
evidence reproducibly retrievable while still supporting a retention
garbage collector in non-audit topologies.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ArtifactRecord(BaseModel):
    """Metadata describing one stored artifact."""

    artifact_id: str
    digest_algorithm: str = "sha256"
    content_hash: str
    size_bytes: int = Field(ge=0)
    content_type: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: float


class ArtifactNotFoundError(LookupError):
    """Raised when an artifact ID is unknown."""


@runtime_checkable
class ArtifactStore(Protocol):
    """Immutable content-addressed blob storage."""

    def put(
        self,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict | None = None,
    ) -> ArtifactRecord: ...

    def get(self, artifact_id: str) -> bytes | None: ...

    def get_record(self, artifact_id: str) -> ArtifactRecord | None: ...

    def exists(self, artifact_id: str) -> bool: ...

    def delete(self, artifact_id: str) -> bool: ...


def content_hash(data: bytes) -> str:
    """Return the SHA-256 hex digest of ``data``."""
    import hashlib

    return hashlib.sha256(data).hexdigest()


def make_artifact_id(data: bytes) -> str:
    """Return the content-addressed ID for ``data``."""
    return f"sha256:{content_hash(data)}"


__all__ = [
    "ArtifactNotFoundError",
    "ArtifactRecord",
    "ArtifactStore",
    "content_hash",
    "make_artifact_id",
]