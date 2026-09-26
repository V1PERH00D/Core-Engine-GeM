"""Command-line entry point for the deterministic demo.

Usage::

    python -m application demo [--scenario NAME] [--json] [--explain]
    python -m application scenarios

The demo requires no network access, no government API credentials, no
LLM API key, no PostgreSQL, and no Redis. Everything runs against the
in-memory persistence/queue backends wired through the same application
service used for production integration.
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

    sub.add_parser("scenarios", help="List the available demo scenarios.")
    return parser


def _print_scenario_summary(name: str, result, explain: bool) -> None:
    payload = result.compliance_payload()
    set_flags = result.set_flags()
    print(f"=== Scenario: {name} ===")
    print(get_scenario(name).description)
    print(f"bidder:      {payload['bidder_id']}")
    print(f"submission:  {result.processing.submission_id} "
          f"({result.processing.stage})")
    print(f"snapshot:    {result.processing.snapshot_id}")
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
        print("explanations (deterministic fallback, grounded):")
        for explanation in result.explanations:
            print(f"  - [{explanation.flag_id}] {explanation.text}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "scenarios":
        for name in scenario_names():
            print(f"{name}: {get_scenario(name).description}")
        return 0

    if args.command == "demo":
        names = [args.scenario] if args.scenario else None
        try:
            results = run_demo(names)
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
