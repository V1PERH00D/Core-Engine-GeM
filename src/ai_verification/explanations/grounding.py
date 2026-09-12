"""Explicit grounding contract for the explanation engine.

The grounding object is the *only* set of artefacts an explanation may
reference. Every claim in a generated explanation must trace to one or more
of these supplied IDs. Arbitrary reference IDs that are not present in the
supplied context are rejected downstream by the grounding validator.

The object is frozen and normalises its reference tuples to sorted,
deduplicated order so the grounding hash is deterministic regardless of
how the caller ordered the lists.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

GROUNDING_SCHEMA_VERSION: int = 1


class GroundingRefKind(StrEnum):
    """The six artefact families an explanation may reference."""

    EVIDENCE = "EVIDENCE"
    VERIFICATION = "VERIFICATION"
    DOCUMENT = "DOCUMENT"
    FINDING = "FINDING"
    COMPARISON = "COMPARISON"
    TRACE = "TRACE"


class ExplanationGrounding(BaseModel):
    """The set of real artefacts a single explanation may cite."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_refs: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    document_refs: tuple[str, ...] = ()
    finding_refs: tuple[str, ...] = ()
    comparison_refs: tuple[str, ...] = ()
    trace_refs: tuple[str, ...] = ()
    grounding_version: int = GROUNDING_SCHEMA_VERSION

    @field_validator(
        "evidence_refs",
        "verification_refs",
        "document_refs",
        "finding_refs",
        "comparison_refs",
        "trace_refs",
    )
    @classmethod
    def _normalise(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(v)))

    # ------------------------------------------------------------------
    # Membership helpers
    # ------------------------------------------------------------------

    def known_ids(self, kind: GroundingRefKind) -> frozenset[str]:
        return frozenset(self._refs(kind))

    def _refs(self, kind: GroundingRefKind) -> tuple[str, ...]:
        mapping: dict[GroundingRefKind, tuple[str, ...]] = {
            GroundingRefKind.EVIDENCE: self.evidence_refs,
            GroundingRefKind.VERIFICATION: self.verification_refs,
            GroundingRefKind.DOCUMENT: self.document_refs,
            GroundingRefKind.FINDING: self.finding_refs,
            GroundingRefKind.COMPARISON: self.comparison_refs,
            GroundingRefKind.TRACE: self.trace_refs,
        }
        return mapping[kind]

    def all_refs(self) -> dict[str, tuple[str, ...]]:
        """Return a mapping from reference-kind value to its IDs."""

        return {
            kind.value: self._refs(kind) for kind in GroundingRefKind
        }

    def is_empty(self) -> bool:
        return all(len(self._refs(k)) == 0 for k in GroundingRefKind)

    def content_hash(self) -> str:
        """Deterministic SHA-256 of the grounding content.

        Used for idempotency and input-version tracking. Order-independent
        because reference tuples are already normalised.
        """
        payload = {
            "version": self.grounding_version,
            "refs": {
                kind.value: list(self._refs(kind)) for kind in GroundingRefKind
            },
        }
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "GROUNDING_SCHEMA_VERSION",
    "ExplanationGrounding",
    "GroundingRefKind",
]