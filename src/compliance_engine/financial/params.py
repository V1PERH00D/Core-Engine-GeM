"""Typed financial requirement parameters.

Every field is optional: a tender supplies only the parameters it
actually needs. Extra keys are rejected (``extra="forbid"``) so a
misspelled threshold name surfaces loudly rather than being ignored.
Thresholds always come from these parameters; the engine never invents
a universal threshold.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from compliance_engine.financial.models import NonNegative


class FinancialRequirementParams(BaseModel):
    """The financial parameters a tender-derived requirement may supply."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Optional explicit focus selects which check the rule performs.
    focus: str | None = None

    # Turnover.
    minimum_turnover_inr_cr: NonNegative | None = None
    turnover_operator: str | None = None
    turnover_mode: str | None = None
    required_financial_years: tuple[str, ...] = ()

    # Net worth.
    minimum_net_worth_inr_cr: float | None = None

    # Solvency.
    require_positive_solvency: bool | None = None

    # Audit.
    require_audited: bool | None = None
    require_ca_udin: bool | None = None
    required_ca_subject: str | None = None

    # Balance sheet.
    required_balance_sheet_fields: tuple[str, ...] = ()

    @field_validator("required_financial_years", "required_balance_sheet_fields", mode="before")
    @classmethod
    def _coerce_to_tuple(cls, value: Any) -> Any:
        if value is None:
            return ()
        if isinstance(value, (tuple, list, set, frozenset)):
            return tuple(str(v) for v in value)
        return (str(value),)


__all__ = ["FinancialRequirementParams"]