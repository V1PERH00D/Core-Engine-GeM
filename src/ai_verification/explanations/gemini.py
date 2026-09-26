"""Gemini-backed explanation model: the real LLM provider.

This module implements the existing :class:`ExplanationModel` contract
(:mod:`ai_verification.explanations.provider`) against the Gemini
``generateContent`` API. It is deliberately narrow:

* The model **only explains**. It receives an :class:`ExplanationPrompt`
  whose boolean ``flag_state`` was fixed upstream by the deterministic
  compliance/verification engines. It never decides or changes a flag,
  never computes severity or risk, and never invents evidence — the
  rendered prompt carries the system-level grounding rules and every
  untrusted evidence string is wrapped in a ``<<<UNTRUSTED_EVIDENCE_DATA``
  block by :mod:`ai_verification.explanations.context`.
* The provider **never silently falls back**. Every failure mode is a
  typed :class:`ExplanationModelError` subclass so the *engine* decides
  to use the deterministic fallback (and the job pipeline decides what
  is retryable).
* No credential is hardcoded. The API key comes from the
  ``GEMINI_API_KEY`` environment variable (or an explicit constructor
  argument); the model name comes from ``GEMINI_MODEL``. Unit tests never
  need a key: they inject the ``poster`` seam or use
  :class:`StaticExplanationModel` / a mock instead.

Transport uses the Python standard library only (``http.client`` over
HTTPS), mirroring the ``PanHttpClient`` pattern used elsewhere in this
repository — no third-party HTTP dependency is introduced. The
``poster`` callable is the test seam; when supplied, no network access
is performed.

Environment variables
---------------------

``GEMINI_API_KEY``
    Required to *use* the live provider. Absent/blank -> ``from_env()``
    returns ``None`` and callers keep the deterministic fallback.
``GEMINI_MODEL``
    Optional model name; defaults to :data:`DEFAULT_GEMINI_MODEL`.
``GEMINI_API_BASE_URL``
    Optional base URL override (must be ``https://``); defaults to
    :data:`DEFAULT_BASE_URL`.
``GEMINI_TIMEOUT_SECONDS``
    Optional per-request timeout override; defaults to
    :data:`DEFAULT_TIMEOUT_SECONDS`.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
from typing import Any, Callable

from ai_verification.explanations.content import (
    ExplanationContent,
    ObservedFact,
    StatementType,
)
from ai_verification.explanations.context import SYSTEM_PROMPT, render_prompt
from ai_verification.explanations.provider import (
    ExplanationModelError,
    ExplanationModelResponse,
    ExplanationModelTimeoutError,
    ExplanationModelUnavailableError,
    ExplanationPrompt,
    MalformedModelOutputError,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Environment variable holding the Gemini API key (never hardcoded).
GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
#: Environment variable holding the model name.
GEMINI_MODEL_ENV = "GEMINI_MODEL"
#: Optional environment variable overriding the API base URL.
GEMINI_BASE_URL_ENV = "GEMINI_API_BASE_URL"
#: Optional environment variable overriding the request timeout.
GEMINI_TIMEOUT_ENV = "GEMINI_TIMEOUT_SECONDS"

#: Default model when ``GEMINI_MODEL`` is not set.
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
#: Public Gemini API host. The API key travels in the ``x-goog-api-key``
#: request header, never in the URL.
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"
API_PATH_TEMPLATE = "/v1beta/models/{model}:generateContent"
#: Default per-request timeout in seconds.
DEFAULT_TIMEOUT_SECONDS = 30.0

PROVIDER_NAME = "gemini"

#: Output contract appended to the typed prompt so the live model returns
#: *only* explanation text and cannot drift into decision-making.
OUTPUT_CONTRACT = (
    "TASK: Explain this finding for a human procurement officer.\n"
    "- Explain the flag state shown above; the boolean FLAG_STATE is final "
    "and was decided upstream by deterministic rules.\n"
    "- Use ONLY the supplied facts and references. Do not invent numbers, "
    "dates, years, identifiers, documents, organizations, or evidence.\n"
    "- Do not make or change the compliance decision and do not suggest "
    "the flag should be different.\n"
    "- Do not assign any severity, risk, score, or priority.\n"
    "- Do not claim fraud, collusion, cartel behaviour, forgery, or intent "
    "unless those exact conclusions are explicitly present in the supplied "
    "evidence and finding semantics.\n"
    "- Return ONLY the explanation text: no JSON, no markdown headers, no "
    "preamble, no sign-off."
)

#: Injected HTTP seam. Signature:
#: ``poster(url, body, headers, timeout_seconds) -> (response_text, status)``.
#: Test doubles never touch the network.
Poster = Callable[[str, bytes, dict[str, str], float], tuple[str, int]]

class GeminiExplanationModel:
    """``ExplanationModel`` backed by the Gemini ``generateContent`` API.

    The provider translates the typed :class:`ExplanationPrompt` into the
    guarded, rendered prompt string (system rules + untrusted-data blocks),
    POSTs it, and validates the plain-text answer into the structured
    :class:`ExplanationContent` envelope. It never mutates the prompt,
    never sets the flag, and never emits severity/risk.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        poster: Poster | None = None,
    ) -> None:
        self._api_key = api_key or ""
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = float(timeout_seconds)
        self._poster = poster

    # ------------------------------------------------------------------
    # Construction from environment
    # ------------------------------------------------------------------

    @classmethod
    def from_env(
        cls, env: dict[str, str] | None = None
    ) -> "GeminiExplanationModel | None":
        """Build a provider from the environment, or ``None``.

        Returns ``None`` when ``GEMINI_API_KEY`` is absent or blank so the
        caller keeps the deterministic fallback. Never raises for missing
        configuration; the key is only read, never logged or persisted.
        """

        env = env if env is not None else dict(os.environ)
        api_key = (env.get(GEMINI_API_KEY_ENV) or "").strip()
        if not api_key:
            return None
        model = (env.get(GEMINI_MODEL_ENV) or "").strip() or DEFAULT_GEMINI_MODEL
        base_url = (
            env.get(GEMINI_BASE_URL_ENV) or ""
        ).strip() or DEFAULT_BASE_URL
        raw_timeout = (env.get(GEMINI_TIMEOUT_ENV) or "").strip()
        timeout = (
            float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_SECONDS
        )
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout,
        )

    @property
    def model_name(self) -> str:
        return self._model

    # ------------------------------------------------------------------
    # ExplanationModel contract
    # ------------------------------------------------------------------

    def generate(
        self,
        prompt: ExplanationPrompt,
        *,
        timeout_seconds: float | None = None,
    ) -> ExplanationModelResponse:
        if not self._api_key:
            raise ExplanationModelUnavailableError(
                f"{GEMINI_API_KEY_ENV} is not configured; the Gemini "
                "explanation provider is unavailable."
            )

        url = self._base_url + API_PATH_TEMPLATE.format(model=self._model)
        body = json.dumps(
            self._request_body(prompt), ensure_ascii=True
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "x-goog-api-key": self._api_key,
        }
        timeout = (
            self._timeout_seconds if timeout_seconds is None else timeout_seconds
        )

        try:
            if self._poster is not None:
                text, status = self._poster(url, body, headers, timeout)
            else:
                text, status = self._post_https(url, body, headers, timeout)
        except ExplanationModelError:
            raise
        except (TimeoutError, socket.timeout) as exc:
            raise ExplanationModelTimeoutError(
                f"Gemini request timed out after {timeout}s."
            ) from exc
        except (ssl.SSLError, OSError) as exc:
            raise ExplanationModelUnavailableError(
                f"Gemini request failed at the transport layer: {exc}"
            ) from exc

        if status < 200 or status >= 300:
            # Do not echo the response body: it may contain request details.
            raise ExplanationModelUnavailableError(
                f"Gemini API returned HTTP {status}."
            )

        answer = self._parse_answer(text)
        content = self._content_from_text(answer, prompt)
        return ExplanationModelResponse(
            content=content,
            model_name=self._model,
            provider_name=PROVIDER_NAME,
            prompt_schema_version=prompt.prompt_schema_version,
            response_metadata={"http_status": status},
        )

    # ------------------------------------------------------------------
    # Request construction
    # ------------------------------------------------------------------

    def _request_body(self, prompt: ExplanationPrompt) -> dict[str, Any]:
        """Gemini ``generateContent`` payload for one explanation."""

        user_text = render_prompt(prompt) + "\n\n" + OUTPUT_CONTRACT
        return {
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [
                {"role": "user", "parts": [{"text": user_text}]},
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 1024,
            },
        }

    # ------------------------------------------------------------------
    # Response handling
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_answer(raw_text: str) -> str:
        """Extract the explanation text from a Gemini response payload."""

        try:
            payload = json.loads(raw_text)
        except (ValueError, TypeError) as exc:
            raise MalformedModelOutputError(
                "Gemini response is not valid JSON."
            ) from exc
        if not isinstance(payload, dict):
            raise MalformedModelOutputError(
                "Gemini response is not a JSON object."
            )

        feedback = payload.get("promptFeedback")
        if isinstance(feedback, dict) and feedback.get("blockReason"):
            raise MalformedModelOutputError(
                "Gemini blocked the request ("
                + str(feedback.get("blockReason"))
                + ")."
            )

        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise MalformedModelOutputError(
                "Gemini response contains no candidates."
            )
        first = candidates[0]
        if not isinstance(first, dict):
            raise MalformedModelOutputError("Gemini candidate is malformed.")
        content = first.get("content") or {}
        parts = content.get("parts") if isinstance(content, dict) else None
        if not isinstance(parts, list) or not parts:
            raise MalformedModelOutputError(
                "Gemini candidate contains no content parts."
            )
        texts = [
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        answer = "".join(texts).strip()
        if not answer:
            raise MalformedModelOutputError("Gemini returned empty text.")
        return answer

    @staticmethod
    def _content_from_text(
        answer: str, prompt: ExplanationPrompt
    ) -> ExplanationContent:
        """Envelope plain LLM text into validated, grounded content.

        Reference lists are copied *from the supplied prompt* — the
        provider can never introduce a reference the caller did not supply.
        ``observed_facts`` are attached only when the answer literally
        cites a supplied ``fact_id``, so structured claims stay honest.
        """

        paragraphs = [p.strip() for p in answer.split("\n") if p.strip()]
        summary = paragraphs[0] if paragraphs else answer

        observed: list[ObservedFact] = []
        for fact in prompt.facts:
            if fact.fact_id not in answer:
                continue
            try:
                statement = StatementType(fact.kind.value)
            except ValueError:
                continue
            observed.append(
                ObservedFact(
                    fact_ref=fact.fact_id,
                    statement_type=statement,
                    source_ref=fact.source_ref,
                )
            )

        return ExplanationContent(
            summary=summary,
            detailed_explanation=answer,
            observed_facts=observed,
            uncertainties=list(prompt.uncertainties),
            evidence_refs=list(prompt.evidence_refs),
            verification_refs=list(prompt.verification_refs),
            finding_refs=list(prompt.finding_refs),
            recommended_review_actions=[
                "Review the cited evidence and verification records "
                "before taking action."
            ],
        )

    # ------------------------------------------------------------------
    # Network seam (stdlib only; HTTPS enforced)
    # ------------------------------------------------------------------

    def _post_https(
        self, url: str, body: bytes, headers: dict[str, str], timeout: float
    ) -> tuple[str, int]:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ExplanationModelUnavailableError(
                "Gemini endpoint must use HTTPS; got scheme: "
                + str(parsed.scheme)
            )
        host = parsed.hostname or ""
        port = parsed.port or 443
        path = parsed.path or "/"
        if parsed.query:
            path = path + "?" + parsed.query

        import http.client

        context = ssl.create_default_context()
        connection = http.client.HTTPSConnection(
            host=host, port=port, timeout=timeout, context=context
        )
        try:
            connection.request(
                method="POST", url=path, body=body, headers=headers
            )
            response = connection.getresponse()
            response_body = response.read().decode("utf-8", errors="replace")
            return response_body, int(response.status)
        finally:
            connection.close()


# ---------------------------------------------------------------------------
# Convenience wiring
# ---------------------------------------------------------------------------


def explanation_model_from_env(
    env: dict[str, str] | None = None,
) -> GeminiExplanationModel | None:
    """Return a live :class:`GeminiExplanationModel` when ``GEMINI_API_KEY``
    is configured, else ``None`` (caller keeps the deterministic fallback).
    """

    return GeminiExplanationModel.from_env(env)


def explanation_engine_from_env(env: dict[str, str] | None = None):
    """Build an ``ExplanationEngine`` wired to the environment.

    With ``GEMINI_API_KEY`` set the engine uses the live Gemini model;
    without it the engine is constructed with no model and its built-in
    deterministic fallback answers. Flags are unaffected either way.
    """

    from ai_verification.explanations.engine import ExplanationEngine

    return ExplanationEngine(model=explanation_model_from_env(env))


__all__ = [
    "API_PATH_TEMPLATE",
    "DEFAULT_BASE_URL",
    "DEFAULT_GEMINI_MODEL",
    "DEFAULT_TIMEOUT_SECONDS",
    "GEMINI_API_KEY_ENV",
    "GEMINI_BASE_URL_ENV",
    "GEMINI_MODEL_ENV",
    "GEMINI_TIMEOUT_ENV",
    "GeminiExplanationModel",
    "OUTPUT_CONTRACT",
    "PROVIDER_NAME",
    "Poster",
    "explanation_engine_from_env",
    "explanation_model_from_env",
]

