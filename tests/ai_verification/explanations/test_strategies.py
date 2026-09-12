"""Tests for the explanation strategy registry."""

from compliance_engine.flags import get_flag_definition

from ai_verification.explanations.strategies import StrategyRegistry, default_registry


def _select(flag_id):
    return default_registry.select(get_flag_definition(flag_id))


def test_financial_threshold_strategy():
    assert _select("TURNOVER_BELOW_THRESHOLD").name == "financial_threshold"


def test_financial_inconsistency_strategy():
    assert _select("FINANCIAL_DATA_INCONSISTENCY").name == "financial_inconsistency"
    assert _select("TAX_DATA_MISMATCH").name == "financial_inconsistency"


def test_identity_mismatch_strategy():
    assert _select("CROSS_SOURCE_IDENTITY_MISMATCH").name == "identity_mismatch"
    assert _select("GST_IDENTITY_MISMATCH").name == "identity_mismatch"


def test_cross_document_mismatch_strategy():
    assert _select("CROSS_DOCUMENT_IDENTIFIER_CONFLICT").name == "cross_document_mismatch"


def test_cross_bidder_reuse_strategy():
    assert _select("CROSS_BIDDER_DOCUMENT_REUSED").name == "cross_bidder_reuse"


def test_semantic_near_duplicate_strategy():
    assert _select("CROSS_BIDDER_DOCUMENT_NEAR_DUPLICATE").name == "semantic_near_duplicate"


def test_evidence_quality_strategy():
    assert _select("OCR_CONFIDENCE_BELOW_THRESHOLD").name == "evidence_quality"


def test_debarment_strategy():
    assert _select("BIDDER_DEBARRED").name == "debarment"
    assert _select("BIDDER_BLACKLISTED").name == "debarment"


def test_missing_evidence_strategy():
    assert _select("REQUIRED_EVIDENCE_MISSING").name == "missing_evidence"
    assert _select("GSTIN_MISSING").name == "missing_evidence"


def test_unavailable_verification_strategy():
    assert _select("VERIFICATION_PROVIDER_UNAVAILABLE").name == "unavailable_verification"
    assert _select("GST_VERIFICATION_UNAVAILABLE").name == "unavailable_verification"


def test_return_filing_strategy():
    assert _select("GST_RETURN_COMPLIANCE_ISSUE").name == "return_filing"
    assert _select("ITR_NOT_FILED").name == "return_filing"


def test_compliance_failure_strategy():
    assert _select("BID_LEVEL_NON_COMPLIANT").name == "compliance_failure"


def test_compliance_pass_strategy():
    assert _select("BID_LEVEL_COMPLIANT").name == "compliance_pass"


def test_unknown_flag_lands_on_generic():
    # A flag without a dedicated strategy still resolves (never None).
    strategy = _select("ADDRESS_MISMATCH")
    assert strategy is not None


def test_registry_is_inspectable():
    registry = StrategyRegistry()
    names = [s.name for s in registry.strategies()]
    assert "generic" in names
    assert "debarment" in names


def test_registry_is_extensible():
    class Custom:
        name = "custom"

        def applies(self, flag_id, capability):
            return flag_id == "ADDRESS_MISMATCH"

        def review_actions(self, *, flag_state, facts):
            return ["custom action"]

        def uncertainty_note(self, *, flag_state):
            return None

    registry = StrategyRegistry()
    registry.register(Custom())
    assert registry.select(get_flag_definition("ADDRESS_MISMATCH")).name == "custom"


def test_review_actions_do_not_auto_disqualify():
    actions = _select("BIDDER_DEBARRED").review_actions(flag_state=True, facts=[])
    assert all("disqualif" not in a.lower() for a in actions)