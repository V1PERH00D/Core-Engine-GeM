"""Minimal abstract interface for tender evaluation rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from compliance_engine.models import ComplianceResult, Evidence, Requirement


class Rule(ABC):
    """Minimal evaluation contract for a rule implementation."""

    rule_id: str = ""
    name: str = ""

    @abstractmethod
    def evaluate(
        self,
        evidence: list[Evidence],
        *args: Any,
        requirement: Requirement | None = None,
        provider: Any | None = None,
        **kwargs: Any,
    ) -> ComplianceResult:
        """Evaluate the rule against evidence and the relevant requirement/provider."""

        raise NotImplementedError
