"""Validate frozen dataset split metadata before training or model selection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from evaluation.splitting import validate_split_order  # noqa: E402


def validate_frozen_splits(manifest: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise TypeError("dataset manifest must be an object")
    if manifest.get("held_out_sealed") is not True:
        raise ValueError("held-out data must be sealed")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise TypeError("dataset manifest cases must be a list")
    report = validate_split_order(cases)
    if report.get("valid") is not True:
        raise ValueError("frozen split validation failed")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = validate_frozen_splits(manifest)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
