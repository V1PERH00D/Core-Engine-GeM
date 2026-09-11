"""Concurrency: lease safety and idempotent delivery."""

import threading

from infrastructure.jobs.models import Job
from infrastructure.jobs.queue import InMemoryJobQueue


def test_concurrent_claim_single_winner():
    queue = InMemoryJobQueue()
    for i in range(50):
        queue.enqueue(
            Job(job_id=f"j{i}", job_type="VERIFY", created_at=0.0, updated_at=0.0)
        )
    results: list = []
    lock = threading.Lock()

    def worker(wid):
        while True:
            claimed = queue.claim(wid)
            if claimed is None:
                return
            with lock:
                results.append((claimed.job_id, wid))

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # All 50 jobs claimed exactly once, each by one worker.
    assert len(results) == 50
    job_ids = [job_id for job_id, _ in results]
    assert len(set(job_ids)) == 50


def test_duplicate_idempotent_delivery_single_job():
    queue = InMemoryJobQueue()
    job = Job(
        job_id="j1", job_type="VERIFY", idempotency_key="k1",
        created_at=0.0, updated_at=0.0,
    )
    queue.enqueue(job)
    # A duplicate with a different job id but same key is not delivered.
    dup = Job(
        job_id="j2", job_type="VERIFY", idempotency_key="k1",
        created_at=0.0, updated_at=0.0,
    )
    returned = queue.enqueue(dup)
    assert returned.job_id == "j1"
    # Only one claimable job.
    queue.claim("w1")
    assert queue.claim("w2") is None


def test_only_lease_owner_can_ack_under_concurrency():
    queue = InMemoryJobQueue()
    queue.enqueue(Job(job_id="j1", job_type="VERIFY", created_at=0.0, updated_at=0.0))
    queue.claim("w1")
    from infrastructure.jobs.queue import JobConflictError

    try:
        queue.ack("j1", "w2")
        raised = False
    except JobConflictError:
        raised = True
    assert raised
    # Owner can still ack.
    assert queue.ack("j1", "w1").state.value == "SUCCEEDED"