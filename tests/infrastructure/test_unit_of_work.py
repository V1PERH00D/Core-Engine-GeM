"""Transactional unit-of-work boundaries (in-memory)."""

from infrastructure.persistence.records import (
    BidderRecord,
    OutboxEventRecord,
)


def _bidder(bidder_id="b1", now=1.0):
    return BidderRecord(bidder_id=bidder_id, created_at=now, updated_at=now)


def test_commit_persists(uow_factory):
    with uow_factory() as uow:
        uow.repos.bidders.add(_bidder())
    # A new unit of work over the same store sees the committed write.
    with uow_factory() as uow:
        assert uow.repos.bidders.get("b1") is not None


def test_rollback_discards(uow_factory):
    uow = uow_factory()
    uow.begin()
    uow.repos.bidders.add(_bidder())
    uow.rollback()
    with uow_factory() as uow:
        assert uow.repos.bidders.get("b1") is None


def test_exception_rolls_back(uow_factory):
    try:
        with uow_factory() as uow:
            uow.repos.bidders.add(_bidder())
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with uow_factory() as uow:
        assert uow.repos.bidders.get("b1") is None


def test_domain_write_and_outbox_share_transaction(uow_factory):
    """A domain write and its outbox insert commit or vanish together."""
    uow = uow_factory()
    uow.begin()
    uow.repos.bidders.add(_bidder())
    uow.repos.outbox.add(
        OutboxEventRecord(
            event_id="o1", aggregate_type="BIDDER", aggregate_id="b1",
            event_type="BIDDER_CREATED", created_at=1.0,
        )
    )
    uow.rollback()
    with uow_factory() as uow:
        assert uow.repos.bidders.get("b1") is None
        assert uow.repos.outbox.list_unpublished() == []


def test_commit_both_visible(uow_factory):
    with uow_factory() as uow:
        uow.repos.bidders.add(_bidder())
        uow.repos.outbox.add(
            OutboxEventRecord(
                event_id="o1", aggregate_type="BIDDER", aggregate_id="b1",
                event_type="BIDDER_CREATED", created_at=1.0,
            )
        )
    with uow_factory() as uow:
        assert uow.repos.bidders.get("b1") is not None
        assert len(uow.repos.outbox.list_unpublished()) == 1
