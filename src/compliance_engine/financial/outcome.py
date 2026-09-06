"""The structured outcome of one financial evaluation.

A :class:`FinancialOutcome` is the intermediate, audit-grade result
produced by a financial rule before it is mapped onto the generic
:class:`ComplianceResult`. It carries the fields the financial vertical
slice must preserve: the check, status, deterministic reason, expected /
actual, financial years, evidence refs, flags and (where available) a
confidence.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from compliance_engine.models import ComplianceStatus
from compliance_engine.financial.models import Confidence, FinancialCheck


class FinancialOutcome(BaseModel):
    """Audit-grade result for one financial check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check: FinancialCheck
    status: ComplianceStatus
    reason: str
    flags: tuple[str, ...] = ()
    expected: Any = None
    actual: Any = None
    financial_years: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    confidence: Confidence | None = None


__all__ = ["FinancialOutcome"]