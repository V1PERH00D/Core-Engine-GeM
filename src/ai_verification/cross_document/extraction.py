"""Extract FieldObservation objects from upstream Evidence."""

from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional

from compliance_engine.models import Evidence

from ai_verification.evidence_quality import (
    EvidenceQualityAssessment,
    QualityReason,
    QualityState,
)

from ai_verification.cross_document.models import (
    ConsistencyDimension,
    DateRole,
    FieldObservation,
    FieldStatus,
    IdentifierKind,
)
from ai_verification.cross_document.normalization import (
    normalize_address,
    normalize_date,
    normalize_identifier,
    normalize_manufacturer,
    normalize_product,
)


@dataclass(frozen=True)
class FieldSpec:
    dimension: ConsistencyDimension
    identifier_kind: IdentifierKind | None = None
    date_role: DateRole | None = None


FIELD_CLASSIFICATION: dict[tuple[str, str], FieldSpec] = {
    ("GST", "gstin"): FieldSpec(
        ConsistencyDimension.IDENTIFIER, identifier_kind=IdentifierKind.GSTIN
    ),
    ("GSTN", "gstin"): FieldSpec(
        ConsistencyDimension.IDENTIFIER, identifier_kind=IdentifierKind.GSTIN
    ),
    ("PAN", "pan_number"): FieldSpec(
        ConsistencyDimension.IDENTIFIER, identifier_kind=IdentifierKind.PAN
    ),
    ("PAN_INCOME_TAX", "pan_number"): FieldSpec(
        ConsistencyDimension.IDENTIFIER, identifier_kind=IdentifierKind.PAN
    ),
    ("UDYAM", "udyam_registration_number"): FieldSpec(
        ConsistencyDimension.IDENTIFIER, identifier_kind=IdentifierKind.UDYAM
    ),
    ("MCA", "cin"): FieldSpec(
        ConsistencyDimension.IDENTIFIER, identifier_kind=IdentifierKind.CIN
    ),
    ("MCA21", "cin"): FieldSpec(
        ConsistencyDimension.IDENTIFIER, identifier_kind=IdentifierKind.CIN
    ),
    ("BS", "ca_udin"): FieldSpec(
        ConsistencyDimension.IDENTIFIER, identifier_kind=IdentifierKind.UDIN
    ),
    ("GST", "registered_address"): FieldSpec(ConsistencyDimension.ADDRESS),
    ("GSTN", "registered_address"): FieldSpec(ConsistencyDimension.ADDRESS),
    ("PAN", "registered_address"): FieldSpec(ConsistencyDimension.ADDRESS),
    ("UDYAM", "registered_address"): FieldSpec(ConsistencyDimension.ADDRESS),
    ("MCA21", "registered_address"): FieldSpec(ConsistencyDimension.ADDRESS),
    ("ITR", "filing_date"): FieldSpec(
        ConsistencyDimension.DATE, date_role=DateRole.FILING_DATE
    ),
    ("ITR", "assessment_year"): FieldSpec(
        ConsistencyDimension.DATE, date_role=DateRole.UNKNOWN
    ),
    ("ITR", "financial_year"): FieldSpec(
        ConsistencyDimension.DATE, date_role=DateRole.UNKNOWN
    ),
    ("OEM", "manufacturer"): FieldSpec(ConsistencyDimension.MANUFACTURER),
    ("OEM_AUTHORIZATION", "manufacturer"): FieldSpec(
        ConsistencyDimension.MANUFACTURER
    ),
    ("BIS", "manufacturer"): FieldSpec(ConsistencyDimension.MANUFACTURER),
    ("BIS_CERTIFICATION", "manufacturer"): FieldSpec(ConsistencyDimension.MANUFACTURER),
    ("BIS", "product_description"): FieldSpec(ConsistencyDimension.PRODUCT),
    ("BIS_CERTIFICATION", "product_description"): FieldSpec(ConsistencyDimension.PRODUCT),
    ("MAKE_IN_INDIA", "supplier_class"): FieldSpec(ConsistencyDimension.PRODUCT),
    ("PRODUCT", "product_description"): FieldSpec(ConsistencyDimension.PRODUCT),
}


_DATE_COMPATIBLE_FAMILIES: dict[str, frozenset[str]] = {
    "ITR": frozenset({"ITR"}),
    "GST_REGISTRATION": frozenset({"GST", "GSTN"}),
    "PAN_REGISTRATION": frozenset({"PAN", "PAN_INCOME_TAX"}),
    "UDYAM_REGISTRATION": frozenset({"UDYAM"}),
    "MCA_REGISTRATION": frozenset({"MCA", "MCA21"}),
    "OEM_AUTHORIZATION": frozenset({"OEM", "OEM_AUTHORIZATION"}),
}


_DATE_DOCUMENT_FAMILY: dict[str, str] = {
    "ITR": "ITR",
    "GST": "GST_REGISTRATION",
    "GSTN": "GST_REGISTRATION",
    "PAN": "PAN_REGISTRATION",
    "PAN_INCOME_TAX": "PAN_REGISTRATION",
    "UDYAM": "UDYAM_REGISTRATION",
    "MCA": "MCA_REGISTRATION",
    "MCA21": "MCA_REGISTRATION",
    "OEM": "OEM_AUTHORIZATION",
    "OEM_AUTHORIZATION": "OEM_AUTHORIZATION",
}


def _date_family_for(document_type: str) -> Optional[str]:
    return _DATE_DOCUMENT_FAMILY.get(document_type)


def classify_field(
    document_type: str, field_name: str
) -> Optional[FieldSpec]:
    return FIELD_CLASSIFICATION.get((document_type, field_name))


QualityLookup = Callable[[str, str], Optional[EvidenceQualityAssessment]]


def _noop_quality_lookup(
    document_id: str, field_name: str
) -> Optional[EvidenceQualityAssessment]:
    return None


def _status_for(
    spec: FieldSpec | None,
    raw_value: object,
    normalized: Optional[str],
) -> FieldStatus:
    if raw_value is None:
        return FieldStatus.MISSING
    if spec is None:
        return FieldStatus.NOT_QUERIED
    if normalized is None:
        return FieldStatus.INVALID
    return FieldStatus.AVAILABLE


def _normalize_for_spec(
    spec: FieldSpec, value: object
) -> Optional[str]:
    if spec.dimension is ConsistencyDimension.IDENTIFIER:
        return normalize_identifier(value)
    if spec.dimension is ConsistencyDimension.ADDRESS:
        return normalize_address(value)
    if spec.dimension is ConsistencyDimension.DATE:
        return normalize_date(value)
    if spec.dimension is ConsistencyDimension.PRODUCT:
        return normalize_product(value)
    if spec.dimension is ConsistencyDimension.MANUFACTURER:
        return normalize_manufacturer(value)
    return None


def extract_observation(
    evidence: Evidence,
    *,
    quality_lookup: Optional[QualityLookup] = None,
) -> FieldObservation:
    lookup = quality_lookup or _noop_quality_lookup
    spec = classify_field(evidence.document_type, evidence.field_name)
    if spec is None:
        return FieldObservation(
            bidder_id=evidence.bidder_id,
            document_id=evidence.document_id,
            document_type=evidence.document_type,
            field_name=evidence.field_name,
            evidence_id=evidence.evidence_id,
            original_value=evidence.value,
            normalized_value=None,
            dimension=None,
            status=FieldStatus.NOT_QUERIED,
            evidence_confidence=evidence.confidence,
            is_comparable=False,
        )

    normalized = _normalize_for_spec(spec, evidence.value)
    status = _status_for(spec, evidence.value, normalized)
    quality = lookup(evidence.document_id, evidence.field_name)

    return FieldObservation(
        bidder_id=evidence.bidder_id,
        document_id=evidence.document_id,
        document_type=evidence.document_type,
        field_name=evidence.field_name,
        evidence_id=evidence.evidence_id,
        original_value=evidence.value,
        normalized_value=normalized,
        dimension=spec.dimension,
        identifier_kind=spec.identifier_kind,
        date_role=spec.date_role,
        status=status,
        evidence_confidence=evidence.confidence,
        quality_state=quality.state if quality else None,
        quality_score=quality.quality_score if quality else None,
        quality_reasons=tuple(quality.reasons) if quality else (),
        is_comparable=(status is FieldStatus.AVAILABLE),
    )


def extract_observations(
    evidence: Iterable[Evidence],
    *,
    bidder_id: Optional[str] = None,
    quality_lookup: Optional[QualityLookup] = None,
) -> List[FieldObservation]:
    observations: List[FieldObservation] = []
    for record in evidence:
        if bidder_id is not None and record.bidder_id != bidder_id:
            continue
        observations.append(
            extract_observation(record, quality_lookup=quality_lookup)
        )
    return observations


def _identifier_pair_compatible(
    left: FieldObservation, right: FieldObservation
) -> bool:
    if left.identifier_kind is None or right.identifier_kind is None:
        return False
    if left.identifier_kind is not right.identifier_kind:
        return False
    if left.field_name != right.field_name:
        return False
    return True


def _date_pair_compatible(
    left: FieldObservation, right: FieldObservation
) -> bool:
    if left.date_role is None or right.date_role is None:
        return False
    if left.date_role is DateRole.UNKNOWN and right.date_role is DateRole.UNKNOWN:
        return False
    if left.date_role is not right.date_role:
        return False
    left_family = _date_family_for(left.document_type)
    right_family = _date_family_for(right.document_type)
    if left_family is None or right_family is None:
        return False
    compatible = _DATE_COMPATIBLE_FAMILIES.get(left_family, frozenset())
    return right.document_type in compatible


def _simple_pair_compatible(
    left: FieldObservation, right: FieldObservation
) -> bool:
    return left.field_name == right.field_name


@dataclass(frozen=True)
class ComparabilityResult:
    comparable: bool
    reason: str


def are_comparable(
    left: FieldObservation, right: FieldObservation
) -> ComparabilityResult:
    if left.dimension is None or right.dimension is None:
        return ComparabilityResult(
            False,
            "Field is not classifiable into a supported dimension.",
        )
    if left.dimension is not right.dimension:
        return ComparabilityResult(
            False,
            (
                f"Dimensions differ: {left.dimension.value} vs "
                f"{right.dimension.value}; cross-dimension pairs are "
                f"never compared."
            ),
        )
    if left.status is not FieldStatus.AVAILABLE:
        return ComparabilityResult(
            False,
            f"Left field is unavailable (status={left.status.value}).",
        )
    if right.status is not FieldStatus.AVAILABLE:
        return ComparabilityResult(
            False,
            f"Right field is unavailable (status={right.status.value}).",
        )
    if left.dimension is ConsistencyDimension.IDENTIFIER:
        ok = _identifier_pair_compatible(left, right)
        if not ok:
            if (
                left.identifier_kind is not None
                and right.identifier_kind is not None
                and left.identifier_kind is not right.identifier_kind
            ):
                return ComparabilityResult(
                    False,
                    (
                        f"Incompatible identifier kinds: "
                        f"{left.identifier_kind.value} vs "
                        f"{right.identifier_kind.value}; "
                        f"identifier comparison is restricted to the "
                        f"same kind and field name."
                    ),
                )
            return ComparabilityResult(
                False,
                "Identifier field names differ; comparison requires the same field name.",
            )
        return ComparabilityResult(
            True,
            (
                f"Same identifier kind ({left.identifier_kind.value}) and "
                f"same field name ({left.field_name!r})."
            ),
        )
    if left.dimension is ConsistencyDimension.DATE:
        ok = _date_pair_compatible(left, right)
        if not ok:
            return ComparabilityResult(
                False,
                (
                    "Date fields are not comparable: roles must match "
                    "and document families must overlap."
                ),
            )
        return ComparabilityResult(
            True,
            (
                f"Same date role ({left.date_role.value}) and compatible "
                f"document families "
                f"({left.document_type} <-> {right.document_type})."
            ),
        )
    if left.dimension is ConsistencyDimension.ADDRESS:
        if not _simple_pair_compatible(left, right):
            return ComparabilityResult(
                False,
                "Address field names differ; comparison requires the same field name.",
            )
        return ComparabilityResult(
            True,
            f"Address fields share the field name {left.field_name!r}.",
        )
    if left.dimension is ConsistencyDimension.PRODUCT:
        if not _simple_pair_compatible(left, right):
            return ComparabilityResult(
                False,
                "Product field names differ; comparison requires the same field name.",
            )
        return ComparabilityResult(
            True,
            f"Product fields share the field name {left.field_name!r}.",
        )
    if left.dimension is ConsistencyDimension.MANUFACTURER:
        if not _simple_pair_compatible(left, right):
            return ComparabilityResult(
                False,
                "Manufacturer field names differ; comparison requires the same field name.",
            )
        return ComparabilityResult(
            True,
            f"Manufacturer fields share the field name {left.field_name!r}.",
        )
    return ComparabilityResult(False, "Unsupported dimension.")


# Public re-export of the internal compatibility matrices.
COMPATIBLE_DATE_FAMILIES = _DATE_COMPATIBLE_FAMILIES
DATE_DOCUMENT_FAMILY = _DATE_DOCUMENT_FAMILY


def _normalization_versions() -> dict:
    from ai_verification.cross_document.normalization import (
        ADDRESS_NORMALIZATION_VERSION,
        DATE_NORMALIZATION_VERSION,
        IDENTIFIER_NORMALIZATION_VERSION,
        MANUFACTURER_NORMALIZATION_VERSION,
        PRODUCT_NORMALIZATION_VERSION,
    )
    return {
        ConsistencyDimension.IDENTIFIER: IDENTIFIER_NORMALIZATION_VERSION,
        ConsistencyDimension.ADDRESS: ADDRESS_NORMALIZATION_VERSION,
        ConsistencyDimension.DATE: DATE_NORMALIZATION_VERSION,
        ConsistencyDimension.PRODUCT: PRODUCT_NORMALIZATION_VERSION,
        ConsistencyDimension.MANUFACTURER: MANUFACTURER_NORMALIZATION_VERSION,
    }


NORMALIZATION_VERSIONS = _normalization_versions()


__all__ = [
    "COMPATIBLE_DATE_FAMILIES",
    "ComparabilityResult",
    "DATE_DOCUMENT_FAMILY",
    "FIELD_CLASSIFICATION",
    "FieldSpec",
    "NORMALIZATION_VERSIONS",
    "QualityLookup",
    "are_comparable",
    "classify_field",
    "extract_observation",
    "extract_observations",
]
