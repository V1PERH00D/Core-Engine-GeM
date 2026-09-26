"""Command-line entry point for the deterministic demo.

Usage::

    python -m application demo [--scenario NAME] [--json] [--explain]
                               [--explanations {fallback,mock,gemini}]
    python -m application scenarios

The demo requires no network access, no government API credentials, no
LLM API key, no PostgreSQL, and no Redis. Everything runs against the
in-memory persistence/queue backends wired through the same application
service used for production integration.

Explanations default to the deterministic fallback (``--explanations
fallback``). ``mock`` routes the same grounded explanation path through a
deterministic in-process mock model; ``gemini`` uses the live Gemini
provider and requires ``GEMINI_API_KEY`` (``GEMINI_MODEL`` optional).
A live model only explains — the boolean compliance flags are fixed
upstream by the deterministic engines and are identical across all three
modes.
"""

from __future__ import annotations

import argparse
import json
import sys

from application.demo import get_scenario, run_demo, scenario_names


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m application",
        description=(
            "GeM bid-compliance demo runner (SIH PS 26100). Fully offline "
            "and deterministic; all government-side providers are static "
            "demo providers (*_DEMO sources)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser(
        "demo", help="Run the deterministic demo scenarios end-to-end."
    )
    demo.add_argument(
        "--scenario",
        metavar="NAME",
        default=None,
        help="Run a single scenario (see `scenarios`). Default: all.",
    )
    demo.add_argument(
        "--json",
        action="store_true",
        help="Emit the full ApplicationResult JSON (compliance contract + "
        "supplementary detail) instead of a human summary.",
    )
    demo.add_argument(
        "--explain",
        action="store_true",
        help="In human summary mode, also print one explanation line per "
        "set flag.",
    )
    demo.add_argument(
        "--explanations",
        choices=("fallback", "mock", "gemini"),
        default="fallback",
        help=(
            "Explanation generator. 'fallback' (default) is the "
            "deterministic built-in; 'mock' demonstrates the model path "
            "offline; 'gemini' calls the live Gemini API and requires "
            "GEMINI_API_KEY (GEMINI_MODEL to override the default model)."
        ),
    )

    sub.add_parser("scenarios", help="List the available demo scenarios.")
    return parser


def _build_explanation_model(mode: str):
    """Resolve the CLI explanation mode to an ``ExplanationModel``.

    ``None`` means "no model": the engine's deterministic fallback runs.
    ``mock`` is a deterministic in-process model for offline demos of the
    full LLM plumbing. ``gemini`` requires ``GEMINI_API_KEY``.
    """
    if mode == "fallback":
        return None
    if mode == "mock":
        from ai_verification.explanations.provider import (
            StaticExplanationModel,
        )

        return StaticExplanationModel(
            model_name="mock-llm:demo", provider_name="mock_llm_demo"
        )
    if mode == "gemini":
        from ai_verification.explanations.gemini import (
            GEMINI_API_KEY_ENV,
            GeminiExplanationModel,
        )

        model = GeminiExplanationModel.from_env()
        if model is None:
            print(
                f"{GEMINI_API_KEY_ENV} is not set; cannot use the live "
                "Gemini provider. Set GEMINI_API_KEY (and optionally "
                "GEMINI_MODEL), or run with `--explanations mock` / "
                "`--explanations fallback`.",
                file=sys.stderr,
            )
            return None
        return model
    return None  # pragma: no cover - argparse enforces the choices


def _print_scenario_summary(name: str, result, explain: bool) -> None:
    payload = result.compliance_payload()
    set_flags = result.set_flags()
    print(f"=== Scenario: {name} ===")
    print(get_scenario(name).description)
    print(f"bidder:      {payload['bidder_id']}")
    print(f"submission:  {result.processing.submission_id} "
          f"({result.processing.stage})")
    print(f"snapshot:    {result.processing.snapshot_id}")
    if result.document_score is not None:
        print(
            f"document:    {result.document_score.category.value} "
            f"({result.document_score.score:.2f}/100)"
        )
        print(f"summary:     {result.document_score.summary}")
    print("compliance contract:")
    print(
        json.dumps(
            {"bidder_id": payload["bidder_id"], "flags": payload["flags"]},
            indent=2,
            sort_keys=True,
        )
    )
    print(f"flags set ({len(set_flags)}): {sorted(set_flags)}")
    for requirement in result.requirements:
        print(
            f"  [{requirement.status:14s}] {requirement.requirement_id}"
            + (f" -> flags {requirement.flags}" if requirement.flags else "")
        )
    if explain and set_flags:
        print("explanations (grounded; LLM never changes the flags):")
        for explanation in result.explanations:
            source = (
                "fallback"
                if explanation.fallback_used
                else (explanation.provider or "model")
            )
            print(
                f"  - [{explanation.flag_id}] ({source}) {explanation.text}"
            )
            print(
                f"      evidence={explanation.evidence_refs} "
                f"verifications={explanation.verification_refs} "
                f"trace={explanation.trace_refs}"
            )


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "scenarios":
        for name in scenario_names():
            print(f"{name}: {get_scenario(name).description}")
        return 0

    if args.command == "demo":
        names = [args.scenario] if args.scenario else None
        explanation_model = _build_explanation_model(args.explanations)
        if args.explanations == "gemini" and explanation_model is None:
            return 2  # live mode requested but GEMINI_API_KEY is absent
        try:
            results = run_demo(names, explanation_model=explanation_model)
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        for name, result in results.items():
            if args.json:
                print(json.dumps(result.to_display_dict(), indent=2, sort_keys=True))
            else:
                _print_scenario_summary(name, result, args.explain)
        return 0

    return 2  # unreachable; argparse enforces the subcommand


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
