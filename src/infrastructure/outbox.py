"""Lightweight transactional outbox publisher.

A domain transaction inserts an :class:`OutboxEventRecord` in the same
commit as the domain write (see the unit of work). A separate publisher
loop then::

    1. reads unpublished outbox entries (oldest first),
    2. enqueues a job/event through the injected ``sink``,
    3. marks the outbox entry published.

Publishing is *at-least-once* and idempotent at the consumer via the
job idempotency key; duplicate publish attempts are made safe by the
``mark_published`` guard (only an unpublished event can be marked).

This solves the classic "DB commit succeeded, queue publish failed"
problem without a distributed transaction: if the publisher crashes
after enqueue but before marking, the event is re-published (safe,
because downstream is idempotent); if it crashes before enqueue, the
event remains unpublished and is retried.
"""

from __future__ import annotations

from typing import Any, Callable

from infrastructure.persistence.records import OutboxEventRecord

#: A sink that relays one outbox event onward (e.g. into a JobQueue).
OutboxSink = Callable[[OutboxEventRecord], None]


class OutboxPublisher:
    def __init__(
        self,
        uow_factory: Callable[[], Any],
        sink: OutboxSink,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._sink = sink
        self._clock = clock if clock is not None else _default_clock

    def publish_pending(self, limit: int = 100) -> int:
        """Relay up to ``limit`` unpublished events; returns count sent.

        A sink failure leaves the event unpublished and increments its
        attempt counter, allowing later retries. Each successfully
        published event is marked (and never republished by this call).
        """
        uow = self._uow_factory()
        with uow:
            events = uow.repos.outbox.list_unpublished(limit)
            published = 0
            for event in events:
                try:
                    self._sink(event)
                except Exception:
                    uow.repos.outbox.record_attempt(event.event_id)
                    continue
                if uow.repos.outbox.mark_published(
                    event.event_id, self._clock()
                ):
                    published += 1
            return published


def _default_clock() -> float:
    import time

    return time.time()


__all__ = ["OutboxPublisher", "OutboxSink"]