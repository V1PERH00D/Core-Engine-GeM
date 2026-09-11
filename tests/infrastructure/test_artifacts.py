"""Artifact store contract tests (in-memory + filesystem)."""

import pytest

from infrastructure.artifacts import (
    FilesystemArtifactStore,
    InMemoryArtifactStore,
    content_hash,
    make_artifact_id,
)


def test_content_hash_stable():
    assert content_hash(b"hello") == content_hash(b"hello")
    assert content_hash(b"hello") != content_hash(b"world")


def test_content_addressed_id_same_bytes():
    assert make_artifact_id(b"a") == make_artifact_id(b"a")
    assert make_artifact_id(b"a") != make_artifact_id(b"b")


def test_memory_put_get_roundtrip():
    store = InMemoryArtifactStore()
    rec = store.put(b"hello", content_type="text/plain", metadata={"x": 1})
    assert rec.artifact_id.startswith("sha256:")
    assert rec.size_bytes == 5
    assert store.get(rec.artifact_id) == b"hello"


def test_memory_put_duplicate_idempotent():
    store = InMemoryArtifactStore()
    r1 = store.put(b"hello")
    r2 = store.put(b"hello")
    assert r1.artifact_id == r2.artifact_id


def test_memory_exists_and_missing():
    store = InMemoryArtifactStore()
    rec = store.put(b"hello")
    assert store.exists(rec.artifact_id)
    assert store.get("sha256:0" * 64) is None
    assert not store.exists("sha256:0" * 64)


def test_memory_metadata_record():
    store = InMemoryArtifactStore()
    rec = store.put(b"hello", metadata={"k": "v"})
    got = store.get_record(rec.artifact_id)
    assert got.metadata == {"k": "v"}
    assert got.content_hash == content_hash(b"hello")


def test_memory_delete_policy():
    immutable = InMemoryArtifactStore(allow_delete=False)
    rec = immutable.put(b"x")
    with pytest.raises(PermissionError):
        immutable.delete(rec.artifact_id)


def test_memory_delete_when_allowed():
    store = InMemoryArtifactStore(allow_delete=True)
    rec = store.put(b"x")
    assert store.delete(rec.artifact_id) is True
    assert store.get(rec.artifact_id) is None


def test_filesystem_roundtrip(tmp_path):
    store = FilesystemArtifactStore(tmp_path)
    rec = store.put(b"file-content", content_type="application/pdf")
    assert store.exists(rec.artifact_id)
    assert store.get(rec.artifact_id) == b"file-content"
    assert store.get_record(rec.artifact_id).size_bytes == 12


def test_filesystem_missing(tmp_path):
    store = FilesystemArtifactStore(tmp_path)
    assert store.get("sha256:0" * 64) is None