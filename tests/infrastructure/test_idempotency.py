"""Idempotency key derivation and store semantics."""

from infrastructure.jobs.idempotency import (
    InMemoryIdempotencyStore,
    make_idempotency_key,
)


def test_key_deterministic():
    a = make_idempotency_key(
        submission_id="s1", stage="VERIFY", logical_input={"x": 1}
    )
    b = make_idempotency_key(
        submission_id="s1", stage="VERIFY", logical_input={"x": 1}
    )
    assert a == b


def test_key_differs_on_stage():
    a = make_idempotency_key(
        submission_id="s1", stage="VERIFY", logical_input={"x": 1}
    )
    b = make_idempotency_key(
        submission_id="s1", stage="ANALYZE", logical_input={"x": 1}
    )
    assert a != b


def test_key_differs_on_input():
    a = make_idempotency_key(
        submission_id="s1", stage="VERIFY", logical_input={"x": 1}
    )
    b = make_idempotency_key(
        submission_id="s1", stage="VERIFY", logical_input={"x": 2}
    )
    assert a != b


def test_store_get_or_create_first_wins():
    store = InMemoryIdempotencyStore()
    job, created = store.get_or_create("k", "job-1", now=1.0)
    assert created is True
    job2, created2 = store.get_or_create("k", "job-2", now=2.0)
    assert created2 is False
    assert job2 == "job-1"


def test_store_delete():
    store = InMemoryIdempotencyStore()
    store.get_or_create("k", "job-1", now=1.0)
    store.delete("k")
    assert store.get("k") is None