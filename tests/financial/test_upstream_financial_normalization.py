"""Financial normalization against the REAL upstream sample fixtures.

These tests prove that the actual upstream balance-sheet document (scalar
financial fields, no document-level financial_year) flows through
``normalize_upstream`` -> ``normalize_financial_profile`` -> ``evaluate``
without losing values and without fabricating financial years.
"""

import json
from pathlib import Path

from compliance_engine.financial.evaluation import evaluate
from compliance_engine.financial.models import FinancialYear
from compliance_engine.financial.normalization import normalize_financial_profile
from compliance_engine.financial.params import FinancialRequirementParams
from compliance_engine.ingestion import normalize_upstream
from compliance_engine.models import ComplianceStatus

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "upstream"


def _profile(name: str = "sample.json"):
    payload = json.loads((FIXTURES / name).read_text())
    evidence = normalize_upstream(payload)
    return normalize_financial_profile(evidence), {e.field_name: e for e in evidence}


def test_annual_turnovers_reach_profile_with_years() -> None:
    profile, _ = _profile()
    points = {p.financial_year.canonical: p.turnover_inr_cr for p in profile.annual_turnovers}
    assert points == {"2022-23": 12.5, "2023-24": 15.8, "2024-25": 18.2}


def test_turnover_rule_passes_with_real_sample() -> None:
    profile, _ = _profile()
    params = FinancialRequirementParams.model_validate(
        {
            "minimum_turnover_inr_cr": 10.0,
            "turnover_operator": ">=",
            "turnover_mode": "AVERAGE_ANNUAL",
            "required_financial_years": ["2022-23", "2023-24", "2024-25"],
        }
    )
    outcome = evaluate(params, profile)
    assert outcome.status is ComplianceStatus.PASS


def test_scalar_net_worth_reaches_profile_without_year() -> None:
    profile, evidence = _profile()
    assert len(profile.net_worth) == 1
    nw = profile.net_worth[0]
    assert nw.value_inr_cr == 26.5
    assert nw.financial_year is None  # not fabricated
    assert nw.evidence_id == evidence["net_worth"].evidence_id


def test_scalar_balance_sheet_fields_reach_profile_without_year() -> None:
    profile, _ = _profile()
    assert len(profile.balance_sheets) == 1
    sheet = profile.balance_sheets[0]
    assert sheet.financial_year is None  # not fabricated
    assert sheet.profit_after_tax_inr_cr == 3.4
    assert sheet.total_assets_inr_cr == 45.0
    assert sheet.total_liabilities_inr_cr == 18.5
    assert sheet.current_assets_inr_cr == 20.0
    assert sheet.current_liabilities_inr_cr == 8.5



def test_scalar_solvency_indicator_reaches_profile_without_year() -> None:
    profile, evidence = _profile()
    assert len(profile.solvency) == 1
    entry = profile.solvency[0]
    assert entry.is_solvency_positive is True
    assert entry.financial_year is None
    assert entry.evidence_id == evidence["solvency_indicator"].evidence_id


def test_solvency_rule_passes_without_year_requirement() -> None:
    profile, _ = _profile()
    params = FinancialRequirementParams.model_validate({"require_positive_solvency": True})
    outcome = evaluate(params, profile)
    assert outcome.status is ComplianceStatus.PASS
    assert outcome.financial_years == ()


def test_audited_status_maps_to_internal_audited_flag() -> None:
    profile, _ = _profile()
    assert profile.audit is not None
    assert profile.audit.audited is True


def test_ca_udin_is_preserved() -> None:
    profile, _ = _profile()
    assert profile.audit is not None
    assert profile.audit.ca_udin == "24045678AAAAAA1234"


def test_audit_rule_passes_with_real_sample() -> None:
    profile, _ = _profile()
    params = FinancialRequirementParams.model_validate(
        {"require_audited": True, "require_ca_udin": True}
    )
    outcome = evaluate(params, profile)
    assert outcome.status is ComplianceStatus.PASS


def test_net_worth_rule_passes_without_year_requirement() -> None:
    profile, _ = _profile()
    params = FinancialRequirementParams.model_validate({"minimum_net_worth_inr_cr": 20.0})
    outcome = evaluate(params, profile)
    assert outcome.status is ComplianceStatus.PASS
    assert outcome.actual["value_inr_cr"] == 26.5
    assert outcome.actual["financial_year"] is None
    assert outcome.financial_years == ()


def test_balance_sheet_completeness_rule_passes() -> None:
    profile, _ = _profile()
    params = FinancialRequirementParams.model_validate(
        {
            "required_balance_sheet_fields": [
                "total_assets_inr_cr",
                "total_liabilities_inr_cr",
                "current_assets_inr_cr",
                "current_liabilities_inr_cr",
                "profit_after_tax_inr_cr",
            ]
        }
    )
    outcome = evaluate(params, profile)
    assert outcome.status is ComplianceStatus.PASS


def test_no_financial_year_is_fabricated_for_scalar_fields() -> None:
    profile, _ = _profile()
    scalar_entries = (
        list(profile.net_worth) + list(profile.solvency) + list(profile.balance_sheets)
    )
    assert scalar_entries
    assert all(e.financial_year is None for e in scalar_entries)


def test_year_required_rule_reports_missing_instead_of_guessing() -> None:
    profile, _ = _profile()
    params = FinancialRequirementParams.model_validate(
        {"minimum_net_worth_inr_cr": 20.0, "required_financial_years": ["2023-24"]}
    )
    outcome = evaluate(params, profile)
    assert outcome.status is ComplianceStatus.MISSING
    assert "financial year" in outcome.reason


def test_undated_entries_do_not_pollute_year_lookups() -> None:
    profile, _ = _profile()
    fy = FinancialYear.parse("2023-24")
    assert profile.net_worth_for_year(fy) is None
    assert profile.balance_sheet_for_year(fy) is None
    assert profile.solvency_for_year(fy) is None
    assert profile.turnover_for_year(fy) is not None
