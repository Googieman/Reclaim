"""Validate and optionally measure the bounded help-chat corpus.

Without ``--url`` this performs an offline corpus check only. It never reports
model quality metrics unless real endpoint responses were observed.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def load_questions(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    required = {"id", "category", "question", "expected_status"}
    if not rows or any(set(row) != required for row in rows):
        raise ValueError("every question row must contain exactly id, category, question, expected_status")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("question IDs must be unique")
    counts = Counter(row["category"] for row in rows)
    expected = {"supported": 50, "unsupported": 20, "adversarial": 5}
    if counts != expected:
        raise ValueError(f"unexpected category counts: {dict(counts)}")
    if any(row["expected_status"] not in {"answered", "insufficient_evidence"} for row in rows):
        raise ValueError("unsupported expected status")
    return rows


def measure(url: str, token: str, rows: list[dict[str, Any]], timeout: float) -> dict[str, Any]:
    observed: list[dict[str, Any]] = []
    for row in rows:
        body = json.dumps({"question": row["question"]}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
                observed.append({"id": row["id"], "http_status": response.status, "status": payload.get("status")})
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            observed.append({"id": row["id"], "error": type(exc).__name__})
    return {"status": "measured", "observed": observed}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--url")
    parser.add_argument("--token", default="")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    try:
        rows = load_questions(args.dataset)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"dataset validation failed: {exc}", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "report_version": "help-chat-evaluation-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "dataset": str(args.dataset).replace("\\", "/"),
        "question_counts": dict(Counter(row["category"] for row in rows)),
        "metrics": None,
        "status": "resource_blocked",
        "blockers": [
            "No model weights were downloaded in this worktree.",
            "No authorized private or paid model service was provisioned.",
            "No live authenticated help endpoint was available for measurement.",
        ],
    }
    exit_code = 2
    if args.url:
        if not args.token:
            print("--token is required with --url", file=sys.stderr)
            return 2
        report.update(measure(args.url, args.token, rows, args.timeout))
        exit_code = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
