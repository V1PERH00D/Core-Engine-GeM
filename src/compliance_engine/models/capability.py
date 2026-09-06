"""Canonical machine-readable capability identifiers.

The engine uses a small set of stable capability IDs to group requirements,
look up verification providers, and label cross-document findings. These
IDs are deliberately distinct from the human-readable section names used in
``docs/capability-matrix.md`` and from the descriptive ``capability`` field
strings on flag definitions.

Current canonical IDs correspond to capabilities that have at least one
executable code reference today. Adding a new canonical ID must be a
deliberate act (with implementation and tests); this module intentionally
does not pre-declare every future capability listed in the matrix.

Mapping of canonical machine ID to its human-readable section name (for
documentation only; the engine never reads these names):

    GST                  -> "GST / GSTN"                      (matrix \u00a74)
    GST_RETURN_FILING    -> "GST / GSTN" (return filing)      (matrix \u00a74)
    PAN_INCOME_TAX       -> "PAN / Income Tax"                (matrix \u00a75)
    UDYAM                -> "Udyam / MSME"                    (matrix \u00a76)
    FINANCIAL            -> "Financial Capacity"              (matrix \u00a77)
    BIDDER_IDENTITY      -> "Bidder Identity"                 (matrix \u00a73, anomalies)

The IDs ``GST``, ``GST_RETURN_FILING``, ``PAN_INCOME_TAX``, ``UDYAM``,
``FINANCIAL``, and ``BIDDER_IDENTITY`` are the only ones currently in
use by the engine.
Any other identifier seen in code is either a human-readable label on a
``FlagDefinition`` (out of scope here) or a value to be migrated to a
canonical ID by a future change.
"""

from enum import StrEnum


class Capability(StrEnum):
    """Canonical machine-readable capability identifiers.

    Values are intentionally upper-snake-case to keep them stable as
    machine IDs and to make them easy to compare and serialize. They
    are not the human-readable capability names that appear in tender
    documents or in the capability matrix.
    """

    GST = "GST"
    GST_RETURN_FILING = "GST_RETURN_FILING"
    PAN_INCOME_TAX = "PAN_INCOME_TAX"
    UDYAM = "UDYAM"
    FINANCIAL = "FINANCIAL"
    BIDDER_IDENTITY = "BIDDER_IDENTITY"


__all__ = ["Capability"]
