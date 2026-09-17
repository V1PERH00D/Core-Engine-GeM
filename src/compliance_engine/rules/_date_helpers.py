"""Small, shared date helpers for certificate/authorization validity rules.

These rules must *never* consult the machine clock in core decision logic.
Validity is therefore evaluated against an explicit ``evaluation_date``
(datetime.date or an ISO ``"YYYY-MM-DD"`` string) supplied by the tender
requirement or the rule invocation.

Malformed or ambiguous dates are controlled: :func:`parse_date_value`
returns ``None`` so callers emit a deterministic ``UNVERIFIABLE`` outcome
rather than guessing or fabricating a validity conclusion.
"""

from __future__ import annotations

from datetime import date, datetime


def coerce_evaluation_date(value: object | None) -> date | None:
    """Return a ``date`` for an explicit evaluation date, or ``None``.

    Accepts :class:`datetime.date` (and :class:`datetime.datetime`)
    directly, plus ISO ``"YYYY-MM-DD"`` strings. ``None`` maps to ``None``
    ("not supplied"). Any other type raises :class:`TypeError` so an
    ambiguous parameter never silently becomes a default against the
    machine clock.
    """

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise TypeError(
                "evaluation_date must be an ISO 'YYYY-MM-DD' string, got "
                f"{value!r}"
            ) from exc
    raise TypeError(
        "evaluation_date must be a datetime.date or ISO string, got "
        f"{type(value).__name__}"
    )


def parse_date_value(value: object | None) -> date | None:
    """Parse a provider/evidence date value to ``date``, or ``None``.

    ``None`` and unparseable/malformed inputs return ``None`` so the caller
    can surface a controlled unverifiable outcome. This is intentionally
    non-raising: malformed source data is a domain outcome, not a
    programming error.
    """

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    return None


__all__ = ["coerce_evaluation_date", "parse_date_value"]