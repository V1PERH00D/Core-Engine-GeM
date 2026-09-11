"""Persistence-layer error taxonomy.

These exceptions are shared by the in-memory and PostgreSQL repository
implementations so callers can handle invariants uniformly regardless of
backend. ``DuplicateRecordError`` and ``MissingReferenceError`` mirror
PostgreSQL's UNIQUE / FOREIGN KEY violations.
"""

from __future__ import annotations


class IntegrityError(RuntimeError):
    """Base class for durable invariants violations."""


class DuplicateRecordError(IntegrityError):
    """A primary key or unique constraint was violated."""


class MissingReferenceError(IntegrityError):
    """A foreign-key target does not exist."""


class RecordNotFoundError(LookupError):
    """A record was requested that does not exist."""


__all__ = [
    "DuplicateRecordError",
    "IntegrityError",
    "MissingReferenceError",
    "RecordNotFoundError",
]