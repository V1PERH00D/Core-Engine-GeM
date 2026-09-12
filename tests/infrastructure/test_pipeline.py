"""Processing pipeline stage transitions."""

import pytest

from infrastructure.pipeline import (
    InvalidStateTransitionError,
    LINEAR_STAGES,
    ProcessingStage,
    next_stage,
    validate_transition,
)


def test_linear_flow_names():
    assert [s.value for s in LINEAR_STAGES] == [
        "INGESTED",
        "NORMALIZED",
        "VERIFICATION_PENDING",
        "VERIFIED",
        "AI_ANALYSIS_PENDING",
        "AI_ANALYZED",
        "EXPLANATION_PENDING",
        "EXPLANATION_READY",
        "COMPLETE",
    ]


def test_next_stage_sequence():
    assert next_stage(ProcessingStage.INGESTED) is ProcessingStage.NORMALIZED
    assert next_stage(ProcessingStage.EXPLANATION_READY) is ProcessingStage.COMPLETE
    assert next_stage(ProcessingStage.COMPLETE) is None


def test_forward_transition_allowed():
    assert (
        validate_transition(ProcessingStage.INGESTED, ProcessingStage.NORMALIZED)
        is ProcessingStage.NORMALIZED
    )


def test_skip_stage_rejected():
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(ProcessingStage.INGESTED, ProcessingStage.VERIFIED)


def test_backward_transition_rejected():
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(ProcessingStage.VERIFIED, ProcessingStage.INGESTED)


def test_same_stage_reentry_allowed():
    assert (
        validate_transition(ProcessingStage.VERIFIED, ProcessingStage.VERIFIED)
        is ProcessingStage.VERIFIED
    )


def test_failed_reachable_from_any():
    # COMPLETE is terminal; FAILED is reachable from every non-terminal stage.
    for stage in LINEAR_STAGES[:-1]:
        assert validate_transition(stage, ProcessingStage.FAILED) is ProcessingStage.FAILED


def test_failed_can_resume_to_linear():
    assert (
        validate_transition(ProcessingStage.FAILED, ProcessingStage.VERIFIED)
        is ProcessingStage.VERIFIED
    )


def test_complete_is_terminal():
    with pytest.raises(InvalidStateTransitionError):
        validate_transition(ProcessingStage.COMPLETE, ProcessingStage.EXPLANATION_READY)