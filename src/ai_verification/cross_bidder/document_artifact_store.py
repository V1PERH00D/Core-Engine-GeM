"""Document artifact access contracts for cross-bidder verification."""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class DocumentMeta(BaseModel):
    """Minimal metadata required for cross-bidder document comparison."""

    model_config = ConfigDict(extra="forbid")

    document_type: str
    evidence_id: str | None = None
    ocr_confidence: float = Field(ge=0.0, le=1.0)
    document_type_confidence: float = Field(ge=0.0, le=1.0)
    issuer: str | None = None
    authorization_number: str | None = None
    issue_date: date | None = None
    valid_until: date | None = None
    bidder_name: str | None = None
    territory: str | None = None


@runtime_checkable
class DocumentArtifactStore(Protocol):
    """Read-only access to document artifacts keyed by document ID."""

    def get_raw_text(self, document_id: str) -> str | None:
        ...

    def get_file_hash(self, document_id: str) -> str | None:
        ...

    def get_metadata(self, document_id: str) -> DocumentMeta | None:
        ...


class InMemoryDocumentArtifactStore:
    """Simple in-memory artifact store for tests and demos."""

    def __init__(
        self,
        *,
        raw_texts: dict[str, str] | None = None,
        file_hashes: dict[str, str] | None = None,
        metadata: dict[str, DocumentMeta] | None = None,
    ) -> None:
        self._raw_texts = dict(raw_texts or {})
        self._file_hashes = dict(file_hashes or {})
        self._metadata = dict(metadata or {})

    def get_raw_text(self, document_id: str) -> str | None:
        return self._raw_texts.get(document_id)

    def get_file_hash(self, document_id: str) -> str | None:
        return self._file_hashes.get(document_id)

    def get_metadata(self, document_id: str) -> DocumentMeta | None:
        value = self._metadata.get(document_id)
        return value.model_copy(deep=True) if value is not None else None


__all__ = [
    "DocumentArtifactStore",
    "DocumentMeta",
    "InMemoryDocumentArtifactStore",
]
