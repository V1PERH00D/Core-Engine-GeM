"""Cross-bidder verification components."""
from .document_artifact_store import (
    DocumentArtifactStore,
    DocumentMeta,
    InMemoryDocumentArtifactStore,
)
from .detector import compare_two_documents, detect_cross_bidder_anomalies
from .normalization import NORMALIZATION_VERSION, normalize_text, normalized_text_hash
from .trace import (
    CorroborationSignals,
    QualitySignals,
    SimilarityLayer,
    SimilarityTrace,
    TemplateGate,
    TemplateGateStatus,
)

__all__ = [
    "CorroborationSignals",
    "DocumentArtifactStore",
    "DocumentMeta",
    "InMemoryDocumentArtifactStore",
    "QualitySignals",
    "SimilarityLayer",
    "SimilarityTrace",
    "TemplateGate",
    "TemplateGateStatus",
    "compare_two_documents",
    "detect_cross_bidder_anomalies",
    "NORMALIZATION_VERSION",
    "normalize_text",
    "normalized_text_hash",
]
