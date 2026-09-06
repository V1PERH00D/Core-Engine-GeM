"""Tests for finding conversion."""

from __future__ import annotations

from compliance_engine.flags import get_flag_definition
from compliance_engine.models import Evidence

from ai_verification.cross_document import extraction as _extraction
from ai_verification.cross_document.aggregation import aggregate
from ai_verification.cross_document.comparison import compare_all
from ai_verification.cross_document.findings import (
    FLAG_ID_BY_DIMENSION,
    observations_for_comparison,
    strongest_mismatches,
    to_verification_findings,
)
from ai_verification.cross_document.models import ConsistencyDimension


extract_observation = _extraction.extract_observation


def _obs(doc_id, doc_type, field, value):
    return extract_observation(
        Evidence(
            evidence_id=f"{doc_id}:{field}",
            bidder_id="bidder-1",
            document_id=doc_id,
            document_type=doc_type,
            field_name=field,
            value=value,
        )
    )


def test_flag_id_per_dimension_registered() -> None:
    assert FLAG_ID_BY_DIMENSION[ConsistencyDimension.IDENTIFIER] == (
        "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
    )
    assert FLAG_ID_BY_DIMENSION[ConsistencyDimension.ADDRESS] == (
        "CROSS_DOCUMENT_ADDRESS_CONFLICT"
    )
    assert FLAG_ID_BY_DIMENSION[ConsistencyDimension.DATE] == (
        "CROSS_DOCUMENT_DATE_SEQUENCE_INVALID"
    )
    assert FLAG_ID_BY_DIMENSION[ConsistencyDimension.PRODUCT] == (
        "CROSS_DOCUMENT_PRODUCT_MISMATCH"
    )
    assert FLAG_ID_BY_DIMENSION[ConsistencyDimension.MANUFACTURER] == (
        "CROSS_DOCUMENT_MANUFACTURER_MISMATCH"
    )


def test_flag_definitions_have_required_fields() -> None:
    for flag_id in FLAG_ID_BY_DIMENSION.values():
        defn = get_flag_definition(flag_id)
        assert defn.flag_id == flag_id
        assert defn.severity
        assert defn.capability
        assert defn.title


def test_no_finding_emitted_for_match() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "27AAACI1234F1Z5")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    assert findings == []


def test_no_finding_emitted_for_insufficient_evidence() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "PAN", "pan_number", "AAACI1234F")  # incompatible
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    assert findings == []


def test_finding_emitted_for_identifier_mismatch() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    assert len(findings) == 1
    f = findings[0]
    assert f.flag_id == "CROSS_DOCUMENT_IDENTIFIER_CONFLICT"
    assert f.bidder_id == "bidder-1"
    assert f.evidence_refs == ["doc-1:gstin", "doc-2:gstin"]


def test_finding_emitted_for_address_mismatch() -> None:
    left = _obs("doc-1", "GST", "registered_address", "Pune")
    right = _obs("doc-2", "GSTN", "registered_address", "Delhi")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    assert len(findings) == 1
    assert findings[0].flag_id == "CROSS_DOCUMENT_ADDRESS_CONFLICT"


def test_finding_emitted_for_date_mismatch() -> None:
    left = _obs("doc-1", "ITR", "filing_date", "2024-07-28")
    right = _obs("doc-2", "ITR", "filing_date", "2024-09-30")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    assert len(findings) == 1
    assert findings[0].flag_id == "CROSS_DOCUMENT_DATE_SEQUENCE_INVALID"


def test_finding_explanation_contains_dimension_and_reason() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    f = findings[0]
    assert "identifier" in f.explanation.lower()
    assert "Comparability reason" in f.explanation


def test_finding_preserves_original_and_normalized_values_via_explanation() -> None:
    left = _obs("doc-1", "GST", "gstin", "27aaaci1234f1z5")
    right = _obs("doc-2", "GST", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    # The original ``27aaaci1234f1z5`` must remain visible in the
    # audit trail.
    assert "'27aaaci1234f1z5'" in findings[0].explanation


def test_finding_does_not_claim_fraud() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    text = findings[0].explanation.lower()
    for forbidden in ("fraud", "forgery", "collusion", "illegal"):
        assert forbidden not in text


def test_finding_id_is_deterministic_and_stable() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    fid = findings[0].finding_id
    assert fid.startswith("cross-document:bidder-1:IDENTIFIER:")
    assert "doc-1:gstin" in fid
    assert "doc-2:gstin" in fid


def test_finding_does_not_fabricate_ids() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    # Both evidence refs must be the originals.
    assert set(findings[0].evidence_refs) == {
        "doc-1:gstin",
        "doc-2:gstin",
    }


def test_finding_severity_copied_from_registry() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    findings = to_verification_findings(agg)
    # The identifier flag is CRITICAL.
    assert findings[0].severity.value == "CRITICAL"


def test_strongest_mismatches_one_per_dimension() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    strongest = strongest_mismatches(agg)
    assert len(strongest) == 1
    assert strongest[0].dimension is ConsistencyDimension.IDENTIFIER


def test_observations_for_comparison_returns_underlying_observations() -> None:
    left = _obs("doc-1", "GST", "gstin", "27AAACI1234F1Z5")
    right = _obs("doc-2", "GSTN", "gstin", "29AAACI1234F1Z9")
    comparisons = compare_all([left, right])
    agg = aggregate("bidder-1", [left, right], comparisons)
    comp = comparisons[0]
    lo, ro = observations_for_comparison(agg, comp)
    assert lo is not None
    assert ro is not None
    assert lo.evidence_id == "doc-1:gstin"
    assert ro.evidence_id == "doc-2:gstin"
