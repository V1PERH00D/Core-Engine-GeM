"""Tests for grounding + claim validation and hallucination defence."""

from ai_verification.explanations.content import (
    ExplanationContent,
    ObservedFact,
    StatementType,
)
from ai_verification.explanations.facts import FactKind, StructuredFact
from ai_verification.explanations.grounding import ExplanationGrounding
from ai_verification.explanations.models import ValidationStatus
from ai_verification.explanations.validation import (
    GroundingValidator,
    ValidationIssueCode,
)


def _facts():
    return [
        StructuredFact(
            fact_id="fact_threshold",
            kind=FactKind.THRESHOLD,
            value=25.0,
            unit="crore",
            source_ref="e1",
        ),
        StructuredFact(
            fact_id="fact_actual",
            kind=FactKind.ACTUAL_VALUE,
            value=18.4,
            unit="crore",
            source_ref="e2",
        ),
        StructuredFact(fact_id="fact_year", kind=FactKind.FINANCIAL_YEAR, value="2023-24"),
    ]


def _grounding():
    return ExplanationGrounding(evidence_refs=("e1", "e2"))


def _validator():
    return GroundingValidator()


def test_valid_content_passes():
    content = ExplanationContent(
        summary="Threshold flag is true.",
        detailed_explanation="The threshold is 25.0 crore and actual is 18.4 crore.",
        observed_facts=[
            ObservedFact(
                fact_ref="fact_threshold",
                statement_type=StatementType.THRESHOLD,
                source_ref="e1",
            ),
            ObservedFact(
                fact_ref="fact_actual",
                statement_type=StatementType.ACTUAL_VALUE,
                source_ref="e2",
            ),
        ],
        evidence_refs=["e1", "e2"],
    )
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=_facts(), flag_state=True
    )
    assert report.is_valid is True
    assert report.status is ValidationStatus.VALID


def test_unknown_evidence_ref_grounding_failed():
    content = ExplanationContent(summary="s", detailed_explanation="d", evidence_refs=["e_missing"])
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[], flag_state=True
    )
    assert report.status is ValidationStatus.GROUNDING_FAILED
    assert ValidationIssueCode.UNKNOWN_EVIDENCE_REF in {i.code for i in report.issues}


def test_unknown_verification_ref():
    content = ExplanationContent(summary="s", detailed_explanation="d", verification_refs=["v_missing"])
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[], flag_state=True
    )
    assert ValidationIssueCode.UNKNOWN_VERIFICATION_REF in {i.code for i in report.issues}


def test_unknown_finding_ref():
    content = ExplanationContent(summary="s", detailed_explanation="d", finding_refs=["f_missing"])
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[], flag_state=True
    )
    assert ValidationIssueCode.UNKNOWN_FINDING_REF in {i.code for i in report.issues}


def test_unknown_fact_ref_claim_failed():
    content = ExplanationContent(
        summary="s",
        detailed_explanation="d",
        observed_facts=[ObservedFact(fact_ref="nope", statement_type=StatementType.ACTUAL_VALUE)],
    )
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=_facts(), flag_state=True
    )
    assert report.status is ValidationStatus.CLAIM_FAILED
    assert ValidationIssueCode.UNKNOWN_FACT_REF in {i.code for i in report.issues}


def test_statement_kind_mismatch_rejected():
    content = ExplanationContent(
        summary="s",
        detailed_explanation="d",
        observed_facts=[ObservedFact(fact_ref="fact_threshold", statement_type=StatementType.DATE)],
    )
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=_facts(), flag_state=True
    )
    assert ValidationIssueCode.STATEMENT_KIND_MISMATCH in {i.code for i in report.issues}


def test_invented_number_rejected():
    content = ExplanationContent(summary="s", detailed_explanation="The value is 999.9 crore.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=_facts(), flag_state=True
    )
    assert ValidationIssueCode.UNSUPPORTED_NUMBER in {i.code for i in report.issues}


def test_supported_number_passes():
    content = ExplanationContent(summary="s", detailed_explanation="The value is 18.4 crore and 25.0 crore.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=_facts(), flag_state=True
    )
    assert ValidationIssueCode.UNSUPPORTED_NUMBER not in {i.code for i in report.issues}


def test_invented_financial_year_rejected():
    content = ExplanationContent(summary="s", detailed_explanation="For 1999-00 the value changed.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=_facts(), flag_state=True
    )
    assert ValidationIssueCode.UNSUPPORTED_FINANCIAL_YEAR in {i.code for i in report.issues}


def test_supported_financial_year_passes():
    content = ExplanationContent(summary="s", detailed_explanation="For 2023-24 the value was recorded.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=_facts(), flag_state=True
    )
def test_invented_date_rejected():
    content = ExplanationContent(summary="s", detailed_explanation="Issued on 2001-02-03.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=_facts(), flag_state=True
    )
    assert ValidationIssueCode.UNSUPPORTED_DATE in {i.code for i in report.issues}


def test_forbidden_fraud_phrase_rejected():
    content = ExplanationContent(summary="s", detailed_explanation="This bidder committed fraud.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[], flag_state=True
    )
    assert ValidationIssueCode.FORBIDDEN_CONCLUSION in {i.code for i in report.issues}


def test_intent_phrase_rejected():
    content = ExplanationContent(summary="s", detailed_explanation="This is deliberate manipulation.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[], flag_state=True
    )
    assert ValidationIssueCode.FORBIDDEN_CONCLUSION in {i.code for i in report.issues}


def test_model_first_framing_rejected():
    content = ExplanationContent(summary="s", detailed_explanation="The AI thinks this bidder is suspicious.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[], flag_state=True
    )
    assert ValidationIssueCode.FORBIDDEN_CONCLUSION in {i.code for i in report.issues}


def test_invented_identifier_rejected():
    content = ExplanationContent(summary="s", detailed_explanation="GSTIN 29ABCDE1234F1Z5 is invalid.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[], flag_state=True
    )
    assert ValidationIssueCode.UNSUPPORTED_IDENTIFIER in {i.code for i in report.issues}


def test_supported_identifier_passes():
    identifier_fact = StructuredFact(fact_id="gst", kind=FactKind.IDENTIFIER, value="29ABCDE1234F1Z5")
    content = ExplanationContent(summary="s", detailed_explanation="GSTIN 29ABCDE1234F1Z5 was checked.")
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[identifier_fact], flag_state=True
    )
    assert ValidationIssueCode.UNSUPPORTED_IDENTIFIER not in {i.code for i in report.issues}


def test_no_grounding_rejects_unknown_claim():
    content = ExplanationContent(summary="s", detailed_explanation="evidence_999 proves it.", evidence_refs=["e_missing"])
    report = _validator().validate(
        content=content, grounding=ExplanationGrounding(), facts=[], flag_state=True
    )
    assert not report.is_valid


def test_unsupported_status_claim_detected_via_fact_ref():
    content = ExplanationContent(
        summary="s",
        detailed_explanation="d",
        observed_facts=[
            ObservedFact(fact_ref="fact_threshold", statement_type=StatementType.VERIFICATION_STATUS)
        ],
    )
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=_facts(), flag_state=True
    )
    assert ValidationIssueCode.STATEMENT_KIND_MISMATCH in {i.code for i in report.issues}


def test_false_flag_explained_as_true_rejected():
    content = ExplanationContent(
        summary="Flag is true.", detailed_explanation="The condition is satisfied."
    )
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[], flag_state=False
    )
    assert ValidationIssueCode.STATE_MISREPRESENTED in {i.code for i in report.issues}


def test_false_flag_with_absence_phrasing_passes():
    content = ExplanationContent(
        summary="Flag is false.",
        detailed_explanation="The available evidence does not establish the condition.",
    )
    report = _validator().validate(
        content=content, grounding=_grounding(), facts=[], flag_state=False
    )
    assert ValidationIssueCode.STATE_MISREPRESENTED not in {i.code for i in report.issues}
    assert ValidationIssueCode.UNSUPPORTED_FINANCIAL_YEAR not in {i.code for i in report.issues}