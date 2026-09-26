"""Deterministic conversion of upstream extraction payloads into Evidence."""

from typing import Any

from pydantic import ValidationError

from compliance_engine.models import (
    Evidence,
    GroundingMetadata,
    NormalizedDocument,
    NormalizedSubmission,
)


def evidence_id_for(document_id: str, field_name: str) -> str:
    """Return a stable evidence identifier for a document field."""

    return f"{document_id}:{field_name}"


def normalize_submission(payload: dict[str, Any]) -> NormalizedSubmission:
    """Convert a validated upstream payload into a NormalizedSubmission.

    The submission envelope preserves ``submission_id``, ``bidder_id`` and
    per-document metadata (``doc_type``, ``doc_type_confidence``,
    ``ocr_confidence``, ``file_hash``, ``grounding``) alongside the
    field-level Evidence, so nothing the persistence pipeline needs is
    discarded at the ingestion boundary.
    """

    submission_id = payload["submission_id"]
    bidder_id = payload["bidder_id"]
    documents: list[NormalizedDocument] = []

    for document in payload["documents"]:
        document_id = document["document_id"]
        document_type = document["doc_type"]
        extracted_fields = document["extracted_fields"]

        evidence: list[Evidence] = []
        for field_name, field in extracted_fields.items():
            if not isinstance(field, dict):
                raise ValidationError.from_exception_data(
                    title="Evidence",
                    line_errors=[
                        {
                            "type": "dict_type",
                            "loc": ("extracted_fields", document_id, field_name),
                            "input": field,
                        }
                    ],
                )

            record = {
                "evidence_id": evidence_id_for(document_id, field_name),
                "bidder_id": bidder_id,
                "document_id": document_id,
                "document_type": document_type,
                "field_name": field_name,
                "value": field.get("value"),
                "confidence": field.get("confidence"),
                "page": field.get("page"),
                "bbox": field.get("bbox"),
                "missing_reason": field.get("missing_reason"),
            }
            try:
                evidence.append(Evidence.model_validate(record))
            except ValidationError as exc:
                raise ValidationError.from_exception_data(
                    title=(
                        f"Malformed extracted field {field_name!r} "
                        f"on document {document_id!r}"
                    ),
                    line_errors=exc.errors(),
                ) from exc

        grounding = document.get("grounding")
        documents.append(
            NormalizedDocument(
                document_id=document_id,
                doc_type=document_type,
                doc_type_confidence=document.get("doc_type_confidence"),
                ocr_confidence=document.get("ocr_confidence"),
                file_hash=document.get("file_hash"),
                grounding=(
                    GroundingMetadata.model_validate(grounding)
                    if grounding is not None
                    else None
                ),
                evidence=evidence,
            )
        )

    return NormalizedSubmission(
        submission_id=submission_id,
        bidder_id=bidder_id,
        documents=documents,
    )


def normalize_upstream(payload: dict[str, Any]) -> list[Evidence]:
    """Convert a validated upstream payload into canonical Evidence objects.

    Each extracted field on each document becomes one Evidence record.
    Values, including lists and nulls, are preserved without interpretation.
    ``missing_reason`` is preserved on the Evidence when supplied; a field
    without it (or with a null value) keeps ``missing_reason=None``.
    Document- and submission-level metadata is available via
    :func:`normalize_submission`.
    """

    return normalize_submission(payload).evidence
