"""Evidence-grounded AI verification explanations (explanation, not risk)."""

from ai_verification.explanations.models import (
    EXPLANATION_SCHEMA_VERSION,
    ExplanationGenerationMetadata,
    ExplanationResult,
    GroundedExplanation,
    GroundingKind,
    GroundingReference,
    ValidationStatus,
)
from ai_verification.explanations.facts import FactKind, StructuredFact
from ai_verification.explanations.grounding import (
    ExplanationGrounding,
    GroundingRefKind,
)
from ai_verification.explanations.content import (
    ExplanationContent,
    ObservedFact,
    StatementType,
)
from ai_verification.explanations.provider import (
    ExplanationModel,
    ExplanationModelError,
    ExplanationModelResponse,
    ExplanationModelTimeoutError,
    ExplanationModelUnavailableError,
    ExplanationPrompt,
    HttpExplanationModel,
    MalformedModelOutputError,
    StaticExplanationModel,
)
from ai_verification.explanations.context import (
    ModelContext,
    build_context,
    render_prompt,
)
from ai_verification.explanations.validation import (
    GroundingValidator,
    ValidationIssue,
    ValidationIssueCode,
    ValidationReport,
)
from ai_verification.explanations.strategies import (
    ExplanationStrategy,
    StrategyRegistry,
    default_registry,
)
from ai_verification.explanations.engine import ExplanationEngine
from ai_verification.explanations.generator import (
    DeterministicFallbackExplanationGenerator,
    ExplanationGenerator,
    ExplanationRequest,
)
from ai_verification.explanations.pipeline import (
    ExplanationPipeline,
    to_explanation_record,
)

__all__ = [
    "EXPLANATION_SCHEMA_VERSION",
    "DeterministicFallbackExplanationGenerator",
    "ExplanationContent",
    "ExplanationEngine",
    "ExplanationGenerationMetadata",
    "ExplanationGenerator",
    "ExplanationGrounding",
    "ExplanationModel",
    "ExplanationModelError",
    "ExplanationModelResponse",
    "ExplanationModelTimeoutError",
    "ExplanationModelUnavailableError",
    "ExplanationPipeline",
    "ExplanationPrompt",
    "ExplanationRequest",
    "ExplanationResult",
    "ExplanationStrategy",
    "FactKind",
    "GroundedExplanation",
    "GroundingKind",
    "GroundingRefKind",
    "GroundingValidator",
    "HttpExplanationModel",
    "MalformedModelOutputError",
    "ModelContext",
    "ObservedFact",
    "StatementType",
    "StaticExplanationModel",
    "StrategyRegistry",
    "StructuredFact",
    "ValidationIssue",
    "ValidationIssueCode",
    "ValidationReport",
    "ValidationStatus",
    "build_context",
    "default_registry",
    "render_prompt",
    "to_explanation_record",
]
