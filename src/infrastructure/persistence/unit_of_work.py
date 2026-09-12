"""Transactional unit of work boundary.

A :class:`UnitOfWork` combines the durable repositories under a single
transaction. On successful exit the transaction commits; on exception it
rolls back. This is the seam that makes the outbox pattern crash-safe:
a domain write and its outbox insert either both commit or both vanish.

Two implementations exist:

* :class:`InMemoryUnitOfWork` — snapshot/restore transaction over the
  in-memory store (deterministic, no external service).
* :class:`~infrastructure.persistence.postgres.PostgresUnitOfWork` —
  wraps a psycopg connection/transaction.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from infrastructure.persistence.memory import _Store, InMemoryRepositories


@runtime_checkable
class UnitOfWork(Protocol):
    """Transactional boundary exposing repository bundles.

    ``repos`` carries the repository attributes used by domain/services
    code; attribute names match the table/entity names.
    """

    repos: InMemoryRepositories

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> "UnitOfWork": ...
    def __exit__(self, exc_type, exc, tb) -> bool: ...


class InMemoryUnitOfWork:
    """Snapshot-based transaction over the in-memory store."""

    def __init__(self, store: _Store | None = None) -> None:
        self._store = store if store is not None else _Store()
        self._repos = InMemoryRepositories(self._store)
        self._snapshot: dict | None = None
        self._active = False

    @property
    def repos(self) -> InMemoryRepositories:
        return self._repos

    def begin(self) -> "InMemoryUnitOfWork":
        if self._active:
            raise RuntimeError("Unit of work already active.")
        self._snapshot = self._store.snapshot()
        self._active = True
        return self

    def commit(self) -> None:
        if not self._active:
            return
        self._snapshot = None
        self._active = False

    def rollback(self) -> None:
        if not self._active:
            return
        if self._snapshot is not None:
            self._store.restore(self._snapshot)
        self._snapshot = None
        self._active = False

    def close(self) -> None:
        self.rollback()

    def __enter__(self) -> "InMemoryUnitOfWork":
        return self.begin()

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.rollback()
        else:
            self.commit()
        return False


__all__ = ["InMemoryUnitOfWork", "UnitOfWork"]