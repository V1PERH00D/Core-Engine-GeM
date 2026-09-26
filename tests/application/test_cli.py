"""CLI surface: deterministic demo runner (offline, no credentials)."""

from __future__ import annotations

import json

from application.cli import main


def test_scenarios_command_lists_all_scenarios(capsys):
    assert main(["scenarios"]) == 0
    out = capsys.readouterr().out
    for name in ("clean", "failing", "missing", "inconsistent", "cross_bidder"):
        assert name in out


def test_demo_command_runs_a_scenario(capsys):
    assert main(["demo", "--scenario", "failing"]) == 0
    out = capsys.readouterr().out
    assert "demo-bidder-failing-02" in out
    assert "PROCUREMENT_DEBARMENT_ACTIVE" in out
    assert '"BIS_CERTIFICATE_INVALID": true' in out


def test_demo_json_output_keeps_contract_separate(capsys):
    assert main(["demo", "--scenario", "clean", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)

    # The compliance contract block is exactly bidder_id + flags.
    assert set(data["compliance"]) == {"bidder_id", "flags"}
    assert all(isinstance(v, bool) for v in data["compliance"]["flags"].values())

    # Supplementary detail is structurally separate.
    for key in ("processing", "requirements", "verifications", "findings",
                "explanations"):
        assert key in data
    assert data["processing"]["stage"] == "COMPLETE"


def test_demo_unknown_scenario_fails_cleanly(capsys):
    assert main(["demo", "--scenario", "nope"]) == 2
    err = capsys.readouterr().err
    assert "nope" in err
