"""Deterministic legal-name normalization for identity reconciliation.

Design constraints (also documented in
``docs/identity-reconciliation.md``):

* Deterministic: same input always produces the same output.
* Versioned: every produced value carries a
  :data:`NAME_NORMALIZATION_VERSION` stamp so audit consumers can
  verify which rules were in effect.
* Conservative: we never silently collapse abbreviations such as
  ``PVT`` -> ``PRIVATE`` or ``LTD`` -> ``LIMITED``. The Compliance
  Engine's existing cross-document identity anomaly detector
  (see ``compliance_engine.anomalies.identity.normalize_identity_name``)
  already performs that lexical rewrite for *evidence* fields; this
  module is deliberately narrower so cross-*source* reconciliation
  can never accidentally amplify a synonym rewrite into a fake
  identity match.
* Wholly synchronous, no AI / no network.

Pipeline (in order):

1. ``None`` -> ``None`` (caller may rely on this).
2. Empty / whitespace-only -> ``None`` (treated as missing).
3. Unicode NFKC normalization.
4. Strip surrounding whitespace.
5. Collapse internal whitespace runs to a single space.
6. Strip a small set of trivially harmless formatting
   characters from the leading and trailing edges only
   (trailing dots, trailing commas).
7. Case-fold (lowercase).
8. Return the lowercase canonical form.

The function retains both the *original* and the *normalized* form
on every produced observation; the module itself never discards the
original.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

#: Bumped whenever the algorithm below changes in any way that could
#: affect equality between two normalized values.
NAME_NORMALIZATION_VERSION = "identity-name-v1"

#: Human-readable, ordered list of every transformation applied.
#: Kept frozen so downstream consumers and tests can introspect the
#: rule set without re-reading the implementation.
NAME_NORMALIZATION_RULES: tuple[str, ...] = (
    "1. None -> None",
    "2. Empty / whitespace-only -> None",
    "3. Unicode NFKC",
    "4. Strip surrounding whitespace",
    "5. Collapse repeated internal whitespace to single space",
    "6. Strip edge punctuation (trailing '.', ',')",
    "7. Case-fold (lowercase)",
)


# ---------------------------------------------------------------------------
# Implementation
# ---------------------------------------------------------------------------

#: Internal whitespace collapse pattern.
_MULTI_WS_RE = re.compile(r"\s+")

#: Trailing/leading edge punctuation that is documented as harmless
#: formatting noise (e.g. trailing ``.`` in ``ACME LTD.``). We strip
#: only from the edges, never from the interior of the name.
_EDGE_PUNCT_RE = re.compile(r"^[.,;:\s]+|[.,;:\s]+$")


def normalize_legal_name(value: Optional[str]) -> Optional[str]:
    """Return the deterministic normalized form of ``value``.

    Returns ``None`` when the input is missing, empty, or
    whitespace-only so downstream code can use ``is None`` as a
    uniform "no name available" signal.
    """

    if value is None:
        return None
    if not isinstance(value, str):  # pragma: no cover -- defensive
        raise TypeError(
            "normalize_legal_name expects str or None, got "
            f"{type(value).__name__}"
        )

    # 1-2. Unicode NFKC.
    text = unicodedata.normalize("NFKC", value)

    # 3. Strip surrounding whitespace.
    text = text.strip()

    if not text:
        return None

    # 4. Collapse internal whitespace.
    text = _MULTI_WS_RE.sub(" ", text)

    # 5. Strip edge punctuation (harmless formatting).
    text = _EDGE_PUNCT_RE.sub("", text).strip()
    if not text:
        return None

    # 6. Case-fold.
    text = text.casefold()

    # 7. Re-collapse whitespace introduced by stripping (defensive).
    text = _MULTI_WS_RE.sub(" ", text).strip()
    return text or None


__all__ = [
    "NAME_NORMALIZATION_RULES",
    "NAME_NORMALIZATION_VERSION",
    "normalize_legal_name",
]