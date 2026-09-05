from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest
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
    assert environment["MODEL_API_KEY"] == "${MODEL_API_KEY:-}"
    assert environment["MODEL_FILENAME"] == model["filename"]
    assert environment["MODEL_REVISION"] == model["revision"]
    assert environment["MODEL_SHA256"] == model["sha256"]
    assert environment["MODEL_SIZE_BYTES"] == str(model["size_bytes"])
    assert gateway["environment"]["RECLAIM_HELP_API_BASE"] == "http://model-help:8080/v1"
    assert gateway["environment"]["MODEL_API_KEY"] == "${MODEL_API_KEY:-}"
    assert gateway["depends_on"]["model-help"]["condition"] == "service_healthy"


def test_model_api_key_is_runtime_required_but_compose_interpolation_is_optional() -> None:
    compose = yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))

    assert (
        compose["services"]["model-help"]["environment"]["MODEL_API_KEY"]
        == "${MODEL_API_KEY:-}"
    )
    assert (
        compose["services"]["model-gateway"]["environment"]["MODEL_API_KEY"]
        == "${MODEL_API_KEY:-}"
    )
    assert "MODEL_API_KEY:?" not in COMPOSE_PATH.read_text(encoding="utf-8")
    assert ': "${MODEL_API_KEY:?MODEL_API_KEY is required}"' in ENTRYPOINT_PATH.read_text(
        encoding="utf-8"
    )


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _run_launcher_with_download_payload(
    tmp_path: Path,
    payload: bytes,
    *,
    existing_payload: bytes | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    shell = shutil.which("sh") or shutil.which("bash")
    required_tools = ("awk", "head", "mktemp", "sed", "sha256sum", "tr", "wc")
    if shell is None or any(shutil.which(tool) is None for tool in required_tools):
        pytest.skip("POSIX shell and checksum tools are required for launcher safety coverage")

    model_dir = tmp_path / "models"
    manifest_path = tmp_path / "manifest.json"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    server_marker = tmp_path / "server-started"
    wget_marker = tmp_path / "wget-called"
    expected_payload = b"good"
    manifest_path.write_text(
        json.dumps(
            {
                "status": "artifact-not-present",
                "model": {
                    "repository": "fixture/help-model",
                    "revision": "fixture-revision",
                    "filename": "fixture.gguf",
                    "sha256": hashlib.sha256(expected_payload).hexdigest(),
                    "size_bytes": len(expected_payload),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_executable(
        bin_dir / "wget",
        """#!/bin/sh
set -eu
output=
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-O" ]; then
    output="$2"
    shift 2
  else
    shift
  fi
done
printf '%s' "$WGET_PAYLOAD" > "$output"
: > "$WGET_MARKER"
""",
    )
    _write_executable(
        bin_dir / "llama-server",
        """#!/bin/sh
set -eu
: > "$LLAMA_MARKER"
""",
    )

    environment = os.environ.copy()
    environment.update(
        {
            "MODEL_API_KEY": "fixture-runtime-key",
            "MODEL_MANIFEST_PATH": manifest_path.as_posix(),
            "MODEL_DIR": model_dir.as_posix(),
            "MODEL_PATH": (model_dir / "fixture.gguf").as_posix(),
            "WGET_PAYLOAD": payload.decode("ascii"),
            "WGET_MARKER": wget_marker.as_posix(),
            "LLAMA_MARKER": server_marker.as_posix(),
            "PATH": os.pathsep.join((bin_dir.as_posix(), environment["PATH"])),
        }
    )
    if existing_payload is not None:
        model_dir.mkdir()
        (model_dir / "fixture.gguf").write_bytes(existing_payload)
    result = subprocess.run(
        [shell, str(ENTRYPOINT_PATH)],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result, model_dir, server_marker


def test_launcher_refuses_mismatched_download_and_cleans_temp_file(tmp_path: Path) -> None:
    result, model_dir, server_marker = _run_launcher_with_download_payload(tmp_path, b"bad")

    assert result.returncode != 0
    assert not server_marker.exists()
    assert (tmp_path / "wget-called").exists()
    assert not list(model_dir.glob(".fixture.gguf.download.*"))
    assert not (model_dir / "fixture.gguf").exists()


def test_launcher_refuses_mismatched_existing_model_without_downloading_or_starting(
    tmp_path: Path,
) -> None:
    result, model_dir, server_marker = _run_launcher_with_download_payload(
        tmp_path,
        b"good",
        existing_payload=b"bad",
    )

    assert result.returncode != 0
    assert not server_marker.exists()
    assert not (tmp_path / "wget-called").exists()
    assert not list(model_dir.glob(".fixture.gguf.download.*"))


@pytest.mark.parametrize("artifact_payload", [b"bad", b"nope"])
def test_powershell_verifier_rejects_wrong_size_or_checksum_without_content_output(
    tmp_path: Path,
    artifact_payload: bytes,
) -> None:
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell is required for verifier executable coverage")

    expected_payload = b"good"
    manifest_path = tmp_path / "manifest.json"
    artifact_path = tmp_path / "fixture.gguf"
    manifest_path.write_text(
        json.dumps(
            {
                "status": "artifact-not-present",
                "model": {
                    "filename": "fixture.gguf",
                    "sha256": hashlib.sha256(expected_payload).hexdigest(),
                    "size_bytes": len(expected_payload),
                },
            }
        ),
        encoding="utf-8",
    )
    artifact_path.write_bytes(artifact_payload)

    result = subprocess.run(
        [
            powershell,
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(VERIFY_SCRIPT_PATH),
            "-ArtifactPath",
            str(artifact_path),
            "-ManifestPath",
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert "help model artifact verification failed" in result.stderr.lower()
    assert artifact_payload.decode("ascii") not in result.stdout + result.stderr


def test_powershell_verifier_checks_identity_without_exposing_file_content() -> None:
    script = VERIFY_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "Get-FileHash -Algorithm SHA256" in script
    assert ".Length" in script
    assert "ConvertFrom-Json" in script
    assert "Get-Content -Raw" not in script
    assert "Write-Output $" not in script
    assert "Write-Error" in script
