"""Top-level compliance engine orchestration.

``ComplianceEngine`` is the single entry point that turns canonical
evidence and tender requirements into compliance results and identity
findings. It contains no capability-specific rule logic, performs no
government verification, and does not interpret tender text.

Rules and providers are constructor dependencies (infrastructure). Per
requests carry only the bidder's evidence and the requirements to
evaluate. The engine:

    * Groups requirements by capability and dispatches each group to
      :class:`RequirementExecutor` with the matching verification
      provider. The executor's own semantics are preserved unchanged for
      ``NOT_APPLICABLE``, ``UNKNOWN``, and missing-rule requirements.
    * Detects missing providers for applicable requirements *before* any
      rule runs and emits a single ``UNVERIFIABLE`` result per affected
      requirement, so a single provider outage cannot abort the whole
      bid. Provider detection is by lookup in the registered providers
      mapping; no rule exceptions are caught.
    * Invokes :func:`verify_cross_document_identity` once per run.

Unexpected exceptions from rules and from the identity verifier
propagate to the caller. Scoring, risk, and AI recommendation are
out-of-scope future components of the same system; they consume
``EngineResult`` and are not produced here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from compliance_engine.anomalies.identity import verify_cross_document_identity
from compliance_engine.models import (
    Applicability,
    ComplianceResult,
    ComplianceStatus,
    EngineResult,
    Evidence,
    Requirement,
)
from compliance_engine.rules.base import Rule
from compliance_engine.rules.executor import RequirementExecutor
from compliance_engine.verification.base import VerificationProvider


class ComplianceEngine:
    """Thin orchestrator over :class:`RequirementExecutor` and the identity verifier.

    Dependencies (rules, providers) are supplied once at construction.
    Each :meth:`run` invocation receives only the per-request data
    (evidence, requirements) and is otherwise stateless.
    """

    def __init__(
        self,
        *,
        rules: Mapping[str, Rule] | None = None,
        providers: Mapping[str, VerificationProvider] | None = None,
    ) -> None:
        """Store rule and provider mappings.

        ``rules`` is keyed by ``rule_id``. ``providers`` is keyed by
        the canonical machine-readable capability ID, e.g.
        :attr:`Capability.GST`, :attr:`Capability.PAN_INCOME_TAX`,
        :attr:`Capability.UDYAM`. A capability that has no entry in
        ``providers`` is treated as an unavailable verification source
        for applicable requirements; non-applicable and unknown
        applicability still flow through the executor unchanged.
        """
        self._rules: dict[str, Rule] = dict(rules) if rules else {}
        self._providers: dict[str, VerificationProvider] = (
            dict(providers) if providers else {}
        )
        self._executor = RequirementExecutor()

    def run(
        self,
        evidence: Sequence[Evidence],
        requirements: Sequence[Requirement],
    ) -> EngineResult:
        """Evaluate a single bid.

        Returns an :class:`EngineResult` containing one
        ``ComplianceResult`` per requirement and the identity findings
        produced from the same evidence. ``bidder_id`` on the result is
        derived from the first evidence record (or ``None`` if no
        evidence was supplied). The engine never mutates ``evidence`` or
        ``requirements``.
        """
        evidence_list = list(evidence)
        requirements_list = list(requirements)

        compliance_results = self._evaluate_requirements(
            evidence=evidence_list,
            requirements=requirements_list,
        )
        identity_findings = verify_cross_document_identity(evidence_list)

        bidder_id = evidence_list[0].bidder_id if evidence_list else None

        return EngineResult(
            bidder_id=bidder_id,
            compliance_results=compliance_results,
            identity_findings=identity_findings,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _evaluate_requirements(
        self,
        *,
        evidence: list[Evidence],
        requirements: list[Requirement],
    ) -> list[ComplianceResult]:
        """Group requirements by capability and dispatch to the executor.

        For each capability, the matching provider (if any) is looked up
        in the providers mapping. The executor is called once per
        capability with that provider and produces one
        ``ComplianceResult`` per requirement. ``NOT_APPLICABLE``,
        ``UNKNOWN``, and missing-rule results come from the executor
        itself and are not re-implemented here.

        If a capability has no registered provider, applicable rules
        would otherwise raise because the provider is required
        (e.g. ``GSTRegistrationRule``). Per the architecture, the
        orchestration layer detects this case *before* invoking any
        rule and emits one ``UNVERIFIABLE`` result per applicable
        requirement. ``NOT_APPLICABLE`` and ``UNKNOWN`` requirements in
        the same group still flow through the executor so its standard
        semantics remain the single source of truth for those statuses.

        Unexpected exceptions from rules (programming errors, type
        errors, custom rule failures) propagate to the caller. The
        engine never inspects exception types.
        """
        if not requirements:
            return []

        grouped: dict[str, list[Requirement]] = defaultdict(list)
        for requirement in requirements:
            grouped[requirement.capability].append(requirement)

        results: list[ComplianceResult] = []
        for capability, capability_requirements in grouped.items():
            provider = self._providers.get(capability)
            if provider is None:
                results.extend(
                    self._results_for_capability_without_provider(
                        capability_requirements
                    )
                )
                continue
            results.extend(
                self._executor.execute(
                    capability_requirements,
                    evidence,
                    self._rules,
                    provider=provider,
                )
            )
        return results

    def _results_for_capability_without_provider(
        self,
        requirements: list[Requirement],
    ) -> list[ComplianceResult]:
        """Produce results for a capability with no registered provider.

        ``NOT_APPLICABLE`` and ``UNKNOWN`` requirements are still
        passed to the executor (with ``provider=None``); the executor
        short-circuits those before any rule call, so the result is
        identical to what it would have produced with a real provider.
        Each ``APPLICABLE`` requirement in the group yields a single
        ``UNVERIFIABLE`` result, explaining that the required provider
        is not available.

        This is the engine's only translation beyond pure delegation.
        It does not duplicate the executor's ``NOT_APPLICABLE``,
        ``UNKNOWN``, or ``NOT_CHECKED`` semantics.
        """
        non_applicable: list[Requirement] = []
        applicable: list[Requirement] = []
        for requirement in requirements:
            if requirement.applicability in (
                Applicability.NOT_APPLICABLE,
                Applicability.UNKNOWN,
            ):
                non_applicable.append(requirement)
            else:
                applicable.append(requirement)

        results: list[ComplianceResult] = []
        if non_applicable:
            results.extend(
                self._executor.execute(
                    non_applicable,
                    evidence=[],
                    rules=self._rules,
                    provider=None,
                )
            )
        for requirement in applicable:
            results.append(
                ComplianceResult(
                    requirement_id=requirement.requirement_id,
                    capability=requirement.capability,
                    status=ComplianceStatus.UNVERIFIABLE,
                    reason=(
                        f"No verification provider is registered for capability "
                        f"{requirement.capability!r}; the requirement could not be verified."
                    ),
                    expected=requirement.expected,
                    actual=None,
                    evidence_refs=[],
                    verification_refs=[],
                    flags=[],
                    rule_id=requirement.rule_id,
                )
            )
        return results


__all__ = ["ComplianceEngine"]
