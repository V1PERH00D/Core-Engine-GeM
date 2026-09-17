"""Cross-document field classification coverage for the new capabilities."""

from ai_verification.cross_document.extraction import classify_field
from ai_verification.cross_document.models import ConsistencyDimension


def test_bis_manufacturer_is_manufacturer_dimension():
    spec = classify_field("BIS", "manufacturer")
    assert spec is not None
    assert spec.dimension is ConsistencyDimension.MANUFACTURER


def test_bis_product_description_is_product_dimension():
    spec = classify_field("BIS", "product_description")
    assert spec is not None
    assert spec.dimension is ConsistencyDimension.PRODUCT


def test_oem_manufacturer_still_mapped():
    spec = classify_field("OEM", "manufacturer")
    assert spec is not None
    assert spec.dimension is ConsistencyDimension.MANUFACTURER


def test_unrelated_field_not_classified():
    assert classify_field("BIS", "certificate_number") is None