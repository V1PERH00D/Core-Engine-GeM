"""Filesystem-backed :class:`ArtifactStore` for local development/tests.

Content is stored under ``root_dir`` in a two-level shard of the hex
digest (``ab/cdef...``) with a JSON sidecar for metadata. No cloud
credentials, buckets, or network are required.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from infrastructure.artifacts.store import (
    ArtifactRecord,
    content_hash,
    make_artifact_id,
)


class FilesystemArtifactStore:
    def __init__(self, root_dir: str | os.PathLike, *, allow_delete: bool = True) -> None:
        self._root = Path(root_dir)
        self._allow_delete = allow_delete
        self._root.mkdir(parents=True, exist_ok=True)

    def _paths(self, artifact_id: str) -> tuple[Path, Path]:
        digest = artifact_id.split(":", 1)[1]
        shard = digest[:2]
        blob = self._root / shard / (digest + ".bin")
        meta = self._root / shard / (digest + ".json")
        return blob, meta

    def put(
        self,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict | None = None,
    ) -> ArtifactRecord:
        artifact_id = make_artifact_id(data)
        existing = self.get_record(artifact_id)
        if existing is not None:
            return existing
        blob, meta = self._paths(artifact_id)
        blob.parent.mkdir(parents=True, exist_ok=True)
        record = ArtifactRecord(
            artifact_id=artifact_id,
            content_hash=content_hash(data),
            size_bytes=len(data),
            content_type=content_type,
            metadata=dict(metadata or {}),
            created_at=_now(),
        )
        blob.write_bytes(data)
        meta.write_text(record.model_dump_json())
        return record

    def get(self, artifact_id: str) -> bytes | None:
        blob, _ = self._paths(artifact_id)
        if not blob.exists():
            return None
        return blob.read_bytes()

    def get_record(self, artifact_id: str) -> ArtifactRecord | None:
        _, meta = self._paths(artifact_id)
        if not meta.exists():
            return None
        return ArtifactRecord.model_validate_json(meta.read_text())

    def exists(self, artifact_id: str) -> bool:
        blob, _ = self._paths(artifact_id)
        return blob.exists()

    def delete(self, artifact_id: str) -> bool:
        if not self._allow_delete:
            raise PermissionError(
                "Artifact store is immutable (allow_delete=False)."
            )
        blob, meta = self._paths(artifact_id)
        existed = blob.exists()
        if existed:
            blob.unlink()
            if meta.exists():
                meta.unlink()
        return existed


def _now() -> float:
    import time

    return time.time()


__all__ = ["FilesystemArtifactStore"]