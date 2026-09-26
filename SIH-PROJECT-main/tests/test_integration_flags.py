"""Cross-document flag tests F/G/H plus the Phase 6 mapping coverage tests.

All flags are produced by the real Core ``CrossDocumentConsistencyEngine``
running under the real ``VerificationEngine``; only inputs are fixtures.
"""

from __future__ import annotations

from app.integration.field_mapping import (
    DOC_TYPE_MAP,
    map_document_type,
    map_field_name,
)
from tests.helpers import doc, flags_of, run_fixture


# TEST F — product mismatch -> CROSS_DOCUMENT_PRODUCT_MISMATCH
def test_f_product_mismatch_flagged():
    fixture = {
        "bidder_id": "b-product",
        "documents": [
            doc(
                "MII_A",
                "make_in_india_local_content",
                supplier_class="Class-I Local Supplier",
            ),
            doc(
                "MII_B",
                "make_in_india_local_content",
                supplier_class="Non-Local Supplier",
            ),
        ],
    }
    result, _ = run_fixture(fixture)
    assert "CROSS_DOCUMENT_PRODUCT_MISMATCH" in flags_of(result)


# TEST G — manufacturer mismatch -> CROSS_DOCUMENT_MANUFACTURER_MISMATCH
def test_g_manufacturer_mismatch_flagged():
    fixture = {
        "bidder_id": "b-manufacturer",
        "documents": [
            doc("OEM_A", "oem_authorization", manufacturer="Acme Industries"),
            doc("OEM_B", "oem_authorization", manufacturer="Beta Machines"),
        ],
    }
    result, _ = run_fixture(fixture)
    assert "CROSS_DOCUMENT_MANUFACTURER_MISMATCH" in flags_of(result)


# TEST H — invalid date sequence with explicit evaluation date
def test_h_date_sequence_invalid_flagged():
    fixture = {
        "bidder_id": "b-dates",
        "evaluation_date_iso": "2025-01-15",
        "documents": [
            doc("ITR_A", "itr_acknowledgment", filing_date="2023-07-31"),
            doc("ITR_B", "itr_acknowledgment", filing_date="2022-07-31"),
        ],
    }
    result, _ = run_fixture(fixture)
    assert "CROSS_DOCUMENT_DATE_SEQUENCE_INVALID" in flags_of(result)


# Phase 6 — mapping coverage assertions (documentation-as-test)
def test_field_mapping_renames_are_explicit():
    assert map_field_name("pan") == "pan_number"
    assert map_field_name("udyam") == "udyam_registration_number"
    assert map_field_name("udin") == "ca_udin"
    assert map_field_name("taxpayer_name") == "name_on_pan"
    assert (
        map_field_name("declared_local_content_pct")
        == "local_content_percentage"
    )
    # Identity pass-through for names Core already understands.
    assert map_field_name("gstin") == "gstin"
    assert map_field_name("registered_address") == "registered_address"
    assert map_field_name("filing_date") == "filing_date"
    assert map_field_name("supplier_class") == "supplier_class"


def test_document_type_mapping_covers_all_module1_classifications():
    expected_labels = {
        "gst_certificate": "GST",
        "pan_card": "PAN",
        "udyam_certificate": "UDYAM",
        "itr_acknowledgment": "ITR",
        "financial_statement": "BS",
        "make_in_india_local_content": "MAKE_IN_INDIA",
        "oem_authorization": "OEM_AUTHORIZATION",
    }
    for label, core_type in expected_labels.items():
        assert map_document_type(label) == core_type
    # Every Module 1 classifier label has a defined Core document type.
    from app.services.classification import DOCUMENT_SIGNATURES

    assert set(DOCUMENT_SIGNATURES) <= set(DOC_TYPE_MAP)
    assert map_document_type(None) == "UNKNOWN"
    assert map_document_type("something_new") == "UNKNOWN"
