"""Shared helpers for agent nodes.

Agents are plain functions taking (state, router). The workflow binds the router
with functools.partial before handing them to LangGraph. Keeping the router an
explicit argument rather than a module global is what lets a test drive a single
agent against a stub provider without touching config or environment.
"""

from __future__ import annotations

from typing import Any, Optional

from ..integrations.router import ModelRouter


def emit_status(message: str) -> None:
    """Push a human-readable status line into the graph's custom stream.

    Wrapped in a try/except because get_stream_writer() only works inside a node
    executing under graph.stream(). The CLI and the unit tests call agents
    directly, and a status line is not worth failing a draft over.
    """
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
        if writer is not None:
            writer({"status": message})
    except Exception:
        pass


def merge_trace(router: ModelRouter, before: int) -> list[dict[str, Any]]:
    """The model calls this router made since index `before`.

    Nodes append only their own new calls, because `trace` is an accumulating
    channel: returning the router's whole call list from every node would
    duplicate every earlier entry once per node.
    """
    return [call.model_dump() for call in router.calls[before:]]


def first_nonempty(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if value and str(value).strip():
            return str(value).strip()
    return None
