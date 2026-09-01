"""Public fixed tool registry for the bounded analysis harness."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .tools import (
    AgentToolRegistry,
    FixedToolRegistry,
    ToolContext,
    ToolRegistry,
)

ALLOWED_TOOL_NAMES = frozenset({"read_case", "read_evidence", "propose_action"})


def build_tool_registry(
    request: Any, *, context: ToolContext | None = None, allowed_tools: Sequence[str] | None = None
) -> ToolRegistry:
    """Build the fixed registry after checking request and tenant/case binding."""

    if allowed_tools is not None:
        return ToolRegistry(context, allowed_tools=allowed_tools)
    return ToolRegistry.for_request(request, context=context)


__all__ = [
    "ALLOWED_TOOL_NAMES",
    "AgentToolRegistry",
    "FixedToolRegistry",
    "ToolContext",
    "ToolRegistry",
    "build_tool_registry",
]
