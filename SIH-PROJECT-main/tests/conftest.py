"""Pytest bootstrap for the SIH integration tests.

Adds the application root to ``sys.path`` (so ``import app...`` works) and
requires the Core-Engine-GeM package (``compliance_engine`` /
``ai_verification``) to be importable — install it with::

    pip install -e ../Core-Engine-GeM

No database, Redis, or external services are needed for this suite.
"""

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytest.importorskip("compliance_engine", reason="Core-Engine-GeM not installed")
pytest.importorskip("ai_verification", reason="Core-Engine-GeM not installed")

FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture()
def contradiction_fixture() -> dict:
    return load_fixture("contradiction_bidder.json")


@pytest.fixture()
def clean_fixture() -> dict:
    return load_fixture("clean_bidder.json")
