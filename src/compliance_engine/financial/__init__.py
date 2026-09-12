"""Financial Capacity verification and consistency engine.

This package implements the Financial Capacity vertical slice of the
compliance engine: typed financial evidence, deterministic derived
metrics, tender-supplied threshold evaluation, financial consistency and
turnover trend checks, and CA/UDIN compatibility. It performs no
network calls and never invents government data or universal thresholds.
"""

from compliance_engine.financial import flags
from compliance_engine.financial.arithmetic import (
    derived_working_capital,
    working_capital,
)
from compliance_engine.financial.consistency import (
    FINANCIAL_NUMERIC_TOLERANCE,
    ConsistencyFinding,
    check_financial_consistency,
)
from compliance_engine.financial.evaluation import determine_focus, evaluate
from compliance_engine.financial.findings import (
    consistency_finding_to_verification_finding,
    outcome_to_compliance_result,
    trend_anomaly_to_verification_finding,
)
from compliance_engine.financial.models import (
    AuditInfo,
    BalanceSheet,
    ComparisonOperator,
    FinancialCheck,
    FinancialProfile,
    FinancialYear,
    MoneyUnit,
    NetWorth,
    Solvency,
    TurnoverMode,
    TurnoverPoint,
)
from compliance_engine.financial.normalization import (
    normalize_financial_profile,
)
from compliance_engine.financial.outcome import FinancialOutcome
from compliance_engine.financial.params import FinancialRequirementParams
from compliance_engine.financial.thresholds import (
    aggregate_turnover,
    evaluate_threshold,
    select_turnover_by_years,
)
from compliance_engine.financial.trend import (
    MAX_ANNUAL_TREND_RATIO,
    MIN_TREND_YEARS,
    TrendAnomaly,
    detect_turnover_trend_anomaly,
)
from compliance_engine.financial.years import normalize_financial_year

__all__ = [
    "AuditInfo",
    "BalanceSheet",
    "ComparisonOperator",
    "FINANCIAL_NUMERIC_TOLERANCE",
    "ConsistencyFinding",
    "FinancialCheck",
    "FinancialOutcome",
    "FinancialProfile",
    "FinancialRequirementParams",
    "FinancialYear",
    "MAX_ANNUAL_TREND_RATIO",
    "MIN_TREND_YEARS",
    "MoneyUnit",
    "NetWorth",
    "Solvency",
    "TrendAnomaly",
    "TurnoverMode",
    "TurnoverPoint",
    "aggregate_turnover",
    "check_financial_consistency",
    "consistency_finding_to_verification_finding",
    "derived_working_capital",
    "detect_turnover_trend_anomaly",
    "determine_focus",
    "evaluate",
    "evaluate_threshold",
    "flags",
    "normalize_financial_profile",
    "normalize_financial_year",
    "outcome_to_compliance_result",
    "select_turnover_by_years",
    "trend_anomaly_to_verification_finding",
    "working_capital",
]