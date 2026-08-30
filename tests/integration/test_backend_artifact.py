"""Clean wheel/sdist build and installed-artifact import smoke tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
REQUIRED_MODULES = {
    "api.intake": "create_intake_app",
    "workflows.case_workflow": "CaseWorkflow",
    "workflows.worker": "create_case_worker",
    "evidence.orchestrator": "EvidenceOrchestrator",
    "timeline.reconstruct": "TimelineReconstructor",
    "connectors.razorpay.webhook": "RazorpayWebhookVerifier",
    "app.events.redpanda": "RedpandaInboxDispatcher",
    "projections.neo4j_case_projection": "Neo4jCaseProjection",
    "packages.contracts.intake": "IncidentIntakeRequest",
}


def _run(*args: str, cwd: Path) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key != "PYTHONPATH"},
    )
    return result.stdout


def _installed_artifact_smoke(artifact: Path, target: Path, clean_cwd: Path) -> None:
    _run(
        sys.executable,
        "-m",
        "pip",
        "install",
        "--no-deps",
        "--no-build-isolation",
        "--target",
        str(target),
        str(artifact),
        cwd=clean_cwd,
    )
    smoke_code = (
        """
import importlib
import pathlib
import sys

target = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(target))
required = %r
for module_name, attribute in required.items():
    module = importlib.import_module(module_name)
    assert getattr(module, attribute)
    module_path = pathlib.Path(module.__file__).resolve()
    assert target == module_path or target in module_path.parents, module_path
"""
        % REQUIRED_MODULES
    )
    _run(
        sys.executable,
        "-I",
        "-c",
        smoke_code,
        str(target),
        cwd=clean_cwd,
    )


@pytest.fixture
def clean_backend_build() -> None:
    build_dir = BACKEND / "build"
    shutil.rmtree(build_dir, ignore_errors=True)
    yield
    shutil.rmtree(build_dir, ignore_errors=True)


def test_clean_wheel_and_sdist_contain_production_runtime_and_import_cleanly(
    clean_backend_build: None,
) -> None:
    transient_shared_package = BACKEND / "packages"
    assert not transient_shared_package.exists()
    with tempfile.TemporaryDirectory(prefix="reclaim-batch-c-") as directory:
        root = Path(directory)
        wheel_dir = root / "wheel"
        sdist_dir = root / "sdist"
        wheel_target = root / "wheel-installed"
        sdist_target = root / "sdist-installed"
        clean_cwd = root / "clean-cwd"
        for path in (wheel_dir, sdist_dir, wheel_target, sdist_target, clean_cwd):
            path.mkdir()

        _run(
            sys.executable,
            "-m",
            "pip",
            "wheel",
            ".",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_dir),
            cwd=BACKEND,
        )
        wheel = next(wheel_dir.glob("*.whl"))

        sdist_name = (
            _run(
                sys.executable,
                "-c",
                "from setuptools.build_meta import build_sdist; import sys; print(build_sdist(sys.argv[1]))",
                str(sdist_dir),
                cwd=BACKEND,
            )
            .strip()
            .splitlines()[-1]
        )
        sdist = sdist_dir / sdist_name
        assert sdist.is_file()

        with zipfile.ZipFile(wheel) as archive:
            wheel_files = set(archive.namelist())
        with tarfile.open(sdist) as archive:
            sdist_files = {name.replace("\\", "/") for name in archive.getnames()}

        for package in (
            "api/",
            "app/",
            "connectors/",
            "evidence/",
            "timeline/",
            "workflows/",
            "projections/",
            "packages/",
        ):
            assert any(
                name.startswith(package) and name.endswith(".py")
                for name in wheel_files
            )
            assert any(
                f"/{package}" in name and name.endswith(".py") for name in sdist_files
            )
        assert not any(
            "tests/" in name or name.startswith("tests/") for name in wheel_files
        )
        assert not any("tests/" in name for name in sdist_files)
        assert not any(name.endswith((".env", ".key")) for name in wheel_files)
        assert not any(name.endswith((".env", ".key")) for name in sdist_files)
        assert not any("security-audits/" in name for name in sdist_files)
        assert not any(
            "__pycache__/" in name or name.endswith((".pyc", ".pyo"))
            for name in wheel_files
        )
        assert not any(
            "__pycache__/" in name or name.endswith((".pyc", ".pyo"))
            for name in sdist_files
        )

        _installed_artifact_smoke(wheel, wheel_target, clean_cwd)
        _installed_artifact_smoke(sdist, sdist_target, clean_cwd)
    assert not transient_shared_package.exists()
