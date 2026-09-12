"""In-memory :class:`ArtifactStore` implementation."""

from __future__ import annotations

from infrastructure.artifacts.store import (
    ArtifactRecord,
    content_hash,
    make_artifact_id,
)


class InMemoryArtifactStore:
    """Deterministic in-memory artifact store.

    Content-addressed; re-``put`` of the same bytes is idempotent and
    returns the same record. ``allow_delete`` gates ``delete`` so
    immutability is honoured unless the caller explicitly opts in.
    """

    def __init__(
        self,
        *,
        allow_delete: bool = True,
        clock=None,
    ) -> None:
        self._allow_delete = allow_delete
        self._clock = clock if clock is not None else self._default_clock
        self._data: dict[str, bytes] = {}
        self._records: dict[str, ArtifactRecord] = {}

    @staticmethod
    def _default_clock() -> float:
        import time

        return time.time()

    def put(
        self,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict | None = None,
    ) -> ArtifactRecord:
        artifact_id = make_artifact_id(data)
        existing = self._records.get(artifact_id)
        if existing is not None:
            return existing.model_copy(deep=True)
        record = ArtifactRecord(
            artifact_id=artifact_id,
            content_hash=content_hash(data),
            size_bytes=len(data),
            content_type=content_type,
            metadata=dict(metadata or {}),
            created_at=float(self._clock()),
        )
        self._data[artifact_id] = data
        self._records[artifact_id] = record
        return record.model_copy(deep=True)

    def get(self, artifact_id: str) -> bytes | None:
        data = self._data.get(artifact_id)
        return None if data is None else bytes(data)

    def get_record(self, artifact_id: str) -> ArtifactRecord | None:
        record = self._records.get(artifact_id)
        return None if record is None else record.model_copy(deep=True)

    def exists(self, artifact_id: str) -> bool:
        return artifact_id in self._data

    def delete(self, artifact_id: str) -> bool:
        if not self._allow_delete:
            raise PermissionError(
                "Artifact store is immutable (allow_delete=False)."
            )
        if artifact_id not in self._data:
            return False
        self._data.pop(artifact_id, None)
        self._records.pop(artifact_id, None)
        return True


__all__ = ["InMemoryArtifactStore"]