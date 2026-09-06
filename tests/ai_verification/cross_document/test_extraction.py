"""Tests for FieldObservation extraction and compatibility."""

from __future__ import annotations

from compliance_engine.models import Evidence

from ai_verification.cross_document import extraction as _extraction
from ai_verification.cross_document.models import (
    ConsistencyDimension,
    DateRole,
    FieldStatus,
    IdentifierKind,
)

# Re-bind the names we use to plain identifiers so the rest of
# the file reads naturally. (Python 3.14 has a bug that prevents
# ``from ai_verification.cross_document import X`` from resolving
# module-level names defined after many intervening statements;
# the workaround is to ``import as`` the package and read
# attributes off the module object.)
COMPATIBLE_DATE_FAMILIES = _extraction.COMPATIBLE_DATE_FAMILIES
DATE_DOCUMENT_FAMILY = _extraction.DATE_DOCUMENT_FAMILY
FIELD_CLASSIFICATION = _extraction.FIELD_CLASSIFICATION
ComparabilityResult = _extraction.ComparabilityResult
FieldSpec = _extraction.FieldSpec
NORMALIZATION_VERSIONS = _extraction.NORMALIZATION_VERSIONS
are_comparable = _extraction.are_comparable
classify_field = _extraction.classify_field
extract_observation = _extraction.extract_observation
extract_observations = _extraction.extract_observations
del _extraction

from tests.ai_verification.cross_document._builders import (
    gst_evidence,
    itr_evidence,
    oem_evidence,
    pan_evidence,
    udyam_evidence,
)


# -----------------------------------------------------------------------
# Classification matrix
# -----------------------------------------------------------------------


def test_classify_field_returns_spec_for_known_pairs() -> None:
    spec = classify_field("GST", "gstin")
    assert isinstance(spec, FieldSpec)
    assert spec.dimension is ConsistencyDimension.IDENTIFIER
    assert spec.identifier_kind is IdentifierKind.GSTIN


def test_classify_field_returns_none_for_unknown_pairs() -> None:
    assert classify_field("UNKNOWN", "foo") is None
    assert classify_field("GST", "foo") is None


def test_classification_matrix_contains_all_supported_kinds() -> None:
    kinds_seen: set[IdentifierKind] = set()
    for spec in FIELD_CLASSIFICATION.values():
        if spec.identifier_kind is not None:
            kinds_seen.add(spec.identifier_kind)
    assert kinds_seen == {
        IdentifierKind.GSTIN,
        IdentifierKind.PAN,
        IdentifierKind.UDYAM,
        IdentifierKind.CIN,
        IdentifierKind.UDIN,
    }


def test_normalization_versions_map_dimensions() -> None:
    from ai_verification.cross_document.normalization import (
        ADDRESS_NORMALIZATION_VERSION,
        DATE_NORMALIZATION_VERSION,
        IDENTIFIER_NORMALIZATION_VERSION,
        MANUFACTURER_NORMALIZATION_VERSION,
        PRODUCT_NORMALIZATION_VERSION,
    )

    assert NORMALIZATION_VERSIONS[ConsistencyDimension.IDENTIFIER] == (
        IDENTIFIER_NORMALIZATION_VERSION
    )
    assert NORMALIZATION_VERSIONS[ConsistencyDimension.ADDRESS] == (
        ADDRESS_NORMALIZATION_VERSION
    )
    assert NORMALIZATION_VERSIONS[ConsistencyDimension.DATE] == (
        DATE_NORMALIZATION_VERSION
    )
    assert NORMALIZATION_VERSIONS[ConsistencyDimension.PRODUCT] == (
        PRODUCT_NORMALIZATION_VERSION
    )
    assert NORMALIZATION_VERSIONS[ConsistencyDimension.MANUFACTURER] == (
        MANUFACTURER_NORMALIZATION_VERSION
    )


# -----------------------------------------------------------------------
# Observation extraction
# -----------------------------------------------------------------------


def _ev(document_id: str, document_type: str, field_name: str, value) -> Evidence:
    return Evidence(
        evidence_id=f"{document_id}:{field_name}",
        bidder_id="bidder-1",
        document_id=document_id,
        document_type=document_type,
        field_name=field_name,
        value=value,
    )


def test_extract_observation_classifies_gst_gstin() -> None:
    obs = extract_observation(_ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"))
    assert obs.dimension is ConsistencyDimension.IDENTIFIER
    assert obs.identifier_kind is IdentifierKind.GSTIN
    assert obs.status is FieldStatus.AVAILABLE
    assert obs.normalized_value == "27AAACI1234F1Z5"
    assert obs.is_comparable


def test_extract_observation_unclassified_field() -> None:
    obs = extract_observation(_ev("doc-1", "UNKNOWN", "foo", "bar"))
    assert obs.dimension is None
    assert obs.status is FieldStatus.NOT_QUERIED
    assert obs.normalized_value is None
    assert obs.is_comparable is False


def test_extract_observation_missing_value_is_missing() -> None:
    obs = extract_observation(_ev("doc-1", "GST", "gstin", None))
    assert obs.status is FieldStatus.MISSING
    assert obs.is_comparable is False


def test_extract_observation_invalid_value_is_invalid() -> None:
    obs = extract_observation(_ev("doc-1", "ITR", "filing_date", "not a date"))
    assert obs.dimension is ConsistencyDimension.DATE
    assert obs.status is FieldStatus.INVALID
    assert obs.is_comparable is False


def test_extract_observations_bidder_filter_drops_other_bidders() -> None:
    evidence = [
        Evidence(
            evidence_id="doc-1:gstin",
            bidder_id="bidder-1",
            document_id="doc-1",
            document_type="GST",
            field_name="gstin",
            value="27AAACI1234F1Z5",
        ),
        Evidence(
            evidence_id="doc-2:gstin",
            bidder_id="bidder-2",
            document_id="doc-2",
            document_type="GST",
            field_name="gstin",
            value="29AAACI1234F1Z9",
        ),
    ]
    out = extract_observations(evidence, bidder_id="bidder-1")
    assert len(out) == 1
    assert out[0].bidder_id == "bidder-1"


def test_extract_observations_default_no_filter() -> None:
    evidence = gst_evidence() + pan_evidence()
    out = extract_observations(evidence)
    assert len(out) == len(evidence)


# -----------------------------------------------------------------------
# Comparability
# -----------------------------------------------------------------------


def test_identifier_kinds_incompatible() -> None:
    left = extract_observation(_ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"))
    right = extract_observation(_ev("doc-2", "PAN", "pan_number", "AAACI1234F"))
    result = are_comparable(left, right)
    assert result.comparable is False
    assert "Incompatible identifier kinds" in result.reason


def test_same_identifier_kind_compatible() -> None:
    left = extract_observation(_ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"))
    right = extract_observation(_ev("doc-2", "GSTN", "gstin", "27AAACI1234F1Z5"))
    assert are_comparable(left, right).comparable is True


def test_address_compatible_same_field_name() -> None:
    left = extract_observation(_ev("doc-1", "GST", "registered_address", "Pune"))
    right = extract_observation(_ev("doc-2", "GSTN", "registered_address", "Pune"))
    assert are_comparable(left, right).comparable is True


def test_address_incompatible_different_field_name() -> None:
    left = extract_observation(_ev("doc-1", "GST", "registered_address", "Pune"))
    right = extract_observation(_ev("doc-2", "GST", "foo", "Pune"))
    result = are_comparable(left, right)
    assert result.comparable is False


def test_date_compatible_same_role_same_family() -> None:
    left = extract_observation(_ev("doc-1", "ITR", "filing_date", "2024-07-28"))
    right = extract_observation(_ev("doc-2", "ITR", "filing_date", "2024-07-28"))
    assert are_comparable(left, right).comparable is True


def test_date_incompatible_different_role() -> None:
    left = extract_observation(_ev("doc-1", "ITR", "filing_date", "2024-07-28"))
    right = extract_observation(_ev("doc-2", "ITR", "assessment_year", "2024-25"))
    result = are_comparable(left, right)
    assert result.comparable is False


def test_date_incompatible_unknown_roles() -> None:
    left = extract_observation(_ev("doc-1", "ITR", "assessment_year", "2024-25"))
    right = extract_observation(_ev("doc-2", "ITR", "financial_year", "2023-24"))
    result = are_comparable(left, right)
    assert result.comparable is False


def test_manufacturer_compatible() -> None:
    left = extract_observation(_ev("doc-1", "OEM", "manufacturer", "Acme"))
    right = extract_observation(_ev("doc-2", "OEM", "manufacturer", "Acme"))
    assert are_comparable(left, right).comparable is True


def test_missing_field_not_comparable() -> None:
    left = extract_observation(_ev("doc-1", "GST", "gstin", None))
    right = extract_observation(_ev("doc-2", "GST", "gstin", "27AAACI1234F1Z5"))
    result = are_comparable(left, right)
    assert result.comparable is False
    assert "Left field is unavailable" in result.reason


def test_invalid_field_not_comparable() -> None:
    left = extract_observation(_ev("doc-1", "ITR", "filing_date", "not a date"))
    right = extract_observation(_ev("doc-2", "ITR", "filing_date", "2024-07-28"))
    result = are_comparable(left, right)
    assert result.comparable is False
    assert "Left field is unavailable" in result.reason


def test_cross_dimension_not_comparable() -> None:
    left = extract_observation(_ev("doc-1", "GST", "gstin", "27AAACI1234F1Z5"))
    right = extract_observation(_ev("doc-2", "GST", "registered_address", "Pune"))
    result = are_comparable(left, right)
    assert result.comparable is False
    assert "Dimensions differ" in result.reason


def test_compatible_date_families_membership() -> None:
    assert "ITR" in COMPATIBLE_DATE_FAMILIES
    assert "GST_REGISTRATION" in COMPATIBLE_DATE_FAMILIES


def test_date_document_family_mapping() -> None:
    assert DATE_DOCUMENT_FAMILY["ITR"] == "ITR"
    assert DATE_DOCUMENT_FAMILY["GST"] == "GST_REGISTRATION"
    assert DATE_DOCUMENT_FAMILY["GSTN"] == "GST_REGISTRATION"
