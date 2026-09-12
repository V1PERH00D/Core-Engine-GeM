"""Processing pipeline stages and validated state transitions.

The pipeline is the *processing* state of a submission. It is distinct
from any domain/compliance state: a submission can be COMPLETE as a
pipeline while containing FAIL compliance results, and a pipeline can
be FAILED even though every domain artefact produced so far is valid.

Linear flow::

    INGESTED
      -> NORMALIZED
      -> VERIFICATION_PENDING
      -> VERIFIED
      -> AI_ANALYSIS_PENDING
      -> AI_ANALYZED
      -> EXPLANATION_PENDING
      -> EXPLANATION_READY
      -> COMPLETE

FAILED is reachable from every non-terminal stage and represents an
operator-visible halt; resuming a FAILED submission moves it back to
an earlier linear stage (retry from the last good stage). Same-state
transitions are allowed so workers can re-enter a stage idempotently.
"""

from __future__ import annotations

from enum import StrEnum


class ProcessingStage(StrEnum):
    INGESTED = "INGESTED"
    NORMALIZED = "NORMALIZED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    VERIFIED = "VERIFIED"
    AI_ANALYSIS_PENDING = "AI_ANALYSIS_PENDING"
    AI_ANALYZED = "AI_ANALYZED"
    EXPLANATION_PENDING = "EXPLANATION_PENDING"
    EXPLANATION_READY = "EXPLANATION_READY"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


#: Linear, happy-path order. Index correspondence gives the successor.
LINEAR_STAGES: tuple[ProcessingStage, ...] = (
    ProcessingStage.INGESTED,
    ProcessingStage.NORMALIZED,
    ProcessingStage.VERIFICATION_PENDING,
    ProcessingStage.VERIFIED,
    ProcessingStage.AI_ANALYSIS_PENDING,
    ProcessingStage.AI_ANALYZED,
    ProcessingStage.EXPLANATION_PENDING,
    ProcessingStage.EXPLANATION_READY,
    ProcessingStage.COMPLETE,
)

#: Successor map for the happy path; COMPLETE has no successor.
SUCCESSOR: dict[ProcessingStage, ProcessingStage] = {
    stage: LINEAR_STAGES[i + 1] for i, stage in enumerate(LINEAR_STAGES[:-1])
}

#: Terminal stages; no further transitions are allowed out of them.
TERMINAL_STAGES: frozenset[ProcessingStage] = frozenset({ProcessingStage.COMPLETE})


def _allowed_transitions() -> dict[ProcessingStage, frozenset[ProcessingStage]]:
    allowed: dict[ProcessingStage, set[ProcessingStage]] = {}
    for stage in LINEAR_STAGES:
        targets = {stage, ProcessingStage.FAILED}
        successor = SUCCESSOR.get(stage)
        if successor is not None:
            targets.add(successor)
        allowed[stage] = targets
    # FINAL state: only idempotent re-entry.
    allowed[ProcessingStage.COMPLETE] = {ProcessingStage.COMPLETE}
    # FAILED may resume to any linear stage (retry from last good stage).
    allowed[ProcessingStage.FAILED] = set(LINEAR_STAGES) | {ProcessingStage.FAILED}
    return {stage: frozenset(t) for stage, t in allowed.items()}


ALLOWED_TRANSITIONS: dict[ProcessingStage, frozenset[ProcessingStage]] = (
    _allowed_transitions()
)


class InvalidStateTransitionError(ValueError):
    """Raised when a processing state transition is not allowed."""


def validate_transition(
    current: ProcessingStage, target: ProcessingStage
) -> ProcessingStage:
    """Validate a transition and return ``target``.

    Raises :class:`InvalidStateTransitionError` for disallowed moves
    such as skipping stages or leaving a terminal state.
    """

    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransitionError(
            f"Invalid processing transition {current.value} -> {target.value}"
        )
    return target


def next_stage(stage: ProcessingStage) -> ProcessingStage | None:
    """Return the linear successor of ``stage``, or ``None``."""
    return SUCCESSOR.get(stage)


__all__ = [
    "ALLOWED_TRANSITIONS",
    "InvalidStateTransitionError",
    "LINEAR_STAGES",
    "ProcessingStage",
    "SUCCESSOR",
    "TERMINAL_STAGES",
    "next_stage",
    "validate_transition",
]
