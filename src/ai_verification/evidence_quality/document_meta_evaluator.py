"""Default evidence-quality evaluator built on
:class:`ai_verification.cross_bidder.document_artifact_store.DocumentMeta`.

This module is the *default* implementation the cross-bidder
detector uses when no other evaluator is injected. It produces a
:class:`DocumentQualitySignals` bundle from:

* The two confidence fields already present in
  :class:`DocumentMeta`: ``ocr_confidence`` and
  ``document_type_confidence``.
* The presence of raw text and metadata in the artifact store.

It does *not* call any LLM, network service, or external API.

Future production extraction systems can supply richer
:class:`FieldQualitySignals` (e.g. per-field confidences) by
injecting a custom evaluator. This default is intentionally the
minimum viable input the engine can score without false positives.
"""

from __future__ import annotations

from typing import Iterable

from ai_verification.cross_bidder.document_artifact_store import (
    DocumentArtifactStore,
    DocumentMeta,
)

from .assessment import EvidenceQualityAssessment
from .evaluator import evaluate_signals
from .signals import (
    CompletenessSignals,
    DocumentQualitySignals,
    FieldQualitySignals,
    MetadataReliabilitySignals,
    OCRQualitySignals,
)


#: Fields the cross-bidder detector requires a document to have in
#: its :class:`DocumentMeta` in order to make a confident comparison.
#: Missing any of them is captured by
#: :attr:`QualityReason.REQUIRED_FIELD_MISSING`.
DEFAULT_REQUIRED_METADATA_FIELDS: tuple[str, ...] = (
    "issuer",
    "authorization_number",
    "issue_date",
    "territory",
)


def _present_metadata_fields(meta: DocumentMeta) -> list[str]:
    """Return the names of the populated metadata fields on ``meta``."""
    return [
        name
        for name in DEFAULT_REQUIRED_METADATA_FIELDS
        if getattr(meta, name, None) is not None
    ]


def build_signals_for_document(
    document_id: str,
    meta: DocumentMeta | None,
    artifact_store: DocumentArtifactStore | None,
    *,
    required_metadata_fields: Iterable[str] = DEFAULT_REQUIRED_METADATA_FIELDS,
) -> DocumentQualitySignals:
    """Build a :class:`DocumentQualitySignals` bundle from a document.

    Used by the default evaluator and exposed so tests can verify
    the signal-construction logic in isolation.

    The bundle is conservative:

    * If ``meta`` is ``None`` or ``artifact_store`` is ``None``,
      all presence booleans are ``False`` and the only signal is
      "unknown".
    * If ``meta`` is present but its fields are ``None``, those
      fields contribute to ``required_fields_missing``.
    * The OCR and field confidences are taken straight from
      :class:`DocumentMeta`; if the meta is ``None`` they are
      ``None``.
    """
    required = list(required_metadata_fields)
    ocr_conf = (
        getattr(meta, "ocr_confidence", None) if meta is not None else None
    )
    dtc = (
        getattr(meta, "document_type_confidence", None)
        if meta is not None
        else None
    )

    raw_text_present = False
    metadata_present = meta is not None
    present_fields: list[str] = []
    if meta is not None:
        present_fields = [
            name for name in required if getattr(meta, name, None) is not None
        ]
    if artifact_store is not None:
        try:
            raw = artifact_store.get_raw_text(document_id)
        except Exception:
            raw = None
        raw_text_present = bool(raw)
    missing_fields = [name for name in required if name not in present_fields]

    return DocumentQualitySignals(
        ocr=OCRQualitySignals(
            ocr_confidence=ocr_conf,
            ocr_text_present=raw_text_present,
        ),
        fields=FieldQualitySignals(
            field_confidence=None,
            required_fields_missing=missing_fields,
        ),
        metadata=MetadataReliabilitySignals(
            document_type_confidence=dtc,
            metadata_present=metadata_present,
        ),
        completeness=CompletenessSignals(
            required_fields=required,
            required_fields_present=present_fields,
            required_fields_missing=missing_fields,
            raw_text_present=raw_text_present,
            metadata_present=metadata_present,
        ),
    )


class DocumentMetaQualityEvaluator:
    """Default evaluator that reads signals from :class:`DocumentMeta`.

    The detector instantiates this with the artifact store and
    then calls :meth:`evaluate_for_document` for each side of a
    pair. The evaluator itself has no state beyond the artifact
    store reference; it is safe to share between threads.
    """

    def __init__(
        self,
        artifact_store: DocumentArtifactStore | None = None,
        *,
        required_metadata_fields: Iterable[str] = DEFAULT_REQUIRED_METADATA_FIELDS,
    ) -> None:
        self._artifact_store = artifact_store
        self._required = tuple(required_metadata_fields)

    def evaluate(
        self, signals: DocumentQualitySignals
    ) -> EvidenceQualityAssessment:
        """Evaluate an already-constructed signals bundle."""
        return evaluate_signals(signals)

    def evaluate_for_document(
        self,
        document_id: str,
        meta: DocumentMeta | None,
    ) -> EvidenceQualityAssessment:
        """Build signals from a document and evaluate them.

        This is the primary entry point used by the cross-bidder
        detector.
        """
        signals = build_signals_for_document(
            document_id,
            meta,
            self._artifact_store,
            required_metadata_fields=self._required,
        )
        return evaluate_signals(signals)


#: A module-level singleton for code paths that don't need to
#: inject a custom evaluator. It is a no-artifact-store
#: evaluator: callers that need raw-text awareness must build
#: their own instance with an :class:`DocumentArtifactStore`.
_DEFAULT_EVALUATOR_NO_STORE = DocumentMetaQualityEvaluator()


def default_evaluator(
    artifact_store: DocumentArtifactStore | None = None,
) -> DocumentMetaQualityEvaluator:
    """Return a default evaluator instance.

    Tests and production callers should pass an explicit
    :class:`DocumentArtifactStore` so raw-text presence is
    observable.
    """
    if artifact_store is None:
        return _DEFAULT_EVALUATOR_NO_STORE
    return DocumentMetaQualityEvaluator(artifact_store=artifact_store)


__all__ = [
    "DEFAULT_REQUIRED_METADATA_FIELDS",
    "DocumentMetaQualityEvaluator",
    "build_signals_for_document",
    "default_evaluator",
]

