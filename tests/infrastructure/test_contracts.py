"""Contract tests: adapters satisfy the same interfaces as the fakes.

Also validates the SQL migration DDL covers the documented entities and
provides opt-in (env-gated) integration smoke tests that are skipped by
default so the normal suite needs no external services.
"""

import os

import pytest

from infrastructure.artifacts import (
    ArtifactStore,
    FilesystemArtifactStore,
    InMemoryArtifactStore,
)
from infrastructure.jobs.durable import DurableJobQueue
from infrastructure.jobs.queue import InMemoryJobQueue, JobQueue
from infrastructure.persistence.schema import MIGRATIONS
from infrastructure.persistence.unit_of_work import InMemoryUnitOfWork, UnitOfWork


def test_inmemory_queue_satisfies_jobqueue_interface():
    queue = InMemoryJobQueue()
    for method in ("enqueue", "claim", "renew_lease", "ack", "fail", "cancel",
                   "recover_stale", "get", "find_by_idempotency_key"):
        assert callable(getattr(queue, method, None))


def test_inmemory_artifact_store_is_runtime_checkable():
    assert isinstance(InMemoryArtifactStore(), ArtifactStore)


def test_filesystem_artifact_store_is_runtime_checkable(tmp_path):
    assert isinstance(FilesystemArtifactStore(tmp_path), ArtifactStore)


def test_inmemory_uow_is_runtime_checkable():
    assert isinstance(InMemoryUnitOfWork(), UnitOfWork)


def test_durable_queue_satisfies_jobqueue_interface():
    queue = InMemoryJobQueue()
    uow_factory = lambda: InMemoryUnitOfWork()  # noqa: E731
    durable = DurableJobQueue(queue, uow_factory)
    for method in ("enqueue", "claim", "renew_lease", "ack", "fail", "cancel",
                   "recover_stale", "get", "find_by_idempotency_key"):
        assert callable(getattr(durable, method, None))


def test_redis_adapter_importable_without_connection():
    from infrastructure.jobs.redis_queue import RedisJobQueue, RedisIdempotencyStore  # noqa: F401


def test_migrations_cover_documented_tables():
    sql = "\n".join(m.sql for m in MIGRATIONS)
    for table in (
        "bidders",
        "submissions",
        "documents",
        "evidence",
        "verifications",
        "compliance_results",
        "findings",
        "explanations",
        "flag_states",
        "flag_snapshots",
        "processing_jobs",
        "audit_events",
        "outbox_events",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql


@pytest.mark.integration
@pytest.mark.skipif(not os.environ.get("TEST_REDIS_URL"), reason="no TEST_REDIS_URL")
def test_redis_queue_contract_against_live_server():
    import redis

    from infrastructure.jobs.models import Job
    from infrastructure.jobs.redis_queue import RedisJobQueue

    client = redis.Redis.from_url(os.environ["TEST_REDIS_URL"])
    queue = RedisJobQueue(client, namespace="gem:test:contract")
    now = 1.0
    queue.enqueue(
        Job(job_id="j1", job_type="VERIFY", created_at=now, updated_at=now)
    )
    claimed = queue.claim("w1")
    assert claimed is not None and claimed.job_id == "j1"
    acked = queue.ack("j1", "w1")
    assert acked.state.value == "SUCCEEDED"


@pytest.mark.integration
@pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="no TEST_DATABASE_URL"
)
def test_postgres_uow_contract_against_live_server():
    import psycopg

    from infrastructure.persistence.postgres import (
        PostgresUnitOfWork,
        apply_migrations,
    )

    conn = psycopg.connect(os.environ["TEST_DATABASE_URL"])
    try:
        apply_migrations(conn)
        with PostgresUnitOfWork(conn) as uow:
            from infrastructure.persistence.records import BidderRecord

            uow.repos.bidders.add(
                BidderRecord(bidder_id="b-test", created_at=1.0, updated_at=1.0)
            )
        assert uow.repos.bidders.get("b-test") is not None
    finally:
        conn.close()