"""Capture reproducible build metadata without including secrets or evidence."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
import subprocess


def git_commit(root: Path) -> str:
    """Return the current commit or an honest unknown marker."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return completed.stdout.strip() or "unknown"


def capture(root: Path) -> dict[str, str]:
    """Build a JSON-serializable provenance record."""

    return {
        "version": os.getenv("RECLAIM_BUILD_VERSION", "unversioned"),
        "commit_sha": git_commit(root),
        "captured_at": datetime.now(UTC).isoformat(),
        "source": "local-build-script",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(capture(root), sort_keys=True))


if __name__ == "__main__":
    main()
