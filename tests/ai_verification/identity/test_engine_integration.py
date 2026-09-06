"""Tests for the integration with the AI VerificationEngine.

These tests confirm that the identity reconciliation engine can be
wired into the existing :class:`VerificationEngine` cleanly, and
that the existing cross-bidder / engine tests stay green.
"""

from __future__ import annotations

from ai_verification.engine import VerificationEngine
from ai_verification.identity import (
    CROSS_SOURCE_IDENTITY_MISMATCH,
    IdentityReconciliationEngine,
)
from ai_verification.models import VerificationInput, VerificationResult

from tests.ai_verification.identity._builders import (
    gst_verified,
    pan_verified,
)


def test_engine_without_identity_component_unaffected() -> None:
    """Default VerificationEngine must not emit identity findings."""

    engine = VerificationEngine()
    input_data = VerificationInput(
        bidder_id="bidder-1",
        verification_records=[
            gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
            pan_verified(name_on_pan="ACME TRADING PRIVATE LIMITED"),
        ],
    )
    result = engine.run(input_data)
    assert isinstance(result, VerificationResult)
    # No identity findings because the component was not enabled.
    flags = {f.flag_id for f in result.findings}
    assert CROSS_SOURCE_IDENTITY_MISMATCH not in flags


def test_engine_with_identity_component_emits_finding_on_mismatch() -> None:
    """The wired engine must emit CROSS_SOURCE_IDENTITY_MISMATCH findings."""

    engine = VerificationEngine(
        identity_reconciliation_engine=IdentityReconciliationEngine(),
    )
    input_data = VerificationInput(
        bidder_id="bidder-1",
        verification_records=[
            gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
            pan_verified(name_on_pan="ACME TRADING PRIVATE LIMITED"),
        ],
    )
    result = engine.run(input_data)
    identity_findings = [
        f
        for f in result.findings
        if f.flag_id == CROSS_SOURCE_IDENTITY_MISMATCH
    ]
    assert len(identity_findings) == 1
    assert identity_findings[0].bidder_id == "bidder-1"
    assert identity_findings[0].severity.value == "HIGH"


def test_engine_with_identity_component_no_mismatch_means_no_finding() -> None:
    engine = VerificationEngine(
        identity_reconciliation_engine=IdentityReconciliationEngine(),
    )
    input_data = VerificationInput(
        bidder_id="bidder-1",
        verification_records=[
            gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
            pan_verified(name_on_pan="ACME ENTERPRISES PRIVATE LIMITED"),
        ],
    )
    result = engine.run(input_data)
    flags = {f.flag_id for f in result.findings}
    assert CROSS_SOURCE_IDENTITY_MISMATCH not in flags


def test_engine_with_identity_component_handles_empty_records() -> None:
    """Empty verification list must not raise and must not emit findings."""

    engine = VerificationEngine(
        identity_reconciliation_engine=IdentityReconciliationEngine(),
    )
    input_data = VerificationInput(
        bidder_id="bidder-1", verification_records=[]
    )
    result = engine.run(input_data)
    flags = {f.flag_id for f in result.findings}
    assert CROSS_SOURCE_IDENTITY_MISMATCH not in flags


def test_engine_does_not_mutate_input_when_identity_enabled() -> None:
    """The integration must preserve the existing non-mutation contract."""

    engine = VerificationEngine(
        identity_reconciliation_engine=IdentityReconciliationEngine(),
    )
    input_data = VerificationInput(
        bidder_id="bidder-1",
        verification_records=[
            gst_verified(legal_name="ACME ENTERPRISES PRIVATE LIMITED"),
            pan_verified(name_on_pan="ACME TRADING PRIVATE LIMITED"),
        ],
    )
    before = input_data.model_dump()
    engine.run(input_data)
    after = input_data.model_dump()
    assert before == after


def test_engine_identity_finding_carries_verification_refs() -> None:
    """The wired engine must propagate verification_ids into findings."""

    engine = VerificationEngine(
        identity_reconciliation_engine=IdentityReconciliationEngine(),
    )
    input_data = VerificationInput(
        bidder_id="bidder-1",
        verification_records=[
            gst_verified(
                verification_id="V-GST-001",
                legal_name="ACME ENTERPRISES PRIVATE LIMITED",
            ),
            pan_verified(
                verification_id="V-PAN-001",
                name_on_pan="ACME TRADING PRIVATE LIMITED",
            ),
        ],
    )
    result = engine.run(input_data)
    identity_findings = [
        f
        for f in result.findings
        if f.flag_id == CROSS_SOURCE_IDENTITY_MISMATCH
    ]
    assert len(identity_findings) == 1
    assert identity_findings[0].verification_refs == [
        "V-GST-001",
        "V-PAN-001",
    ]