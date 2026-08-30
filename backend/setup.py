"""Legacy setuptools hook used only to make the backend sdist self-contained."""

from __future__ import annotations

import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.sdist import sdist as _sdist


class SelfContainedSdist(_sdist):
    """Include the repository-level shared contracts in backend source archives."""

    def make_release_tree(self, base_dir: str, files: list[str]) -> None:
        # setuptools records the mapped external files as ../packages/... in
        # SOURCES.txt.  Passing those paths to the base implementation would
        # normalize them into backend/packages, mutating the source tree.
        local_files = [
            file for file in files if not file.replace("\\", "/").startswith("../packages/")
        ]
        super().make_release_tree(base_dir, local_files)
        source = Path(__file__).resolve().parent.parent / "packages"
        destination = Path(base_dir) / "packages"
        shutil.copytree(
            source,
            destination,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.py[cod]"),
        )

        # The wheel is built from backend/ and maps the shared package one
        # directory upward.  An sdist is self-contained, so its generated
        # project metadata must resolve that same package from its own root.
        pyproject = Path(base_dir) / "pyproject.toml"
        metadata = pyproject.read_text(encoding="utf-8")
        metadata = metadata.replace('"packages" = "../packages"', '"packages" = "packages"')
        pyproject.write_text(metadata, encoding="utf-8")


setup(cmdclass={"sdist": SelfContainedSdist})
