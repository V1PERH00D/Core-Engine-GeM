"""LLM / explanation-model provider abstraction.

The explanation engine talks to a generation model only through the
:class:`ExplanationModel` protocol. Providers never live in domain models,
and a provider must *never* silently fall back: failures are raised as
typed exceptions so the engine (not the provider) can decide to use the
deterministic fallback.

Two concrete implementations are provided:

* :class:`StaticExplanationModel` — deterministic fake for tests and local
  development. It builds an :class:`ExplanationContent` directly from the
  supplied facts and never calls a network.
* :class:`HttpExplanationModel` — a production-shaped HTTP seam. It is
  provider-agnostic: a caller injects a ``send`` callable and a response
  parser; the model only validates the result into the typed response
  envelope. No Kimi-specific semantics are hard-coded here.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ai_verification.explanations.content import (
    ExplanationContent,
    ObservedFact,
    StatementType,
)
from ai_verification.explanations.facts import StructuredFact

PROMPT_SCHEMA_VERSION: int = 1


# ---------------------------------------------------------------------------
# Prompts and responses
# ---------------------------------------------------------------------------


class ExplanationPrompt(BaseModel):
    """The controlled, minimal context sent to a generation model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    flag_id: str
    flag_state: bool
    flag_title: str | None = None
    flag_description: str | None = None

    facts: tuple[StructuredFact, ...] = ()

    evidence_refs: tuple[str, ...] = ()
    verification_refs: tuple[str, ...] = ()
    finding_refs: tuple[str, ...] = ()

    uncertainties: tuple[str, ...] = ()

    locale: str | None = None
    prompt_schema_version: int = PROMPT_SCHEMA_VERSION


class ExplanationModelResponse(BaseModel):
    """A validated structured response from the generation model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: ExplanationContent
    model_name: str | None = None
    provider_name: str | None = None
    prompt_schema_version: int = PROMPT_SCHEMA_VERSION
    response_metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Errors (explicit, no silent fallback inside providers)
# ---------------------------------------------------------------------------


class ExplanationModelError(Exception):
    """Base error for any explanation-model failure."""


class ExplanationModelUnavailableError(ExplanationModelError):
    """The provider could not be reached or is not configured."""


class ExplanationModelTimeoutError(ExplanationModelError):
    """The provider exceeded the requested timeout."""


class MalformedModelOutputError(ExplanationModelError):
    """The model returned an unparseable / structurally invalid output."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ExplanationModel(Protocol):
    """Dependency-injected seam for generating an explanation."""

    def generate(
        self,
        prompt: ExplanationPrompt,
        *,
        timeout_seconds: float | None = None,
    ) -> ExplanationModelResponse: ...


# ---------------------------------------------------------------------------
# Deterministic static provider (tests / local dev)
# ---------------------------------------------------------------------------


class StaticExplanationModel:
    """Deterministic provider that composes content from supplied facts.

    It never invents a value: the summary, observed facts, and review
    actions are all derived from the supplied :class:`ExplanationPrompt`.
    """

    def __init__(
        self, *, model_name: str = "static", provider_name: str = "static"
    ) -> None:
        self._model_name = model_name
        self._provider_name = provider_name

    def generate(
        self,
        prompt: ExplanationPrompt,
        *,
        timeout_seconds: float | None = None,
    ) -> ExplanationModelResponse:
        state_word = "true" if prompt.flag_state else "false"
        title = prompt.flag_title or prompt.flag_id

        observed: list[ObservedFact] = []
        fact_sentences: list[str] = []
        for fact in prompt.facts:
            mapping = _STATEMENT_TYPE_BY_FACT_KIND.get(fact.kind.value)
            if mapping is None:
                continue
            observed.append(
                ObservedFact(
                    fact_ref=fact.fact_id,
                    statement_type=mapping,
                    source_ref=fact.source_ref,
                )
            )
            fact_sentences.append(_describe_fact(fact))

        if fact_sentences:
            detail = "; ".join(fact_sentences) + "."
        else:
            detail = (
                f"Flag {prompt.flag_id} is {state_word}. "
                "No structured facts were supplied to support this explanation."
            )

        summary = f"{title} is {state_word}."
        uncertainties = list(prompt.uncertainties)
        if not uncertainties:
            uncertainties.append("No uncertainty information was supplied.")

        return ExplanationModelResponse(
            content=ExplanationContent(
                summary=summary,
                detailed_explanation=detail,
                observed_facts=observed,
                uncertainties=uncertainties,
                evidence_refs=list(prompt.evidence_refs),
                verification_refs=list(prompt.verification_refs),
                finding_refs=list(prompt.finding_refs),
                recommended_review_actions=[
                    "Review the cited evidence and verification records "
                    "before taking action."
                ],
            ),
            model_name=self._model_name,
            provider_name=self._provider_name,
            prompt_schema_version=prompt.prompt_schema_version,
        )


_STATEMENT_TYPE_BY_FACT_KIND = {
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


_FACT_LABELS = {
    "ACTUAL_VALUE": "actual value",
    "EXPECTED_VALUE": "expected value",
    "THRESHOLD": "threshold",
    "FINANCIAL_YEAR": "financial year",
    "VERIFICATION_STATUS": "verification status",
    "QUALITY_STATE": "quality state",
    "COMPARISON_OUTCOME": "comparison outcome",
    "SIMILARITY_SCORE": "similarity score",
    "SIMILARITY_THRESHOLD": "similarity threshold",
    "IDENTIFIER": "identifier",
    "NORMALIZED_VALUE": "normalized value",
    "DOCUMENT_NAME": "document",
    "DATE": "date",
}


def _describe_fact(fact: StructuredFact) -> str:
    label = _FACT_LABELS.get(fact.kind.value, "fact")
    unit = f" {fact.unit}" if fact.unit else ""
    value = fact.display_value()
    if not value:
        value = str(fact.value) if fact.value is not None else "unknown"
    return f"{label} {value}{unit}"


# ---------------------------------------------------------------------------
# Production-shaped HTTP seam (provider-agnostic)
# ---------------------------------------------------------------------------


class HttpExplanationModel:
    """Provider-agnostic HTTP model with explicit failure semantics.

    ``send`` is injected and returns a raw response payload; ``parse`` turns
    that payload into an :class:`ExplanationContent` (or raises
    ``MalformedModelOutputError``). The model only validates and envelopes
    the result. Provider-specific request/response shapes live entirely in
    those injected callables, not here.
    """

    def __init__(
        self,
        *,
        model_name: str,
        provider_name: str,
        send: Callable[[dict[str, Any], float | None], dict[str, Any]],
        parse: Callable[[dict[str, Any]], ExplanationContent],
    ) -> None:
        self._model_name = model_name
        self._provider_name = provider_name
        self._send = send
        self._parse = parse

    def generate(
        self,
        prompt: ExplanationPrompt,
        *,
        timeout_seconds: float | None = None,
    ) -> ExplanationModelResponse:
        request_payload = prompt.model_dump(mode="json")
        try:
            raw = self._send(request_payload, timeout_seconds)
        except ExplanationModelError:
            raise
        except TimeoutError as exc:
            raise ExplanationModelTimeoutError(str(exc)) from exc
        except Exception as exc:  # network / transport failure
            raise ExplanationModelUnavailableError(str(exc)) from exc

        try:
            content = self._parse(raw)
        except MalformedModelOutputError:
            raise
        except Exception as exc:
            raise MalformedModelOutputError(str(exc)) from exc

        if not isinstance(content, ExplanationContent):
            raise MalformedModelOutputError(
                "Parser did not return an ExplanationContent."
            )

        return ExplanationModelResponse(
            content=content,
            model_name=self._model_name,
            provider_name=self._provider_name,
            prompt_schema_version=prompt.prompt_schema_version,
            response_metadata={"raw": _safe_metadata(raw)},
        )


def _safe_metadata(raw: Any) -> dict[str, Any]:
    """Return a JSON-safe, bounded metadata snapshot (never secrets)."""

    if isinstance(raw, dict):
        return {
            k: v
            for k, v in raw.items()
            if isinstance(v, (str, int, float, bool, type(None)))
        }
    return {}


__all__ = [
    "PROMPT_SCHEMA_VERSION",
    "ExplanationModel",
    "ExplanationModelError",
    "ExplanationModelResponse",
    "ExplanationModelTimeoutError",
    "ExplanationModelUnavailableError",
    "ExplanationPrompt",
    "HttpExplanationModel",
    "MalformedModelOutputError",
    "StaticExplanationModel",
]