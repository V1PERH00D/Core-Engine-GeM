"""Cross-document consistency engine."""

from .models import (
    AddressComparisonOutcome,
    ConsistencyDimension,
    CrossDocumentAggregation,
    DateComparisonOutcome,
    DateRole,
    DimensionSummary,
    FieldObservation,
    FieldStatus,
    IdentifierComparisonOutcome,
    IdentifierKind,
    ManufacturerComparisonOutcome,
    PairwiseComparison,
    ProductComparisonOutcome,
    outcome_for_dimension,
)
from .normalization import (
    ADDRESS_NORMALIZATION_RULES,
    ADDRESS_NORMALIZATION_VERSION,
    DATE_NORMALIZATION_RULES,
    DATE_NORMALIZATION_VERSION,
    IDENTIFIER_NORMALIZATION_RULES,
    IDENTIFIER_NORMALIZATION_VERSION,
    MANUFACTURER_NORMALIZATION_RULES,
    MANUFACTURER_NORMALIZATION_VERSION,
    PRODUCT_NORMALIZATION_RULES,
    PRODUCT_NORMALIZATION_VERSION,
    normalize_address,
    normalize_date,
    normalize_identifier,
    normalize_manufacturer,
    normalize_product,
    parse_iso_date,
)

# Import the extraction module via the fully-qualified package
# path and read its public names off the module. Python 3.14 has
# a bug that prevents ``from .extraction import name`` from
# resolving module-level names defined after many intervening
# statements when called from the partially-loaded __init__.py
# of the same package; the workaround is to read the names off
# the module object directly.
import ai_verification.cross_document.extraction as _extraction
COMPARABLE_DATE_FAMILIES = _extraction.COMPATIBLE_DATE_FAMILIES
DATE_DOCUMENT_FAMILY = _extraction.DATE_DOCUMENT_FAMILY
FIELD_CLASSIFICATION = _extraction.FIELD_CLASSIFICATION
ComparabilityResult = _extraction.ComparabilityResult
FieldSpec = _extraction.FieldSpec
NORMALIZATION_VERSIONS = _extraction.NORMALIZATION_VERSIONS
QualityLookup = _extraction.QualityLookup
are_comparable = _extraction.are_comparable
classify_field = _extraction.classify_field
extract_observation = _extraction.extract_observation
extract_observations = _extraction.extract_observations
del _extraction

from .aggregation import aggregate
from .comparison import compare_all, compare_pair, enumerate_pairs
from .findings import (
    FLAG_ID_BY_DIMENSION,
    observations_for_comparison,
    strongest_mismatches,
    to_verification_findings,
)
from .engine import (
    CrossDocumentConsistencyEngine,
    CrossDocumentConsistencyResult,
)


__all__ = [
    "ADDRESS_NORMALIZATION_RULES",
    "ADDRESS_NORMALIZATION_VERSION",
    "AddressComparisonOutcome",
    "COMPARIBLE_DATE_FAMILIES",
    "ComparabilityResult",
    "ConsistencyDimension",
    "CrossDocumentAggregation",
    "CrossDocumentConsistencyEngine",
    "CrossDocumentConsistencyResult",
    "DATE_DOCUMENT_FAMILY",
    "DATE_NORMALIZATION_RULES",
    "DATE_NORMALIZATION_VERSION",
    "DateComparisonOutcome",
    "DateRole",
    "DimensionSummary",
    "FIELD_CLASSIFICATION",
    "FLAG_ID_BY_DIMENSION",
    "FieldObservation",
    "FieldSpec",
    "FieldStatus",
    "IDENTIFIER_NORMALIZATION_RULES",
    "IDENTIFIER_NORMALIZATION_VERSION",
    "IdentifierComparisonOutcome",
    "IdentifierKind",
    "MANUFACTURER_NORMALIZATION_RULES",
    "MANUFACTURER_NORMALIZATION_VERSION",
    "ManufacturerComparisonOutcome",
    "NORMALIZATION_VERSIONS",
    "PairwiseComparison",
    "ProductComparisonOutcome",
    "QualityLookup",
    "aggregate",
    "are_comparable",
    "classify_field",
    "compare_all",
    "compare_pair",
    "enumerate_pairs",
    "extract_observation",
    "extract_observations",
    "normalize_address",
    "normalize_date",
    "normalize_identifier",
    "normalize_manufacturer",
    "normalize_product",
    "observations_for_comparison",
    "outcome_for_dimension",
    "parse_iso_date",
    "strongest_mismatches",
    "to_verification_findings",
]
