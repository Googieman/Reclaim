"""Intentional expected-red seams for the US3 test-first batch.

These helpers make missing future production symbols fail inside the owning test
instead of causing collection/import failures.  They never provide an
implementation or fallback behavior.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from typing import Any


def require_symbol(module_name: str, symbol_name: str, *, task: str) -> Any:
    """Load a future production symbol or fail at the expected-red boundary."""

    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        missing_name = exc.name or "unknown module"
        if missing_name == module_name or module_name.startswith(f"{missing_name}."):
            raise AssertionError(
                f"{task} production seam is not implemented: {module_name}.{symbol_name}"
            ) from exc
        raise

    try:
        return getattr(module, symbol_name)
    except AttributeError as exc:
        raise AssertionError(
            f"{task} production seam is missing: {module_name}.{symbol_name}"
        ) from exc


def missing_symbols(requirements: Mapping[str, tuple[str, str]]) -> tuple[str, ...]:
    """Return every absent future seam with its explicit owning task."""

    missing: list[str] = []
    for owner, (module_name, symbol_name) in requirements.items():
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            missing_name = exc.name or "unknown module"
            if missing_name == module_name or module_name.startswith(
                f"{missing_name}."
            ):
                missing.append(f"{owner} -> {module_name}.{symbol_name}")
                continue
            raise
        if not hasattr(module, symbol_name):
            missing.append(f"{owner} -> {module_name}.{symbol_name}")
    return tuple(missing)


__all__ = ["missing_symbols", "require_symbol"]
