from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "models" / "help-deepseek" / "manifest.json"


def test_help_model_manifest_is_immutable_and_complete() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == "help-model-manifest-v1.0.0"
    assert manifest["profile_id"] == "reclaim-help-deepseek"
    assert manifest["status"] == "artifact-not-present"

    model = manifest["model"]
    assert model["repository"] == "ggml-org/DeepSeek-R1-Distill-Qwen-1.5B-Q4_0-GGUF"
    assert model["upstream_model"] == "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"
    assert model["revision"] == "fc9d48f477cfe8f983fa5e41557ecd47e619fef4"
    assert model["filename"] == "deepseek-r1-distill-qwen-1.5b-q4_0.gguf"
    assert model["sha256"] == "0d3f4820ee66ab44884b8176f17371eb1baa1d63df15740ffd5873d9e03e8978"
    assert model["size_bytes"] == 1_066_227_008
    assert model["quantization"] == "Q4_0"

    license_info = manifest["license"]
    assert license_info["references"]
    assert license_info["lineage_notice"]

    runtime = manifest["runtime"]
    assert runtime["image"].startswith("ghcr.io/ggml-org/llama.cpp@sha256:")
    assert len(runtime["image"].split("@sha256:", 1)[1]) == 64
    assert runtime["server_flags"] == [
        "--no-webui",
        "--no-agent",
        "--parallel",
        "1",
        "--ctx-size",
        "4096",
        "--n-predict",
        "1024",
    ]

    limits = manifest["limits"]
    assert limits == {
        "max_context_tokens": 4096,
        "max_input_tokens": 2048,
        "max_output_tokens": 1024,
        "max_concurrency": 1,
        "request_timeout_seconds": 60,
    }


def test_model_weight_is_not_checked_in_with_the_manifest() -> None:
    weight = MANIFEST.with_name("deepseek-r1-distill-qwen-1.5b-q4_0.gguf")

    assert not weight.exists()
    assert "*.gguf" in (ROOT / ".gitignore").read_text(encoding="utf-8")
