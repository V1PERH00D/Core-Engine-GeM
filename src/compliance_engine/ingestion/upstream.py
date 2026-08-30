"""Deterministic conversion of upstream extraction payloads into Evidence."""

from typing import Any

from pydantic import ValidationError

from compliance_engine.models import Evidence


def evidence_id_for(document_id: str, field_name: str) -> str:
    """Return a stable evidence identifier for a document field."""

    return f"{document_id}:{field_name}"


def normalize_upstream(payload: dict[str, Any]) -> list[Evidence]:
    """Convert a validated upstream payload into canonical Evidence objects.

    Each extracted field on each document becomes one Evidence record.
    Values, including lists and nulls, are preserved without interpretation.
    ``missing_reason`` is not mapped onto Evidence; a null value is kept as
    ``None`` so later stages can distinguish missing content from an absent field.
    """

    bidder_id = payload["bidder_id"]
    evidence: list[Evidence] = []

    for document in payload["documents"]:
        document_id = document["document_id"]
        document_type = document["doc_type"]
        extracted_fields = document["extracted_fields"]

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

    return evidence
