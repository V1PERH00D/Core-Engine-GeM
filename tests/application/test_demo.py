"""Deterministic demo scenario contract.

The demo requires no network, no government credentials, and no LLM key;
results must be byte-identical across runs.
"""

from __future__ import annotations

import json

from application.demo import run_demo, scenario_names


def test_demo_has_all_five_scenarios():
    assert scenario_names() == [
        "clean",
        "cross_bidder",
        "failing",
        "inconsistent",
        "missing",
    ]


def test_demo_is_deterministic_across_runs():
    first = run_demo()
    second = run_demo()
    for name in scenario_names():
        assert (
            first[name].compliance == second[name].compliance
        ), f"scenario {name}: compliance payload differs"
        assert (
            first[name].processing.snapshot_id
            == second[name].processing.snapshot_id
        )


def test_demo_scenario_flags():
    results = run_demo()

    clean = results["clean"].set_flags()
    assert clean == {}

    failing = results["failing"].set_flags()
    assert set(failing) == {
        "BIS_CERTIFICATE_INVALID",
        "LOCAL_CONTENT_BELOW_THRESHOLD",
        "PROCUREMENT_DEBARMENT_ACTIVE",
        "TURNOVER_BELOW_THRESHOLD",
    }

    missing = results["missing"].set_flags()
    assert "GSTIN_MISSING" in missing
    assert "REQUIRED_FIELD_MISSING" in missing
    # Missing evidence must never appear as PASS.
    missing_statuses = {
        r.requirement_id: r.status for r in results["missing"].requirements
    }
    assert missing_statuses["demo-req-gst"] == "MISSING"
    assert missing_statuses["demo-req-bis"] == "MISSING"

    inconsistent = results["inconsistent"].set_flags()
    assert set(inconsistent) == {"CROSS_DOCUMENT_IDENTITY_MISMATCH"}

    cross_bidder = results["cross_bidder"].set_flags()
    assert set(cross_bidder) == {"CROSS_BIDDER_DOCUMENT_REUSED"}


def test_demo_output_is_boolean_only_everywhere():
    for name, result in run_demo().items():
        payload = json.loads(json.dumps(result.compliance_payload()))
        assert set(payload) == {"bidder_id", "flags"}
        assert all(isinstance(v, bool) for v in payload["flags"].values())
        flat = json.dumps(result.compliance_payload()).lower()
        assert "severity" not in payload
        assert "risk" not in payload


def test_demo_explanations_cover_every_set_flag():
    results = run_demo()
    for name in ("failing", "missing", "inconsistent"):
        result = results[name]
        explained = {e.flag_id for e in result.explanations}
        assert explained == set(result.set_flags()), name
        assert all(e.fallback_used for e in result.explanations), name


def test_demo_provides_both_true_and_false_flags():
    # The external contract demonstrates explicit true AND false values.
    result = run_demo(["failing"])["failing"]
    values = set(result.compliance.flags.values())
    assert values == {True, False}
