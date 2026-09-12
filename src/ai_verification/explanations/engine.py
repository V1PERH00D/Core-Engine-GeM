"""Explanation engine: model orchestration, validation, deterministic fallback.

The engine is downstream of flag computation. It never decides the boolean
state — it only explains the state the caller supplied. It talks to an
injected :class:`ExplanationModel`; when that is absent, times out, is
unavailable, returns malformed output, or fails grounding/claim validation,
it deterministically falls back to a facts-only explanation.
"""

from __future__ import annotations

from compliance_engine.flags import get_flag_definition

from ai_verification.explanations.content import (
    ExplanationContent,
    ObservedFact,
    StatementType,
)
from ai_verification.explanations.context import build_context
from ai_verification.explanations.facts import StructuredFact
from ai_verification.explanations.generator import ExplanationRequest
from ai_verification.explanations.grounding import ExplanationGrounding
from ai_verification.explanations.models import (
    EXPLANATION_SCHEMA_VERSION,
    ExplanationGenerationMetadata,
    ExplanationResult,
    ValidationStatus,
)
from ai_verification.explanations.provider import (
    ExplanationModel,
    ExplanationModelError,
    ExplanationModelTimeoutError,
    ExplanationModelUnavailableError,
    MalformedModelOutputError,
    StaticExplanationModel,
)
from ai_verification.explanations.strategies import (
    StrategyRegistry,
    default_registry,
)
from ai_verification.explanations.validation import GroundingValidator

_STATEMENT_BY_FACT_KIND = {
    "ACTUAL_VALUE": StatementType.ACTUAL_VALUE,
    "EXPECTED_VALUE": StatementType.EXPECTED_VALUE,
    "THRESHOLD": StatementType.THRESHOLD,
    "FINANCIAL_YEAR": StatementType.FINANCIAL_YEAR,
    "VERIFICATION_STATUS": StatementType.VERIFICATION_STATUS,
    "QUALITY_STATE": StatementType.QUALITY_STATE,
    "COMPARISON_OUTCOME": StatementType.COMPARISON_OUTCOME,
    "SIMILARITY_SCORE": StatementType.SIMILARITY_SCORE,
    "SIMILARITY_THRESHOLD": StatementType.SIMILARITY_THRESHOLD,
    "IDENTIFIER": StatementType.IDENTIFIER,
    "NORMALIZED_VALUE": StatementType.NORMALIZED_VALUE,
    "DOCUMENT_NAME": StatementType.DOCUMENT_NAME,
    "DATE": StatementType.DATE,
}


class ExplanationEngine:
    """Explain one boolean flag using an optional model with fallback."""

    def __init__(
        self,
        model: ExplanationModel | None = None,
        *,
        validator: GroundingValidator | None = None,
        registry: StrategyRegistry | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self._model = model
        self._validator = validator or GroundingValidator()
        self._registry = registry or default_registry
        self._timeout_seconds = timeout_seconds
        self._fallback = StaticExplanationModel()

    def explain(
        self,
        bidder_id: str,
        flag_id: str,
        flag_state: bool,
        grounding: ExplanationGrounding | None = None,
        *,
        finding: object | None = None,
        facts: list[StructuredFact] | None = None,
        uncertainties: list[str] | None = None,
        locale: str | None = None,
        correlation_id: str | None = None,
    ) -> ExplanationResult:
        request = ExplanationRequest(
            bidder_id=bidder_id,
            flag_id=flag_id,
            flag_active=flag_state,
            finding=finding,  # type: ignore[arg-type]
            evidence_refs=list(grounding.evidence_refs) if grounding else [],
            verification_refs=list(grounding.verification_refs) if grounding else [],
            finding_refs=list(grounding.finding_refs) if grounding else [],
            document_refs=list(grounding.document_refs) if grounding else [],
            comparison_refs=list(grounding.comparison_refs) if grounding else [],
            trace_refs=list(grounding.trace_refs) if grounding else [],
            facts=list(facts or []),
            uncertainties=list(uncertainties or []),
            locale=locale,
            correlation_id=correlation_id,
        )
        return self.explain_request(request, grounding=grounding)

    def explain_request(
        self,
        request: ExplanationRequest,
        grounding: ExplanationGrounding | None = None,
    ) -> ExplanationResult:
        definition = get_flag_definition(request.flag_id)
        grounding = grounding or request.build_grounding()
        facts = list(request.facts)
        strategy = self._registry.select(definition)

        model_content, used_fallback, provider_name, model_name = (
            self._generate(request, grounding, facts)
        )

        report = self._validator.validate(
            content=model_content,
            grounding=grounding,
            facts=facts,
            flag_state=request.flag_state,
        )

        if not report.is_valid:
            content = self._build_fallback(
                definition, request.flag_state, facts, request.uncertainties, strategy
            )
            validation_status = ValidationStatus.FALLBACK
            used_fallback = True
        else:
            content = model_content
            validation_status = ValidationStatus.VALID

        return ExplanationResult(
            explanation_id=ExplanationResult.allocate_explanation_id(
                request.bidder_id, definition.flag_id, request.flag_state
            ),
            bidder_id=request.bidder_id,
            flag_id=definition.flag_id,
            flag_state=request.flag_state,
            content=content,
            grounding=grounding,
            generation=ExplanationGenerationMetadata(
                generator="explanation_engine",
                generator_version="1",
                model=model_name,
                deterministic_fallback=used_fallback,
                correlation_id=request.correlation_id,
                generator_type="engine",
                provider_name=provider_name,
                prompt_schema_version=1,
                grounding_version=grounding.grounding_version,
                validation_status=validation_status.value,
                fallback_used=used_fallback,
                input_hash=grounding.content_hash(),
            ),
            validation_status=validation_status,
            fallback_used=used_fallback,
            schema_version=EXPLANATION_SCHEMA_VERSION,
        )

    def explain_strict(
        self,
        request: ExplanationRequest,
        grounding: ExplanationGrounding | None = None,
    ) -> ExplanationResult:
        """Job-path variant: raise retryable provider failures.

        The synchronous :meth:`explain` falls back on any model failure;
        this variant lets the processing pipeline distinguish *provider
        unavailable / timeout* (raised, therefore retryable) from
        *malformed / grounding* failures (deterministic fallback).
        """
        definition = get_flag_definition(request.flag_id)
        grounding = grounding or request.build_grounding()
        facts = list(request.facts)
        strategy = self._registry.select(definition)

        model_content, used_fallback, provider_name, model_name = self._generate(
            request, grounding, facts, propagate_retryable=True
        )

        report = self._validator.validate(
            content=model_content,
            grounding=grounding,
            facts=facts,
            flag_state=request.flag_state,
        )

        if not report.is_valid:
            content = self._build_fallback(
                definition, request.flag_state, facts, request.uncertainties, strategy
            )
            validation_status = ValidationStatus.FALLBACK
            used_fallback = True
        else:
            content = model_content
            validation_status = ValidationStatus.VALID

        return ExplanationResult(
            explanation_id=ExplanationResult.allocate_explanation_id(
                request.bidder_id, definition.flag_id, request.flag_state
            ),
            bidder_id=request.bidder_id,
            flag_id=definition.flag_id,
            flag_state=request.flag_state,
            content=content,
            grounding=grounding,
            generation=ExplanationGenerationMetadata(
                generator="explanation_engine",
                generator_version="1",
                model=model_name,
                deterministic_fallback=used_fallback,
                correlation_id=request.correlation_id,
                generator_type="engine",
                provider_name=provider_name,
                prompt_schema_version=1,
                grounding_version=grounding.grounding_version,
                validation_status=validation_status.value,
                fallback_used=used_fallback,
                input_hash=grounding.content_hash(),
            ),
            validation_status=validation_status,
            fallback_used=used_fallback,
            schema_version=EXPLANATION_SCHEMA_VERSION,
        )

    # ------------------------------------------------------------------

    def _generate(
        self,
        request: ExplanationRequest,
        grounding: ExplanationGrounding,
        facts: list[StructuredFact],
        *,
        propagate_retryable: bool = False,
    ) -> tuple[ExplanationContent, bool, str | None, str | None]:
        definition = get_flag_definition(request.flag_id)
        context = build_context(
            flag_id=request.flag_id,
            flag_state=request.flag_state,
            facts=facts,
            evidence_refs=list(grounding.evidence_refs),
            verification_refs=list(grounding.verification_refs),
            finding_refs=list(grounding.finding_refs),
            uncertainties=request.uncertainties,
            locale=request.locale,
        )

        if self._model is None:
            return (
                self._build_fallback(
                    definition,
                    request.flag_state,
                    facts,
                    request.uncertainties,
                    self._registry.select(definition),
                ),
                True,
                "deterministic_fallback",
                "deterministic_fallback",
            )

        try:
            response = self._model.generate(
                context.prompt, timeout_seconds=self._timeout_seconds
            )
        except (
            ExplanationModelTimeoutError,
            ExplanationModelUnavailableError,
        ) as exc:
            if propagate_retryable:
                raise
            content = self._build_fallback(
                definition,
                request.flag_state,
                facts,
                request.uncertainties,
                self._registry.select(definition),
            )
            return content, True, "deterministic_fallback", "deterministic_fallback"
        except MalformedModelOutputError:
            content = self._build_fallback(
                definition,
                request.flag_state,
                facts,
                request.uncertainties,
                self._registry.select(definition),
            )
            return content, True, "deterministic_fallback", "deterministic_fallback"
        except ExplanationModelError:
            content = self._build_fallback(
                definition,
                request.flag_state,
                facts,
                request.uncertainties,
                self._registry.select(definition),
            )
            return content, True, "deterministic_fallback", "deterministic_fallback"

        return (
            response.content,
            False,
            response.provider_name,
            response.model_name,
        )

    def _build_fallback(
        self,
        definition,
        flag_state: bool,
        facts: list[StructuredFact],
        uncertainties: list[str],
        strategy,
    ) -> ExplanationContent:
        state_word = "true" if flag_state else "false"
        title = definition.title or definition.flag_id

        observed: list[ObservedFact] = []
        for fact in facts:
            stmt = _STATEMENT_BY_FACT_KIND.get(fact.kind.value)
            if stmt is None:
                continue
            observed.append(
                ObservedFact(
                    fact_ref=fact.fact_id,
                    statement_type=stmt,
                    source_ref=fact.source_ref,
                )
            )

        notes: list[str] = []
        note = strategy.uncertainty_note(flag_state=flag_state)
        if note:
            notes.append(note)
        notes.extend(list(uncertainties))
        if not notes:
            notes.append("No uncertainty information was supplied.")

        return ExplanationContent(
            summary=f"{title} is {state_word}.",
            detailed_explanation=_narrate(definition, flag_state, facts),
            observed_facts=observed,
            uncertainties=notes,
            evidence_refs=[f.source_ref for f in facts if f.source_ref],
            verification_refs=[
                f.verification_ref for f in facts if f.verification_ref
            ],
            finding_refs=[],
            recommended_review_actions=strategy.review_actions(
                flag_state=flag_state, facts=facts
            ),
        )
def _narrate(definition, flag_state: bool, facts: list[StructuredFact]) -> str:
    """Compose a factual, deterministic narrative from supplied facts only."""

    state_word = "is flagged" if flag_state else "is not flagged"

    thresholds = [f for f in facts if f.kind.value in ("THRESHOLD", "EXPECTED_VALUE")]
    actuals = [f for f in facts if f.kind.value == "ACTUAL_VALUE"]
    years = [f for f in facts if f.kind.value == "FINANCIAL_YEAR"]

    if thresholds or actuals or years:
        parts = [f"Flag {definition.flag_id} {state_word}."]
        if years:
            parts.append(
                "for "
                + ", ".join(
                    sorted({str(y.value) for y in years if y.value is not None})
                )
                + "."
            )
        if thresholds:
            parts.append(
                "The requirement expects a value of at least "
                + "; ".join(t.display_value() for t in thresholds)
                + "."
            )
        if actuals:
            parts.append(
                "The available evidence gives "
                + "; and ".join(a.display_value() for a in actuals)
                + "."
            )
        return " ".join(parts)

    clauses = []
    for fact in facts:
        value = fact.display_value()
        if not value:
            continue
        clauses.append(f"supplied fact {fact.fact_id} records {value}")

    if clauses:
        return (
            f"Flag {definition.flag_id} {state_word}. "
            + "; ".join(clauses)
            + "."
        )

    return (
        f"Flag {definition.flag_id} {state_word}. "
        "No structured facts were supplied to support this explanation."
    )


__all__ = ["ExplanationEngine"]