"""Stable, JSON-safe serialization boundaries for engine artefacts.

No Python object is ever pickled. Every artefact is projected to a
JSON-safe envelope ``{schema_version, artifact_type, data}`` where
``data`` is produced by Pydantic ``model_dump(mode=\"json\")`` (enums and
datetimes become strings, tuples become lists). ``deserialize_artifact``
round-trips the envelope through the registered model so callers get a
fully-typed object back.

The ``ARTIFACT_TYPE_REGISTRY`` maps a stable ``artifact_type`` string to
the owning Pydantic model. Adding a new persistable artefact means
registering its model here — nothing else changes.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

# Domain artefacts that the persistence layer must round-trip safely.
from compliance_engine.models.evidence import Evidence
from compliance_engine.models.finding import IdentityFinding
from compliance_engine.models.result import ComplianceResult
from compliance_engine.models.verification import Verification
from compliance_engine.verification.debarment_models import NormalizedDebarmentData

from ai_verification.cross_bidder.document_artifact_store import DocumentMeta
from ai_verification.cross_bidder.trace import SimilarityTrace
from ai_verification.cross_document.models import CrossDocumentAggregation
from ai_verification.evidence_quality.assessment import EvidenceQualityAssessment
from ai_verification.identity.models import IdentityAggregation
from ai_verification.models.contracts import VerificationFinding

from compliance_engine.financial.outcome import FinancialOutcome

SERIALIZATION_SCHEMA_VERSION: int = 1

ARTIFACT_TYPE_REGISTRY: dict[str, type[BaseModel]] = {
    "evidence": Evidence,
    "verification": Verification,
    "compliance_result": ComplianceResult,
    "identity_finding": IdentityFinding,
    "verification_finding": VerificationFinding,
    "similarity_trace": SimilarityTrace,
    "identity_aggregation": IdentityAggregation,
    "cross_document_aggregation": CrossDocumentAggregation,
    "evidence_quality_assessment": EvidenceQualityAssessment,
    "financial_outcome": FinancialOutcome,
    "normalized_debarment_data": NormalizedDebarmentData,
    "document_meta": DocumentMeta,
}


class SerializedArtifact(BaseModel):
    """The stable on-disk/wire envelope for one engine artefact."""

    artifact_type: str
    schema_version: int
    data: dict[str, Any]


class UnknownArtifactTypeError(ValueError):
    """Raised for an ``artifact_type`` not in the registry."""


def serialize_artifact(obj: BaseModel) -> SerializedArtifact:
    """Project ``obj`` into a JSON-safe envelope.

    Requires ``obj`` to be an instance of a registered model so the
    envelope can be deterministically round-tripped later.
    """
    artifact_type = _type_name_for(type(obj))
    data = obj.model_dump(mode="json")
    # Guard: the payload must be JSON-safe (no bytes/date leak-through).
    json.dumps(data)
    return SerializedArtifact(
        artifact_type=artifact_type,
        schema_version=SERIALIZATION_SCHEMA_VERSION,
        data=data,
    )


def deserialize_artifact(
    envelope: SerializedArtifact | dict[str, Any],
) -> BaseModel:
    """Round-trip an envelope back into a typed domain model."""
    if isinstance(envelope, SerializedArtifact):
        env = envelope
    else:
        env = SerializedArtifact.model_validate(envelope)
    model = ARTIFACT_TYPE_REGISTRY.get(env.artifact_type)
    if model is None:
        raise UnknownArtifactTypeError(
            f"Unknown artifact type {env.artifact_type!r}."
        )
    return model.model_validate(env.data)


def _type_name_for(cls: type[BaseModel]) -> str:
    for name, registered in ARTIFACT_TYPE_REGISTRY.items():
        if registered is cls or issubclass(cls, registered):
            return name
    raise UnknownArtifactTypeError(
        f"Type {cls.__name__} is not a registered serialization target."
    )


__all__ = [
    "ARTIFACT_TYPE_REGISTRY",
    "SERIALIZATION_SCHEMA_VERSION",
    "SerializedArtifact",
    "UnknownArtifactTypeError",
    "deserialize_artifact",
    "serialize_artifact",
]