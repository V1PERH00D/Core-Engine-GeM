"""Compatibility re-export of the CE-owned legal-name normalizer.

The conservative legal-name normalization primitive now lives in the
Compliance Engine (:mod:`compliance_engine.normalization`). This module
re-exports it unchanged so existing downstream imports
(``ai_verification.identity.normalization``) keep working. See
``docs/identity-reconciliation.md`` for the design constraints.
"""

from compliance_engine.normalization import (
    NAME_NORMALIZATION_RULES,
    NAME_NORMALIZATION_VERSION,
    normalize_legal_name,
)

__all__ = [
    "NAME_NORMALIZATION_RULES",
    "NAME_NORMALIZATION_VERSION",
    "normalize_legal_name",
]
