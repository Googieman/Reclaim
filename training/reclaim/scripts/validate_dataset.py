"""Validate RECLAIM specialization rows before any Soup training command."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from agent.output_parser import (  # noqa: E402
    AnalysisResponseError,
    parse_validated_analysis_response,
)
from agent.providers import ProviderMetadata  # noqa: E402

from evaluation.splitting import validate_split_order  # noqa: E402
from packages.contracts.analysis_policy import (  # noqa: E402
    ModelAnalysisRequest,
    ModelBudget,
    ProviderMode,
)

VALID_SPLITS = {"development", "validation", "held_out"}
FORBIDDEN_TEXT = re.compile(
    r"(?:api[_ -]?key|password|secret|access[_ -]?token|private[_ -]?key)",
    re.IGNORECASE,
)


def validate_dataset(dataset_dir: Path, manifest_path: Path) -> dict[str, Any]:
    manifest = _load_object(manifest_path)
    errors: list[str] = []
    _validate_manifest_metadata(manifest, errors)
    if manifest.get("held_out_sealed") is not True:
        errors.append("held_out_sealed must be true")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        errors.append("manifest cases must be a list")
        cases = []
    try:
        split_report = validate_split_order(cases)
    except (TypeError, ValueError) as exc:
        split_report = {"valid": False}
        errors.append(f"split validation failed: {exc}")

    seen: set[str] = set()
    rows_checked = Counter()
    labels = Counter()
    row_records: list[dict[str, Any]] = []
    for split in ("development", "validation"):
        path = dataset_dir / f"{split}.jsonl"
        if not path.exists():
            errors.append(f"missing dataset file: {path}")
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                _validate_row(row, expected_split=split, seen=seen, labels=labels)
                row_records.append(row)
            except (
                TypeError,
                ValueError,
                json.JSONDecodeError,
                AnalysisResponseError,
            ) as exc:
                errors.append(f"{path.name}:{line_number}: {exc}")
            else:
                rows_checked[split] += 1

    manifest_counts = manifest.get("rows_written", {})
    for split in ("development", "validation"):
        if int(manifest_counts.get(split, -1)) != rows_checked[split]:
            errors.append(f"manifest row count mismatch for {split}")
    if any(
        case.get("split") == "held_out" and case.get("sealed") is not True
        for case in cases
        if isinstance(case, dict)
    ):
        errors.append("held-out case metadata is not sealed")
    if (dataset_dir / "held_out.jsonl").exists() and (dataset_dir / "held_out.jsonl").read_text(encoding="utf-8").strip():
        errors.append("held-out payloads must not be emitted by the training builder")
    _validate_row_lineage(row_records, cases, errors)

    result = {
        "status": "valid" if not errors else "invalid",
        "dataset_version": manifest.get(
            "dataset_version", manifest.get("manifest_version")
        ),
        "manifest": str(manifest_path),
        "rows_checked": dict(rows_checked),
        "split_counts": manifest.get("split_counts", {}),
        "class_balance": dict(labels),
        "held_out_sealed": manifest.get("held_out_sealed") is True,
        "leakage": split_report,
        "errors": errors,
        "limitations": list(manifest.get("limitations", [])),
    }
    return result


def _validate_manifest_metadata(manifest: dict[str, Any], errors: list[str]) -> None:
    """Validate the training manifest independently of the row parser."""

    if manifest.get("manifest_version") != manifest.get("dataset_version"):
        errors.append("manifest and dataset versions must match")
    if not isinstance(manifest.get("source_files"), list) or not manifest["source_files"]:
        errors.append("source_files provenance is required")
    checksums = manifest.get("source_checksums")
    if not isinstance(checksums, dict):
        errors.append("source_checksums provenance is required")
    else:
        for source, checksum in checksums.items():
            if not isinstance(source, str) or not isinstance(checksum, str) or not re.fullmatch(r"[0-9a-f]{64}", checksum):
                errors.append(f"source checksum is invalid: {source}")
    if manifest.get("held_out_access_policy") != "final_evaluation_only":
        errors.append("held-out access policy must be final_evaluation_only")
    split_counts = manifest.get("split_counts")
    rows_written = manifest.get("rows_written")
    cases = manifest.get("cases")
    if not isinstance(split_counts, dict) or any(split not in split_counts for split in VALID_SPLITS):
        errors.append("split_counts must define all dataset splits")
    if not isinstance(rows_written, dict) or any(split not in rows_written for split in VALID_SPLITS):
        errors.append("rows_written must define all dataset splits")
    if not isinstance(cases, list):
        errors.append("manifest cases must be a list")
    elif isinstance(split_counts, dict):
        expected = Counter(case.get("split") for case in cases if isinstance(case, dict))
        for split in VALID_SPLITS:
            if split_counts.get(split) != expected[split]:
                errors.append(f"manifest split count mismatch for {split}")
    class_balance = manifest.get("class_balance")
    if not isinstance(class_balance, dict):
        errors.append("class_balance is required")
    elif any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in class_balance.values()):
        errors.append("class_balance values must be non-negative integers")


def _validate_row_lineage(
    rows: list[dict[str, Any]], cases: list[Any], errors: list[str]
) -> None:
    case_by_id = {
        str(case.get("evaluation_case_id")): case
        for case in cases
        if isinstance(case, dict) and case.get("evaluation_case_id")
    }
    for row in rows:
        provenance = row.get("provenance", {})
        case_id = str(row.get("example_id", "")).removeprefix("example-")
        case = case_by_id.get(case_id)
        if not isinstance(provenance, dict) or case is None:
            errors.append(f"row {row.get('example_id')} is not represented in manifest cases")
            continue
        for name in ("split", "entity_group_id", "customer_group_id", "temporal_boundary"):
            if provenance.get(name) != case.get(name):
                errors.append(f"row {row.get('example_id')} {name} does not match manifest case")


def _validate_row(
    row: Any, *, expected_split: str, seen: set[str], labels: Counter[str]
) -> None:
    if not isinstance(row, dict):
        raise TypeError("row must be an object")
    example_id = row.get("example_id")
    if not isinstance(example_id, str) or not example_id.strip():
        raise ValueError("example_id is required")
    if example_id in seen:
        raise ValueError("duplicate example_id")
    seen.add(example_id)
    if row.get("row_checksum") != _checksum(
        {key: value for key, value in row.items() if key != "row_checksum"}
    ):
        raise ValueError("row checksum does not match")
    messages = row.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise ValueError("row must contain exactly user and assistant messages")
    if [message.get("role") for message in messages if isinstance(message, dict)] != [
        "user",
        "assistant",
    ]:
        raise ValueError("row roles must be user then assistant")
    context = _json_message(messages[0], "user")
    target = _json_message(messages[1], "assistant")
    provenance = row.get("provenance")
    if not isinstance(provenance, dict):
        raise TypeError("provenance is required")
    required = (
        "case_source",
        "fixture_version",
        "data_class",
        "scenario_family",
        "compromise_status",
        "split",
        "generation_version",
        "label_version",
        "entity_group_id",
        "temporal_boundary",
    )
    missing = [name for name in required if not str(provenance.get(name, "")).strip()]
    if missing:
        raise ValueError(f"provenance fields missing: {missing}")
    if provenance["split"] != expected_split:
        raise ValueError("row split does not match file")
    if FORBIDDEN_TEXT.search(json.dumps(row, ensure_ascii=False)):
        raise ValueError("row contains secret-like field or text")
    if context.get("untrusted_evidence_notice") is None:
        raise ValueError("untrusted evidence notice is required")
    scope = context.get("scope")
    if not isinstance(scope, dict):
        raise TypeError("context scope is required")
    request = ModelAnalysisRequest(
        tenant_id=str(scope.get("tenant_id")),
        case_id=str(scope.get("case_id")),
        correlation_id=str(scope.get("correlation_id")),
        redacted_case_representation=context,
        evidence_references=tuple(
            item["evidence_id"]
            for item in context.get("evidence", [])
            if isinstance(item, dict) and item.get("evidence_id")
        ),
        allowed_tools=(),
        policy_version_id="policy-v1.0.0",
        budget=ModelBudget(max_tokens=2048, max_tool_calls=0, timeout_seconds=60),
        provider_mode=ProviderMode.REPLAY,
        replay_label=ProviderMode.REPLAY,
    )
    parsed = parse_validated_analysis_response(
        json.dumps(target),
        request,
        provider_metadata=ProviderMetadata(
            provider=target.get("provider", ""),
            model=target.get("model", ""),
            mode=ProviderMode.REPLAY,
        ),
    )
    allowed_timeline = {
        item.get("timeline_event_id")
        for item in context.get("timeline", [])
        if isinstance(item, dict)
    }
    for proposal in parsed.response.proposals:
        if proposal.action_type.value not in {
            "revoke_suspicious_session",
            "hold_fulfillment",
            "cancel_order",
            "refund_payment",
            "restore_identity",
        }:
            raise ValueError("unsupported action in target")
        if proposal.target_resource not in allowed_timeline:
            raise ValueError("target resource is not in context")
    for attribution in parsed.response.attributions:
        labels[attribution.label.value] += 1


def _json_message(message: Any, role: str) -> dict[str, Any]:
    if (
        not isinstance(message, dict)
        or message.get("role") != role
        or not isinstance(message.get("content"), str)
    ):
        raise ValueError(f"{role} message is malformed")
    value = json.loads(message["content"])
    if not isinstance(value, dict):
        raise TypeError(f"{role} content must be a JSON object")
    return value


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("manifest must be an object")
    return value


def _checksum(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    result = validate_dataset(args.dataset, args.manifest)
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "valid" else 2


if __name__ == "__main__":
    raise SystemExit(main())
