"""Cross-bidder verification components."""
from .document_artifact_store import (
    DocumentArtifactStore,
    DocumentMeta,
    InMemoryDocumentArtifactStore,
)
from .embedding import (
    EmbeddingEndpointConfig,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingTransport,
    EmbeddingTransportError,
    EmbeddingValidationError,
    HttpEmbeddingAdapter,
    StaticEmbeddingProvider,
    StaticEmbeddingTransport,
    UnavailableEmbeddingProvider,
    cosine_similarity,
)
from .detector import compare_two_documents, detect_cross_bidder_anomalies
from .normalization import NORMALIZATION_VERSION, normalize_text, normalized_text_hash
from .orchestrator import CrossBidderOrchestrator
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
    "CrossBidderOrchestrator",
    "DocumentArtifactStore",
    "DocumentMeta",
    "EmbeddingEndpointConfig",
    "EmbeddingProvider",
    "EmbeddingRequest",
    "EmbeddingResponse",
    "EmbeddingTransport",
    "EmbeddingTransportError",
    "EmbeddingValidationError",
    "HttpEmbeddingAdapter",
    "InMemoryDocumentArtifactStore",
    "QualitySignals",
    "SimilarityLayer",
    "SimilarityTrace",
    "StaticEmbeddingProvider",
    "StaticEmbeddingTransport",
    "TemplateGate",
    "TemplateGateStatus",
    "UnavailableEmbeddingProvider",
    "compare_two_documents",
    "cosine_similarity",
    "detect_cross_bidder_anomalies",
    "NORMALIZATION_VERSION",
    "normalize_text",
    "normalized_text_hash",
]

