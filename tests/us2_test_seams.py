"""Intentional test seams for US2 components that are not implemented yet.

These helpers keep test-first coverage importable while production components are
still absent.  They never provide a test implementation or fallback behavior.
"""

from __future__ import annotations

import importlib
from typing import Any


def require_symbol(module_name: str, symbol_name: str, *, task: str) -> Any:
    """Load a future production symbol or fail inside the owning test.

    The caller marks tests using this helper as strict expected-red tests.  A
    missing module is therefore a test result, not a collection/import failure.
    """

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


__all__ = ["require_symbol"]
