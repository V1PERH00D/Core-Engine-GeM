"""Boolean flag materialization and snapshots.

The downstream contract is exactly::

    {"bidder_id": "...", "flags": {"<CANONICAL_FLAG_ID>": true/false}}

Severity and risk are intentionally absent from this layer. The
materializer turns a set of :class:`FlagStateRecord` (boolean states +
provenance) into a reproducible :class:`BidderFlagSnapshot` whose stable
``snapshot_id`` is a digest of ``(bidder_id, version, flags)`` so the
same logical flag state always materializes to the same snapshot.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, Field, field_validator

from compliance_engine.flags import UnknownFlagError, get_flag_definition

from infrastructure.persistence.records import FlagStateRecord

FLAG_SNAPSHOT_SCHEMA_VERSION: int = 1


class FlagProvenance(BaseModel):
    """Internal provenance retained alongside a boolean flag state."""

    finding_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    source: str | None = None
    correlation_id: str | None = None


class BidderFlagSnapshot(BaseModel):
    """One reproducible, boolean-only flag snapshot for a bidder."""

    snapshot_id: str
    bidder_id: str
    snapshot_version: int = FLAG_SNAPSHOT_SCHEMA_VERSION
    flags: dict[str, bool] = Field(default_factory=dict)
    provenance: dict[str, dict[str, Any]] = Field(default_factory=dict)
    content_hash: str
    created_at: float

    @field_validator("flags")
    @classmethod
    def _validate_flags(cls, value: dict[str, bool]) -> dict[str, bool]:
        for key, val in value.items():
            if not isinstance(val, bool):
                raise ValueError(
                    f"Flag {key!r} must be a boolean, got {type(val).__name__}."
                )
        return value

    def downstream_payload(self) -> dict[str, Any]:
        """Return the exact downstream contract shape (sorted flags)."""
        return {
            "bidder_id": self.bidder_id,
            "flags": {
                flag_id: self.flags[flag_id]
                for flag_id in sorted(self.flags)
            },
        }

    def internal_payload(
        self, explanation_refs: Mapping[str, str] | None = None
    ) -> dict[str, Any]:
        """Return a richer internal representation including explanation IDs.

        ``explanation_refs`` maps a canonical flag ID to its explanation ID.
        This is an internal-only view; the downstream contract returned by
        :meth:`downstream_payload` remains boolean-only.
        """
        payload = self.downstream_payload()
        if explanation_refs:
            payload["explanations"] = {
                flag_id: explanation_refs[flag_id]
                for flag_id in sorted(explanation_refs)
                if flag_id in self.flags
            }
        return payload


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def compute_snapshot_id(
    bidder_id: str, version: int, flags: Mapping[str, bool]
) -> str:
    digest = hashlib.sha256(
        _canonical_json(
            {
                "bidder_id": bidder_id,
                "version": version,
                "flags": dict(flags),
            }
        ).encode("utf-8")
    ).hexdigest()
    return f"snap:{digest}"


def materialize_flag_snapshot(
    bidder_id: str,
    states: Iterable[FlagStateRecord],
    *,
    known_flag_ids: Iterable[str] | None = None,
    clock=None,
) -> BidderFlagSnapshot:
    """Materialize a reproducible snapshot from boolean flag states.

    Duplicate states for one flag keep the last one (upsert semantics).
    ``known_flag_ids``, when supplied, fixes the flag universe: any known
    flag absent from ``states`` is recorded as ``False`` (explicit default
    semantics); without it only flags actually present are emitted.
    """
    if clock is None:
        import time

        clock = time.time

    flags: dict[str, bool] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for state in states:
        # Canonical ID validation: reject non-registry flags.
        get_flag_definition(state.flag_id)
        flags[state.flag_id] = state.is_set
        provenance[state.flag_id] = {
            "finding_refs": list(state.finding_refs),
            "evidence_refs": list(state.evidence_refs),
            "verification_refs": list(state.verification_refs),
            "source": state.source,
            "correlation_id": state.correlation_id,
        }

    if known_flag_ids is not None:
        for flag_id in known_flag_ids:
            get_flag_definition(flag_id)
            flags.setdefault(flag_id, False)
            provenance.setdefault(flag_id, {"source": "DEFAULT_UNSET"})

    snapshot_id = compute_snapshot_id(
        bidder_id, FLAG_SNAPSHOT_SCHEMA_VERSION, flags
    )
    return BidderFlagSnapshot(
        snapshot_id=snapshot_id,
        bidder_id=bidder_id,
        snapshot_version=FLAG_SNAPSHOT_SCHEMA_VERSION,
        flags=flags,
        provenance=provenance,
        content_hash=snapshot_id.removeprefix("snap:"),
        created_at=float(clock()),
    )


__all__ = [
    "BidderFlagSnapshot",
    "FLAG_SNAPSHOT_SCHEMA_VERSION",
    "FlagProvenance",
    "UnknownFlagError",
    "compute_snapshot_id",
    "materialize_flag_snapshot",
]