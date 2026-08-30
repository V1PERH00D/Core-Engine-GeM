"""Minimal abstract interface for tender evaluation rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from compliance_engine.models import Capability, ComplianceResult, Evidence, Requirement


class Rule(ABC):
    """Minimal evaluation contract for a rule implementation."""

    rule_id: str = ""
    name: str = ""
    required_providers: tuple[Capability, ...] = ()

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
