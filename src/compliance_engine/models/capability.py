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

    GST                  -> "GST / GSTN"                      (matrix §4)
    GST_RETURN_FILING    -> "GST / GSTN" (return filing)      (matrix §4)
    PAN_INCOME_TAX       -> "PAN / Income Tax"                (matrix §5)
    UDYAM                -> "Udyam / MSME"                    (matrix §6)
    FINANCIAL            -> "Financial Capacity"              (matrix §7)
    MAKE_IN_INDIA        -> "Make in India / Local Content"   (matrix §10)
    BIS                  -> "BIS / Product Certification"     (matrix §15)
    DIGILOCKER           -> "DigiLocker / Document Verif."    (matrix §16)
    OEM_AUTHORIZATION    -> "OEM Authorization"               (matrix §17)
    BIDDER_IDENTITY      -> "Bidder Identity"                 (matrix §3, anomalies)
    MCA21                -> "MCA21 / Company Registration"    (matrix §9)
    DEBARMENT            -> "Procurement Eligibility"         (matrix §19)

The IDs ``GST``, ``GST_RETURN_FILING``, ``PAN_INCOME_TAX``, ``UDYAM``,
``FINANCIAL``, ``MAKE_IN_INDIA``, ``BIS``, ``DIGILOCKER``,
``OEM_AUTHORIZATION``, ``BIDDER_IDENTITY``, ``MCA21``, and ``DEBARMENT``
are the only ones currently in use by the engine.
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
    MAKE_IN_INDIA = "MAKE_IN_INDIA"
    BIS = "BIS"
    DIGILOCKER = "DIGILOCKER"
    OEM_AUTHORIZATION = "OEM_AUTHORIZATION"
    BIDDER_IDENTITY = "BIDDER_IDENTITY"
    MCA21 = "MCA21"
    DEBARMENT = "DEBARMENT"


__all__ = ["Capability"]
