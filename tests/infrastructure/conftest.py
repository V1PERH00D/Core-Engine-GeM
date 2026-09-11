"""Shared test fixtures for the infrastructure suite."""

from __future__ import annotations

import pytest

from infrastructure.jobs.models import Job
from infrastructure.jobs.queue import InMemoryJobQueue


class ManualClock:
    """Deterministic, manually advanced clock."""

    def __init__(self, start: float = 1000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float = 1.0) -> None:
        self.value += seconds


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def queue(clock) -> InMemoryJobQueue:
    return InMemoryJobQueue(clock=clock)


def make_job(clock: ManualClock, **overrides):
    """Build a PENDING job with sensible defaults."""
    defaults = dict(
        job_id="job-1",
        job_type="VERIFY",
        created_at=clock(),
        updated_at=clock(),
    )
    defaults.update(overrides)
    return Job(**defaults)


@pytest.fixture
def make_job_factory(clock):
    def _make(**overrides):
        return make_job(clock, **overrides)

    return _make


@pytest.fixture
def uow():
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    return InMemoryUnitOfWork()


@pytest.fixture
def uow_factory():
    from infrastructure.persistence.memory import _Store
    from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork

    store = _Store()

    def _factory():
        return InMemoryUnitOfWork(store)

    return _factory