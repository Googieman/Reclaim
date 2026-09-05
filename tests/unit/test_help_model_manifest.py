from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_deployable_help_model_identity_matches_the_pinned_manifest() -> None:
    manifest = json.loads(
        (ROOT / "models" / "help-deepseek" / "manifest.json").read_text(encoding="utf-8")
    )
    model = manifest["model"]

    assert manifest["profile_id"] == "reclaim-help-deepseek"
    assert model == {
        "repository": "ggml-org/DeepSeek-R1-Distill-Qwen-1.5B-Q4_0-GGUF",
        "upstream_model": "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B",
        "revision": "fc9d48f477cfe8f983fa5e41557ecd47e619fef4",
        "filename": "deepseek-r1-distill-qwen-1.5b-q4_0.gguf",
        "sha256": "0d3f4820ee66ab44884b8176f17371eb1baa1d63df15740ffd5873d9e03e8978",
        "size_bytes": 1066227008,
        "quantization": "Q4_0",
    }
    assert not (ROOT / "models" / "help-deepseek" / model["filename"]).exists()

