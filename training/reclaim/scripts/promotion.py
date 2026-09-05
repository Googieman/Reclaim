"""Build a conservative base-versus-specialist promotion report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .evaluate import compare_reports
except ImportError:  # pragma: no cover - supports direct CLI execution
    from evaluate import compare_reports


MIN_CHECKPOINT_BYTES = 1024


def validate_model_artifact(
    path: Path,
    *,
    expected_sha256: str | None = None,
    min_bytes: int = MIN_CHECKPOINT_BYTES,
) -> dict[str, Any]:
    """Validate an observed adapter artifact before it can support promotion."""

    candidate = path / "adapter_model.safetensors" if path.is_dir() else path
    if not candidate.exists() or not candidate.is_file():
        return {"qualified": False, "reason": "checkpoint artifact is missing", "path": str(candidate)}
    size = candidate.stat().st_size
    if size < min_bytes:
        return {"qualified": False, "reason": "checkpoint artifact is too small to be a valid checkpoint", "path": str(candidate), "size_bytes": size}
    checksum = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if expected_sha256 is not None and checksum != expected_sha256:
        return {"qualified": False, "reason": "checkpoint artifact checksum does not match provenance", "path": str(candidate), "size_bytes": size, "sha256": checksum}
    return {"qualified": True, "reason": "observed checkpoint artifact is present and checksummed", "path": str(candidate), "size_bytes": size, "sha256": checksum}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--specialist", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--training-manifest", type=Path)
    args = parser.parse_args(argv)
    base = json.loads(args.base.read_text(encoding="utf-8"))
    specialist = json.loads(args.specialist.read_text(encoding="utf-8"))
    report = compare_reports(base, specialist)
    if args.training_manifest:
        training_manifest = json.loads(args.training_manifest.read_text(encoding="utf-8"))
        artifact_name = training_manifest.get("adapter_artifact")
        artifact = Path(artifact_name) if isinstance(artifact_name, str) else None
        artifact_result = (
            validate_model_artifact(
                artifact,
                expected_sha256=training_manifest.get("adapter_sha256"),
            )
            if artifact is not None
            else {"qualified": False, "reason": "adapter artifact provenance is missing"}
        )
        report["artifact_validation"] = artifact_result
        if not artifact_result["qualified"]:
            report["decision"] = "DON'T SHIP"
            report.setdefault("limitations", []).append(
                "The observed specialist checkpoint is not qualified for promotion: "
                + artifact_result["reason"]
            )
    report["base_report"] = str(args.base)
    report["specialist_report"] = str(args.specialist)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"decision": report["decision"], "output": str(args.output)}))
    return 0 if report["decision"] == "SHIP" else 2


if __name__ == "__main__":
    raise SystemExit(main())
