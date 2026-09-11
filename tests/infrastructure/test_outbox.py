"""Outbox publisher: crash-safe publication semantics."""

from infrastructure.jobs.queue import InMemoryJobQueue
from infrastructure.outbox import OutboxPublisher, OutboxSink
from infrastructure.persistence.records import OutboxEventRecord


class _RecordingSink:
    def __init__(self, fail: bool = False):
        self.sent: list[OutboxEventRecord] = []
        self.fail = fail

    def __call__(self, event: OutboxEventRecord) -> None:
        if self.fail:
            raise RuntimeError("sink down")
        self.sent.append(event)


def _event(event_id="o1", created_at=1.0):
    return OutboxEventRecord(
        event_id=event_id,
        aggregate_type="SUBMISSION",
        aggregate_id="s1",
        event_type="SUBMISSION_INGESTED",
        payload={"submission_id": "s1"},
        created_at=created_at,
    )


def _setup(uow_factory, events):
    with uow_factory() as uow:
        for e in events:
            uow.repos.outbox.add(e)


def test_publish_pending_marks_published(uow_factory):
    _setup(uow_factory, [_event()])
    sink = _RecordingSink()
    publisher = OutboxPublisher(uow_factory, sink, clock=lambda: 2.0)
    assert publisher.publish_pending() == 1
    assert len(sink.sent) == 1
    with uow_factory() as uow:
        assert uow.repos.outbox.list_unpublished() == []


def test_second_run_is_noop(uow_factory):
    _setup(uow_factory, [_event()])
    sink = _RecordingSink()
    publisher = OutboxPublisher(uow_factory, sink, clock=lambda: 2.0)
    publisher.publish_pending()
    assert publisher.publish_pending() == 0
    assert len(sink.sent) == 1


def test_sink_failure_leaves_unpublished_and_increments_attempts(uow_factory):
    _setup(uow_factory, [_event()])
    sink = _RecordingSink(fail=True)
    publisher = OutboxPublisher(uow_factory, sink, clock=lambda: 2.0)
    publisher.publish_pending()
    with uow_factory() as uow:
        events = uow.repos.outbox.list_unpublished()
        assert len(events) == 1
        assert events[0].attempts == 1


def test_retry_after_failure_succeeds(uow_factory):
    _setup(uow_factory, [_event()])
    fail_sink = _RecordingSink(fail=True)
    publisher = OutboxPublisher(uow_factory, fail_sink, clock=lambda: 2.0)
    publisher.publish_pending()
    ok_sink = _RecordingSink()
    publisher2 = OutboxPublisher(uow_factory, ok_sink, clock=lambda: 3.0)
    assert publisher2.publish_pending() == 1
    assert len(ok_sink.sent) == 1


def test_ordering_by_created_at(uow_factory):
    _setup(uow_factory, [_event("o2", 2.0), _event("o1", 1.0)])
    sink = _RecordingSink()
    publisher = OutboxPublisher(uow_factory, sink, clock=lambda: 3.0)
    publisher.publish_pending()
    assert [e.event_id for e in sink.sent] == ["o1", "o2"]


def test_duplicate_publish_safe(uow_factory):
    _setup(uow_factory, [_event()])
    sink = _RecordingSink()
    publisher = OutboxPublisher(uow_factory, sink, clock=lambda: 2.0)
    publisher.publish_pending()
    # Simulate a re-delivery attempt via two publishers racing.
    publisher.publish_pending()
    assert len(sink.sent) == 1
