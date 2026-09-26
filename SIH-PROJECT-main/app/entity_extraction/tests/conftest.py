"""Make the legacy Module 2 tests collectable when pytest runs from the
project root: they were written with bare-module imports
(``from tasks import ...``, ``from regex_patterns import ...``), which
require both the project root and this package directory on sys.path."""

import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parents[1]   # app/entity_extraction
_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # SIH-PROJECT-main

for _p in (str(_PKG_DIR), str(_PROJECT_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
