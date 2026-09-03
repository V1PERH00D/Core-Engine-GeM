from datetime import date

import pytest

from ai_verification.cross_bidder import (
    DocumentArtifactStore,
    DocumentMeta,
    InMemoryDocumentArtifactStore,
)


def make_metadata() -> DocumentMeta:
    return DocumentMeta(
        document_type="OEM_AUTH",
        ocr_confidence=0.97,
        document_type_confidence=0.99,
        issuer="ACME OEM",
        authorization_number="AUTH-123",
        issue_date=date(2026, 1, 10),
        valid_until=date(2027, 1, 10),
        bidder_name="Bidder One",
        territory="India",
    )


def make_store() -> InMemoryDocumentArtifactStore:
    return InMemoryDocumentArtifactStore(
        raw_texts={"doc-1": "OEM authorization text"},
        file_hashes={"doc-1": "abc123"},
        metadata={"doc-1": make_metadata()},
    )


def test_protocol_compatibility() -> None:
    assert isinstance(make_store(), DocumentArtifactStore)


def test_raw_text_read() -> None:
    store = make_store()
    assert store.get_raw_text("doc-1") == "OEM authorization text"


def test_file_hash_read() -> None:
    store = make_store()
    assert store.get_file_hash("doc-1") == "abc123"


def test_metadata_read() -> None:
    store = make_store()

    metadata = store.get_metadata("doc-1")

    assert metadata == make_metadata()


def test_unknown_document_returns_none() -> None:
    store = make_store()

    assert store.get_raw_text("missing") is None
    assert store.get_file_hash("missing") is None
    assert store.get_metadata("missing") is None


def test_optional_metadata_fields_are_supported() -> None:
    metadata = DocumentMeta(
        document_type="GST",
        ocr_confidence=0.8,
        document_type_confidence=0.9,
    )

    assert metadata.issuer is None
    assert metadata.authorization_number is None
    assert metadata.issue_date is None
    assert metadata.valid_until is None
    assert metadata.bidder_name is None
    assert metadata.territory is None


@pytest.mark.parametrize("field", ["ocr_confidence", "document_type_confidence"])
@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_confidence_bounds(field: str, value: float) -> None:
    values = {
        "document_type": "OEM_AUTH",
        "ocr_confidence": 0.5,
        "document_type_confidence": 0.5,
    }
    values[field] = value

    with pytest.raises(ValueError):
        DocumentMeta(**values)


def test_reads_do_not_mutate_stored_metadata() -> None:
    metadata = make_metadata()
    store = InMemoryDocumentArtifactStore(metadata={"doc-1": metadata})

    returned = store.get_metadata("doc-1")
    assert returned is not None

    returned.issuer = "Changed"

    reread = store.get_metadata("doc-1")
    assert reread is not None
    assert reread.issuer == "ACME OEM"
