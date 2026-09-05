from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "models" / "help-deepseek" / "manifest.json"
ENTRYPOINT_PATH = ROOT / "infra" / "model-help" / "entrypoint.sh"
DOCKERFILE_PATH = ROOT / "infra" / "model-help" / "Dockerfile"
RAILWAY_PATH = ROOT / "infra" / "railway" / "model-help.toml"
COMPOSE_PATH = ROOT / "infra" / "docker-compose.yml"
VERIFY_SCRIPT_PATH = ROOT / "scripts" / "models" / "verify_help_model.ps1"


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_model_image_consumes_the_manifest_and_keeps_weights_external() -> None:
    manifest = _manifest()
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT_PATH.read_text(encoding="utf-8")

    assert "COPY models/help-deepseek/manifest.json" in dockerfile
    assert "MODEL_MANIFEST_PATH" in dockerfile
    assert "MODEL_MANIFEST_PATH" in entrypoint
    assert "*.gguf" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert not list(ROOT.rglob("*.gguf"))
    assert manifest["artifact_policy"]["weights_committed"] is False


def test_entrypoint_downloads_only_when_absent_and_verifies_before_start() -> None:
    manifest = _manifest()
    model = manifest["model"]
    entrypoint = ENTRYPOINT_PATH.read_text(encoding="utf-8")

    assert 'MODEL_API_KEY:?MODEL_API_KEY is required' in entrypoint
    assert 'MODEL_DIR:=/models' in entrypoint
    assert 'MODEL_DOWNLOAD_URL' in entrypoint
    assert model["revision"] in entrypoint or "manifest_string revision" in entrypoint
    assert model["filename"] in entrypoint or "manifest_string filename" in entrypoint
    assert "sha256sum" in entrypoint
    assert "wc -c" in entrypoint
    assert re.search(r"if \[ ! -f \"\$MODEL_PATH\" \]; then", entrypoint)

    download = entrypoint.index("wget")
    temporary_verify = entrypoint.index("verify_model \"$temporary_path\"")
    promote = entrypoint.index("mv -f \"$temporary_path\" \"$MODEL_PATH\"")
    final_verify = entrypoint.index('verify_model "$MODEL_PATH"')
    server = entrypoint.index("exec llama-server")
    assert download < temporary_verify < promote < final_verify < server


def test_entrypoint_preserves_private_toolless_single_concurrency_server_contract() -> None:
    entrypoint = ENTRYPOINT_PATH.read_text(encoding="utf-8")

    assert '--host 0.0.0.0' in entrypoint
    assert '--port "${PORT:-8080}"' in entrypoint
    assert '--api-key "$MODEL_API_KEY"' in entrypoint
    assert "--no-webui" in entrypoint
    assert "--no-agent" in entrypoint
    assert "--parallel 1" in entrypoint
    assert "--ctx-size 4096" in entrypoint
    assert "--n-predict 1024" in entrypoint
    assert "tools" not in entrypoint.lower()


def test_railway_model_service_is_private_pinned_and_persistent() -> None:
    manifest = _manifest()
    model = manifest["model"]
    config = tomllib.loads(RAILWAY_PATH.read_text(encoding="utf-8"))

    assert config["build"]["dockerfilePath"] == "infra/model-help/Dockerfile"
    assert config["deploy"]["healthcheckPath"] == "/health"
    assert config["volumes"] == [{"name": "help-model-data", "mountPath": "/models"}]
    variables = config["variables"]
    assert variables["MODEL_MANIFEST_PATH"] == "/etc/reclaim/help-model-manifest.json"
    assert variables["MODEL_FILENAME"] == model["filename"]
    assert variables["MODEL_REVISION"] == model["revision"]
    assert variables["MODEL_SHA256"] == model["sha256"]
    assert variables["MODEL_SIZE_BYTES"] == str(model["size_bytes"])
    assert variables["MODEL_DOWNLOAD_URL"].endswith(
        f"/resolve/{model['revision']}/{model['filename']}?download=true"
    )
    assert "model_api_key" not in variables
    assert all("domain" not in key.lower() for key in config)


def test_compose_adds_private_model_service_without_publishing_model_port() -> None:
    manifest = _manifest()
    model = manifest["model"]
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))
    services = compose["services"]
    model_help = services["model-help"]
    gateway = services["model-gateway"]

    assert model_help["profiles"] == ["full"]
    assert model_help["build"] == {
        "context": "..",
        "dockerfile": "infra/model-help/Dockerfile",
    }
    assert "ports" not in model_help
    assert "/models" in model_help["volumes"][0]
    environment = model_help["environment"]
    assert environment["MODEL_API_KEY"] == "${MODEL_API_KEY:?MODEL_API_KEY is required}"
    assert environment["MODEL_FILENAME"] == model["filename"]
    assert environment["MODEL_REVISION"] == model["revision"]
    assert environment["MODEL_SHA256"] == model["sha256"]
    assert environment["MODEL_SIZE_BYTES"] == str(model["size_bytes"])
    assert gateway["environment"]["RECLAIM_HELP_API_BASE"] == "http://model-help:8080/v1"
    assert gateway["depends_on"]["model-help"]["condition"] == "service_healthy"


def test_powerShell_verifier_checks_identity_without_exposing_file_content() -> None:
    script = VERIFY_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "Get-FileHash -Algorithm SHA256" in script
    assert ".Length" in script
    assert "ConvertFrom-Json" in script
    assert "Get-Content -Raw" not in script
    assert "Write-Output $" not in script
    assert "Write-Error" in script
