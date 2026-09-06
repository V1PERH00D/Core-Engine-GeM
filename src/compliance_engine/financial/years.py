"""Deterministic financial-year normalization.

Financial years in India run April to March. The engine normalizes the
supported textual forms into a single canonical string ``YYYY-YY`` built
from the start calendar year and the two-digit end year:

    * ``FY2023-24``  -> ``2023-24``
    * ``FY 2023-24`` -> ``2023-24``
    * ``fy2023-24``  -> ``2023-24`` (prefix case-insensitive)
    * ``2023-24``    -> ``2023-24``
    * ``2023-2024``  -> ``2023-24``
    * ``2023 - 24``  -> ``2023-24``

Anything that cannot be parsed unambiguously returns ``None``. The
engine deliberately does **not** guess: a bare ``2023`` (no range), a
mismatched ``2023-25``, or a non-numeric value are all unparseable and
therefore ``None``.

Required financial years are compared against this canonical form, so
``FY2023-24`` and ``2023-2024`` are treated as the same year.
"""

from __future__ import annotations

import re

# Leading "FY"/"fy" prefix with optional separator.
_PREFIX_RE = re.compile(r"^[Ff][Yy]\s*[-_ ]?\s*")

# Year range: start (4 digits) then a dash/slash then a 2- or 4-digit end.
_RANGE_RE = re.compile(r"^(\d{4})\s*[-–/]\s*(\d{2}|\d{4})$")

CANONICAL_YEAR_PATTERN = r"^\d{4}-\d{2}$"


def normalize_financial_year(value: object) -> str | None:
    """Return the canonical ``YYYY-YY`` form, or ``None`` when ambiguous.

    Only the explicit range forms above are accepted. A value of ``None``
    or an empty/boolean input is ``None`` (absent, not error).
    """

    if value is None:
        return None
    if isinstance(value, bool):
        return None

    text = str(value).strip()
    if not text:
        return None

    text = _PREFIX_RE.sub("", text).strip()
    match = _RANGE_RE.match(text)
    if match is None:
        return None

    start_raw, end_raw = match.group(1), match.group(2)
    start = int(start_raw)

    if len(end_raw) == 2:
        end = int(end_raw)
        # The two-digit end must be the next year's last two digits.
        if end != (start + 1) % 100:
            return None
    else:
        end = int(end_raw)
        if end != start + 1:
            return None

    return f"{start:04d}-{end % 100:02d}"


__all__ = [
    "CANONICAL_YEAR_PATTERN",
    "normalize_financial_year",
]