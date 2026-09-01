"""Test import paths for the repository's shared and backend packages."""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
TESTS_ROOT = REPOSITORY_ROOT / "tests"
for path in (REPOSITORY_ROOT, BACKEND_ROOT, TESTS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
