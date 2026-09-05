"""Capture actual Soup/hardware environment information without inventing results."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def capture_environment(*, soup_executable: str = "soup") -> dict[str, Any]:
    path = shutil.which(soup_executable)
    result: dict[str, Any] = {
        "captured_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "soup_executable": path,
        "soup_doctor": {"status": "not_run", "stdout": "", "stderr": ""},
    }
    if path is None:
        result["soup_doctor"] = {
            "status": "unavailable",
            "stdout": "",
            "stderr": "soup executable was not found on PATH",
        }
        return result
    completed = subprocess.run(
        [path, "doctor"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=300,
    )
    result["soup_doctor"] = {
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": _safe_text(completed.stdout or ""),
        "stderr": _safe_text(completed.stderr or ""),
    }
    return result


def _safe_text(value: str) -> str:
    # Doctor output is diagnostic, but do not persist likely secret assignments.
    lines = []
    for line in value.splitlines():
        lower = line.lower()
        if any(
            marker in lower for marker in ("api_key=", "token=", "password=", "secret=")
        ):
            lines.append("[REDACTED DIAGNOSTIC LINE]")
        else:
            lines.append(line)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soup", default="soup")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = capture_environment(soup_executable=args.soup)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"status": result["soup_doctor"]["status"], "output": str(args.output)}
        )
    )
    return 0 if result["soup_doctor"]["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
