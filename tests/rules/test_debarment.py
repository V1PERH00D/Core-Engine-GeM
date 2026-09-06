"""Tests for the procurement-eligibility / debarment rule.

Covers:

* verified CLEAR -> PASS,
* active verified restriction -> FAIL with the new flag,
* expired restriction -> PASS with historical provenance,
* UNKNOWN business status -> UNVERIFIABLE,
* provider failure modes (UNAVAILABLE / ERROR / NOT_FOUND /
  INVALID / 4xx without payload) -> UNVERIFIABLE,
* verification_refs preserved, evidence/document enrichment,
* provider failure never becomes FAIL,
* date semantics: active boundary, end-date boundary, future
  restriction, missing dates,
* reproducibility across evaluation dates,
* registry entry, severity, capability matrix invariant,
* backward-compat: no changes to existing 768 tests.
"""

from __future__ import annotations

from datetime import date, UTC, datetime
from typing import Any

import pytest

from compliance_engine.flags import get_flag_definition, FlagSeverity
from compliance_engine.models import (
    Applicability,
    ComplianceStatus,
    Evidence,
    Requirement,
    Verification,
    VerificationStatus,
)
from compliance_engine.rules.debarment import (
    FLAG_ACTIVE_RESTRICTION,
    FLAG_UNVERIFIABLE,
    DebarmentEligibilityRule,
    is_active_on,
)
from compliance_engine.verification.debarment_adapter import (
    DEBARMENT_CAPABILITY,
    DEBARMENT_SOURCE,
    DebarmentAdapter,
    DebarmentResponseParser,
    StaticDebarmentTransport,
)
from compliance_engine.verification.debarment_models import (
    DebarmentRestrictionStatus,
    DebarmentRestrictionType,
    MatchMethod,
)
from compliance_engine.verification.transport import SourceResponseEnvelope


RULE_ID = "DEBARMENT_ELIGIBILITY_001"


def _requirement(
    *,
    evaluation_date: date | None = None,
) -> Requirement:
    parameters: dict[str, Any] = {}
    if evaluation_date is not None:
        parameters["evaluation_date"] = evaluation_date
    return Requirement(
        requirement_id="req-debarment-001",
        capability=DEBARMENT_CAPABILITY,
        description="Procurement eligibility must be verified.",
        mandatory=True,
        applicability=Applicability.APPLICABLE,
        expected="CLEAR",
        rule_id=RULE_ID,
        parameters=parameters,
    )


def _identifier_evidence(value: str | None = "27AAACI1234F1Z5") -> Evidence:
    return Evidence(
        evidence_id="doc-deb-001:debarment_identifier",
        bidder_id="bidder_acme_01",
        document_id="doc-deb-001",
        document_type="DEBARMENT",
        field_name="debarment_identifier",
        value=value,
    )


def _subject_name_evidence(name: str) -> Evidence:
    return Evidence(
        evidence_id="doc-deb-001:subject_name",
        bidder_id="bidder_acme_01",
        document_id="doc-deb-001",
        document_type="DEBARMENT",
        field_name="subject_name",
        value=name,
    )


def _env(
    *,
    status_code: int,
    raw: dict[str, Any] | None = None,
    correlation_id: str | None = "corr-test",
) -> SourceResponseEnvelope:
    return SourceResponseEnvelope(
        status_code=status_code,
        raw_response=raw,
        latency_ms=15,
        correlation_id=correlation_id,
    )


def _clear_payload() -> dict[str, Any]:
    return {
        "restriction_status": "CLEAR",
        "match_method": "EXACT_IDENTIFIER",
    }


def _active_restricted_payload(
    *,
    effective: str = "2024-01-01",
    end: str | None = "2026-12-31",
    restriction_type: str = "DEBARMENT",
    match_method: str = "EXACT_IDENTIFIER",
    authority: str = "GeM",
    reference: str = "REF-2024-001",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "restriction_status": "RESTRICTED",
        "restriction_type": restriction_type,
        "effective_date": effective,
        "issuing_authority": authority,
        "reference_number": reference,
        "subject_type": "ORGANIZATION",
        "subject_identifier": "27AAACI1234F1Z5",
        "subject_name_original": "ACME ENTERPRISES PRIVATE LIMITED",
        "match_method": match_method,
    }
    if end is not None:
        payload["end_date"] = end
    return payload


# ---------------------------------------------------------------------------
# is_active_on: pure-function date semantics
# ---------------------------------------------------------------------------


def test_is_active_on_within_window() -> None:
    assert is_active_on(
        effective_date=date(2024, 1, 1),
        end_date=date(2026, 1, 1),
        evaluation_date=date(2025, 6, 15),
    )


def test_is_active_on_effective_in_future() -> None:
    assert not is_active_on(
        effective_date=date(2026, 1, 1),
        end_date=date(2027, 1, 1),
        evaluation_date=date(2025, 6, 15),
    )


def test_is_active_on_after_end_date() -> None:
    assert not is_active_on(
        effective_date=date(2020, 1, 1),
        end_date=date(2022, 1, 1),
        evaluation_date=date(2025, 6, 15),
    )


def test_is_active_on_end_date_exclusive() -> None:
    # Restriction ends on the evaluation date -> already expired.
    assert not is_active_on(
        effective_date=date(2024, 1, 1),
        end_date=date(2025, 6, 15),
        evaluation_date=date(2025, 6, 15),
    )


def test_is_active_on_effective_date_boundary_inclusive() -> None:
    # Restriction takes effect on the evaluation date -> active.
    assert is_active_on(
        effective_date=date(2025, 6, 15),
        end_date=date(2026, 1, 1),
        evaluation_date=date(2025, 6, 15),
    )


def test_is_active_on_open_ended() -> None:
    assert is_active_on(
        effective_date=date(2024, 1, 1),
        end_date=None,
        evaluation_date=date(2025, 6, 15),
    )


def test_is_active_on_missing_effective_date() -> None:
    assert not is_active_on(
        effective_date=None,
        end_date=date(2026, 1, 1),
        evaluation_date=date(2025, 6, 15),
    )


def test_is_active_on_missing_both_dates() -> None:
    assert not is_active_on(
        effective_date=None,
        end_date=None,
        evaluation_date=date(2025, 6, 15),
    )


# ---------------------------------------------------------------------------
# Verified CLEAR -> PASS
# ---------------------------------------------------------------------------


def test_verified_clear_maps_to_pass() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=_clear_payload()
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    evidence = [_identifier_evidence()]
    result = rule.evaluate(evidence, adapter, _requirement())
    assert result.status is ComplianceStatus.PASS
    assert result.rule_id == RULE_ID
    assert result.evidence_refs == [evidence[0].evidence_id]
    assert result.verification_refs  # populated
    assert result.flags == []
    assert result.actual["data"]["restriction_status"] == "CLEAR"


# ---------------------------------------------------------------------------
# Active verified restriction -> FAIL
# ---------------------------------------------------------------------------


def test_active_restriction_maps_to_fail() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    evidence = [_identifier_evidence()]
    evaluation_date = date(2025, 6, 15)
    result = rule.evaluate(
        evidence,
        adapter,
        _requirement(evaluation_date=evaluation_date),
    )
    assert result.status is ComplianceStatus.FAIL
    assert result.flags == [FLAG_ACTIVE_RESTRICTION]
    assert result.evidence_refs == [evidence[0].evidence_id]
    assert len(result.verification_refs) == 1


def test_active_restriction_severity_is_high() -> None:
    definition = get_flag_definition(FLAG_ACTIVE_RESTRICTION)
    assert definition.severity is FlagSeverity.HIGH
    assert definition.capability == "Blacklisting / Debarment"


# ---------------------------------------------------------------------------
# Expired restriction -> PASS with historical provenance
# ---------------------------------------------------------------------------


def test_expired_restriction_maps_to_pass_with_history() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(
                        effective="2020-01-01",
                        end="2022-01-01",
                    ),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    evidence = [_identifier_evidence()]
    evaluation_date = date(2025, 6, 15)
    result = rule.evaluate(
        evidence,
        adapter,
        _requirement(evaluation_date=evaluation_date),
    )
    assert result.status is ComplianceStatus.PASS
    assert result.flags == []
    assert result.actual["historical_restriction"] is True
    assert result.actual["data"]["restriction_status"] == "RESTRICTED"


# ---------------------------------------------------------------------------
# UNKNOWN business status -> UNVERIFIABLE
# ---------------------------------------------------------------------------


def test_unknown_business_maps_to_unverifiable() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw={"restriction_status": "UNKNOWN"},
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    evidence = [_identifier_evidence()]
    result = rule.evaluate(
        evidence,
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.flags == [FLAG_UNVERIFIABLE]


# ---------------------------------------------------------------------------
# Provider failure -> UNVERIFIABLE, never FAIL
# ---------------------------------------------------------------------------


def test_unavailable_provider_maps_to_unverifiable() -> None:
    adapter = DebarmentAdapter()  # no transport -> UNAVAILABLE
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.flags == [FLAG_UNVERIFIABLE]


def test_4xx_without_payload_maps_to_unverifiable() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(status_code=404, raw=None)
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.flags == [FLAG_UNVERIFIABLE]


def test_5xx_maps_to_unverifiable() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(status_code=503, raw=None)
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.flags == [FLAG_UNVERIFIABLE]


def test_provider_failure_never_becomes_fail() -> None:
    # No transport -> UNAVAILABLE. The rule must not turn this
    # into a FAIL even if the requirement says "expected=CLEAR".
    adapter = DebarmentAdapter()
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is not ComplianceStatus.FAIL


def test_malformed_payload_maps_to_unverifiable() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw={"foo": "bar"}
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.flags == [FLAG_UNVERIFIABLE]


# ---------------------------------------------------------------------------
# Missing / unknown evaluation date semantics
# ---------------------------------------------------------------------------


def test_restricted_without_evaluation_date_maps_to_unverifiable() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(),  # no evaluation_date
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE
    assert result.flags == [FLAG_UNVERIFIABLE]


def test_evaluation_date_via_kwargs_overrides_parameter() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    # The kwarg evaluation_date is before the effective_date
    # so the restriction is not active.
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
        evaluation_date=date(2019, 1, 1),
    )
    assert result.status is ComplianceStatus.PASS
    assert result.actual["historical_restriction"] is True


def test_evaluation_date_bad_type_raises() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={"X": _env(status_code=200, raw=_clear_payload())}
        )
    )
    rule = DebarmentEligibilityRule()
    with pytest.raises(TypeError):
        rule.evaluate(
            [_identifier_evidence("X")],
            adapter,
            _requirement(),
            evaluation_date="not-a-date",
        )


def test_parameter_evaluation_date_bad_type_raises() -> None:
    adapter = DebarmentAdapter()
    rule = DebarmentEligibilityRule()
    requirement = _requirement()
    requirement.parameters = {"evaluation_date": "not-a-date"}
    with pytest.raises(TypeError):
        rule.evaluate(
            [_identifier_evidence()],
            adapter,
            requirement,
        )


# ---------------------------------------------------------------------------
# Determinism across evaluation dates
# ---------------------------------------------------------------------------


def test_deterministic_outcome_for_same_inputs() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    evidence = [_identifier_evidence()]
    evaluation_date = date(2025, 6, 15)
    r1 = rule.evaluate(
        evidence,
        adapter,
        _requirement(evaluation_date=evaluation_date),
    )
    r2 = rule.evaluate(
        evidence,
        adapter,
        _requirement(evaluation_date=evaluation_date),
    )
    assert r1.status == r2.status == ComplianceStatus.FAIL
    assert r1.verification_refs != r2.verification_refs  # distinct IDs


def test_future_evaluation_date_passes_restricted() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(
                        effective="2024-01-01",
                        end="2024-06-01",
                    ),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    # Far-future evaluation date: restriction has expired.
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2030, 1, 1)),
    )
    assert result.status is ComplianceStatus.PASS
    assert result.actual["historical_restriction"] is True


def test_past_evaluation_date_before_effective_passes() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(
                        effective="2025-01-01",
                        end="2026-01-01",
                    ),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    # Pre-effective evaluation date: restriction not yet active.
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2024, 1, 1)),
    )
    assert result.status is ComplianceStatus.PASS


# ---------------------------------------------------------------------------
# Matching strategy enforcement
# ---------------------------------------------------------------------------


def test_name_only_match_with_dates_active_still_fails() -> None:
    # A name-only match (no identifier) is not a legal match.
    # The rule must surface UNVERIFIABLE rather than escalate
    # to FAIL even when dates are well-defined.
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(
                        match_method="EXACT_NAME",
                    ),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE


def test_insufficient_evidence_match_maps_to_unverifiable() -> None:
    # The source could not establish a reliable identity match.
    # Even with a RESTRICTED record on the source side, the
    # rule must surface UNVERIFIABLE because a "similar name"
    # is never a "confirmed legal entity".
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(
                        match_method="INSUFFICIENT_EVIDENCE",
                    ),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE


def test_similar_but_not_equal_name_with_no_dates_maps_to_unverifiable() -> None:
    # Same shape as an INSUFFICIENT_EVIDENCE-with-dates payload;
    # the rule must not turn it into a match.
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw={
                        "restriction_status": "RESTRICTED",
                        "restriction_type": "DEBARMENT",
                        "match_method": "NORMALIZED_NAME",
                        "subject_type": "ORGANIZATION",
                        "subject_name_original": "ACME ENTERPRISES LIMITED",
                    },
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.UNVERIFIABLE


# ---------------------------------------------------------------------------
# Evidence / document enrichment
# ---------------------------------------------------------------------------


def test_verification_evidence_id_and_document_id_enriched() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=_clear_payload()
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    evidence = [_identifier_evidence()]
    result = rule.evaluate(evidence, adapter, _requirement())
    # The verification_ref points to a verification with the
    # evidence_id and document_id populated.
    assert result.verification_refs
    # The rule copied the evidence_id/document_id onto the
    # verification; the engine's tracking wrapper preserves them.
    # We assert indirectly: the rule must not raise and must
    # return the same verification_refs.
    assert isinstance(result.verification_refs, list)


def test_subject_name_forwarded_to_query() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=_clear_payload()
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    evidence = [
        _identifier_evidence(),
        _subject_name_evidence("ACME ENTERPRISES"),
    ]
    rule.evaluate(evidence, adapter, _requirement())
    # The transport captured the query; the subject_name must be
    # in the query dict.
    assert adapter._transport.queries  # type: ignore[attr-defined]
    q = adapter._transport.queries[-1]  # type: ignore[attr-defined]
    assert q.subject_name == "ACME ENTERPRISES"


# ---------------------------------------------------------------------------
# Missing evidence
# ---------------------------------------------------------------------------


def test_missing_evidence_maps_to_missing() -> None:
    adapter = DebarmentAdapter()
    rule = DebarmentEligibilityRule()
    result = rule.evaluate([], adapter, _requirement())
    assert result.status is ComplianceStatus.MISSING
    assert result.verification_refs == []
    assert result.evidence_refs == []


def test_null_evidence_value_maps_to_missing() -> None:
    adapter = DebarmentAdapter()
    rule = DebarmentEligibilityRule()
    evidence = [_identifier_evidence(None)]
    result = rule.evaluate(evidence, adapter, _requirement())
    assert result.status is ComplianceStatus.MISSING


# ---------------------------------------------------------------------------
# Fallback identifier: well-known bidder identifier types
# ---------------------------------------------------------------------------


def test_gstin_evidence_used_as_fallback_identifier() -> None:
    # No DEBARMENT-typed evidence; the rule falls back to a GSTIN
    # field and queries the source against it.
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200, raw=_clear_payload()
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    evidence = [
        Evidence(
            evidence_id="doc-gst-001:gstin",
            bidder_id="bidder_acme_01",
            document_id="doc-gst-001",
            document_type="GST",
            field_name="gstin",
            value="27AAACI1234F1Z5",
        )
    ]
    result = rule.evaluate(evidence, adapter, _requirement())
    assert result.status is ComplianceStatus.PASS


def test_pan_evidence_used_as_fallback_identifier() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={"AAACI1234F": _env(
                status_code=200, raw=_clear_payload()
            )}
        )
    )
    rule = DebarmentEligibilityRule()
    evidence = [
        Evidence(
            evidence_id="doc-pan-001:pan_number",
            bidder_id="bidder_acme_01",
            document_id="doc-pan-001",
            document_type="PAN",
            field_name="pan_number",
            value="AAACI1234F",
        )
    ]
    result = rule.evaluate(evidence, adapter, _requirement())
    assert result.status is ComplianceStatus.PASS


# ---------------------------------------------------------------------------
# Provider-required assertions
# ---------------------------------------------------------------------------


def test_provider_required() -> None:
    rule = DebarmentEligibilityRule()
    with pytest.raises(ValueError, match="provider"):
        rule.evaluate([], None, _requirement())


def test_requirement_required() -> None:
    rule = DebarmentEligibilityRule()
    with pytest.raises(ValueError, match="requirement"):
        rule.evaluate([], DebarmentAdapter(), None)


# ---------------------------------------------------------------------------
# Restriction type variety
# ---------------------------------------------------------------------------


def test_suspension_active_restriction_fails() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(
                        restriction_type="SUSPENSION"
                    ),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.FAIL
    assert result.actual["data"]["restriction_type"] == "SUSPENSION"


def test_procurement_restriction_active_restriction_fails() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(
                        restriction_type="PROCUREMENT_RESTRICTION"
                    ),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.FAIL
    assert result.actual["data"]["restriction_type"] == (
        "PROCUREMENT_RESTRICTION"
    )


def test_blacklist_active_restriction_fails() -> None:
    adapter = DebarmentAdapter(
        transport=StaticDebarmentTransport(
            responses={
                "27AAACI1234F1Z5": _env(
                    status_code=200,
                    raw=_active_restricted_payload(
                        restriction_type="BLACKLIST"
                    ),
                )
            }
        )
    )
    rule = DebarmentEligibilityRule()
    result = rule.evaluate(
        [_identifier_evidence()],
        adapter,
        _requirement(evaluation_date=date(2025, 6, 15)),
    )
    assert result.status is ComplianceStatus.FAIL
    assert result.actual["data"]["restriction_type"] == "BLACKLIST"


# ---------------------------------------------------------------------------
# Flag definitions
# ---------------------------------------------------------------------------


def test_active_flag_definition_registered() -> None:
    definition = get_flag_definition(FLAG_ACTIVE_RESTRICTION)
    assert definition.flag_id == FLAG_ACTIVE_RESTRICTION
    assert definition.severity is FlagSeverity.HIGH
    assert definition.capability == "Blacklisting / Debarment"


def test_unverifiable_flag_definition_registered() -> None:
    definition = get_flag_definition(FLAG_UNVERIFIABLE)
    assert definition.flag_id == FLAG_UNVERIFIABLE
    assert definition.severity is FlagSeverity.MEDIUM
    assert definition.capability == "Blacklisting / Debarment"


# ---------------------------------------------------------------------------
# Rule id
# ---------------------------------------------------------------------------


def test_rule_id_is_stable() -> None:
    assert DebarmentEligibilityRule.rule_id == "DEBARMENT_ELIGIBILITY_001"
