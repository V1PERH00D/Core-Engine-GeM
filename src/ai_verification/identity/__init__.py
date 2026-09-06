"""Cross-source bidder identity reconciliation.

This subpackage provides a deterministic, auditable engine that
compares the already-normalized legal-name values carried inside
``Verification`` records produced by the Compliance Engine's GST,
PAN, Udyam, and MCA adapters, and surfaces meaningful cross-source
identity inconsistencies as findings.

Design constraints (also documented in ``docs/identity-reconciliation.md``):

* Deterministic, no AI / no embeddings / no network calls.
* Typed Pydantic models (``extra="forbid"``).
* No provider re-querying: the engine consumes existing
  ``Verification`` artefacts only.
* No "majority truth" policy: the engine produces an evidence
  graph; downstream policy decides how to act.
"""

from .models import (
    ComparisonOutcome,
    IdentityAggregation,
    IdentityObservation,
    IdentityPairwiseComparison,
    SourceAvailability,
)
from .normalization import (
    NAME_NORMALIZATION_RULES,
    NAME_NORMALIZATION_VERSION,
    normalize_legal_name,
)
from .engine import IdentityReconciliationEngine, IdentityReconciliationResult
from .findings import (
    CROSS_SOURCE_IDENTITY_MISMATCH,
    to_identity_findings,
    to_verification_findings,
)
from .extraction import CAPABILITY_TO_SOURCE, SOURCE_IDENTITY_FIELD

__all__ = [
    "CAPABILITY_TO_SOURCE",
    "CROSS_SOURCE_IDENTITY_MISMATCH",
    "ComparisonOutcome",
    "IdentityAggregation",
    "IdentityObservation",
    "IdentityPairwiseComparison",
    "IdentityReconciliationEngine",
    "IdentityReconciliationResult",
    "NAME_NORMALIZATION_RULES",
    "NAME_NORMALIZATION_VERSION",
    "SOURCE_IDENTITY_FIELD",
    "SourceAvailability",
    "normalize_legal_name",
    "to_identity_findings",
    "to_verification_findings",
]