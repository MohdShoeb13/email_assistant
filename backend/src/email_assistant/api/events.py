"""Turning a graph run into a stream of SSE events.

The event vocabulary is the contract between the graph and the pipeline rail in
the UI, so it lives in one file rather than being assembled inline in the route.

Why a queue rather than yielding straight from the graph: model-call records
arrive through the router's `on_call` hook, which fires *during* a node, while
node updates arrive from the graph's own stream *after* a node finishes. A single
generator cannot be driven from both. The router thread pushes into a queue, the
generator drains it, and the UI sees a fallback the moment it happens instead of
several seconds later when the node returns.
"""

from __future__ import annotations

import queue
import threading
import uuid
from typing import Any, Iterator, Optional

from ..integrations.router import ModelRouter
from ..memory.profile_store import ProfileStore
from ..state import MAX_REVISIONS, ModelCall, new_state
from ..workflow.langgraph_flow import (
    AGENT_LABELS,
    AGENT_SEQUENCE,
    build_graph,
    merge_update,
    stream_graph,
)

# Which state key each node fills. The UI expands a rail node to show this.
NODE_OUTPUT_KEY = {
    "input_parser": "parsed",
    "intent_detection": "intent",
    "tone_stylist": "tone_spec",
    "personalization": "profile",
    "draft_writer": "draft",
    "review": "review",
    "router": "status",
}

_SENTINEL = object()


def agent_catalog() -> list[dict[str, str]]:
    """The pipeline as the UI should draw it, left to right."""
    return [{"id": node, "label": AGENT_LABELS[node]} for node in AGENT_SEQUENCE]


def _next_node(node: str, state: dict[str, Any]) -> Optional[str]:
    """Which node runs after `node`, mirroring the graph's own edges.

    Kept in sync with route_after_review by hand rather than importing it,
    because this must answer for every node, not just the branching one.
    """
    if state.get("status") == "failed":
        return "router" if node != "router" else None

    if node == "review":
        review = state.get("review") or {}
        if not review.get("passed") and int(state.get("attempts") or 0) <= MAX_REVISIONS:
            return "draft_writer"
        return "router"

    try:
        index = AGENT_SEQUENCE.index(node)
    except ValueError:
        return None
    return AGENT_SEQUENCE[index + 1] if index + 1 < len(AGENT_SEQUENCE) else None


def generate_events(
    *,
    prompt: str,
    tone: Optional[str],
    intent: str,
    recipient: Optional[str],
    length: str,
    user_id: str,
    routing_profile: Optional[str],
    store: Optional[ProfileStore] = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield (event_name, payload) pairs for one generation run."""
    store = store or ProfileStore()
    session_id = uuid.uuid4().hex[:12]

    calls: "queue.Queue[Any]" = queue.Queue()

    def on_call(call: ModelCall) -> None:
        calls.put(call)

    router = ModelRouter(profile=routing_profile, on_call=on_call)
    graph = build_graph(router, store)

    state = new_state(
        raw_prompt=prompt,
        user_id=user_id,
        session_id=session_id,
        requested_tone=tone,
        requested_intent=intent,
        recipient=recipient,
        length_hint=length,
        routing_profile=router.profile,
    )

    yield "run_start", {
        "session_id": session_id,
        "routing_profile": router.profile,
        "agents": agent_catalog(),
        "max_revisions": MAX_REVISIONS,
    }
    yield "agent_start", {
        "node": AGENT_SEQUENCE[0],
        "label": AGENT_LABELS[AGENT_SEQUENCE[0]],
    }

    final: dict[str, Any] = dict(state)
    events: "queue.Queue[Any]" = queue.Queue()

    def drive() -> None:
        """Run the graph on a worker thread, pushing normalized events."""
        try:
            for event in stream_graph(graph, state, thread_id=session_id):
                events.put(event)
        except Exception as exc:  # noqa: BLE001 - reported to the client, not swallowed
            events.put({"kind": "fatal", "message": str(exc)})
        finally:
            events.put(_SENTINEL)

    worker = threading.Thread(target=drive, name=f"graph-{session_id}", daemon=True)
    worker.start()

    started: set[str] = {AGENT_SEQUENCE[0]}
    fatal: Optional[str] = None

    while True:
        item = events.get()

        # Drain the model calls that landed while this node was running, so the
        # rail can show a fallback before the node itself reports back.
        while True:
            try:
                call = calls.get_nowait()
            except queue.Empty:
                break
            yield "model_call", call.model_dump()

        if item is _SENTINEL:
            break

        kind = item.get("kind")
        if kind == "status":
            yield "agent_status", {"message": item["message"]}
        elif kind == "fatal":
            fatal = item["message"]
        elif kind == "node":
            node = item["node"]
            update = item["update"] or {}
            merge_update(final, update)

            output_key = NODE_OUTPUT_KEY.get(node)
            yield "agent_done", {
                "node": node,
                "label": AGENT_LABELS.get(node, node),
                "output": final.get(output_key) if output_key else None,
                "revision": node == "draft_writer" and int(final.get("attempts") or 0) > 1,
            }

            # Announce the *next* node, not this one. LangGraph's "updates"
            # stream only reports a node after it finishes, so an agent_start
            # emitted here would always arrive paired with its own agent_done
            # and the rail would never show anything as running.
            nxt = _next_node(node, final)
            if nxt is not None:
                started.add(nxt)
                yield "agent_start", {"node": nxt, "label": AGENT_LABELS.get(nxt, nxt)}

            if node == "draft_writer" and final.get("draft"):
                # Push the draft the moment it exists. The review pass takes
                # seconds, and there is no reason to make the user wait to read.
                yield "draft", {"draft": final["draft"], "attempts": final.get("attempts", 1)}
            elif node == "review" and final.get("review"):
                review = final["review"]
                if not review.get("passed") and int(final.get("attempts") or 0) <= MAX_REVISIONS:
                    yield "revision", {
                        "attempt": final.get("attempts"),
                        "reason": review.get("fix_instructions", ""),
                        "issues": review.get("issues", []),
                    }

    worker.join(timeout=1.0)

    # Anything the router logged after the last node reported.
    while True:
        try:
            yield "model_call", calls.get_nowait().model_dump()
        except queue.Empty:
            break

    if fatal:
        yield "error", {"message": fatal}
        yield "done", {"status": "failed", "errors": [fatal], "trace": final.get("trace", [])}
        return

    yield "done", {
        "session_id": session_id,
        "draft_id": final.get("draft_id") or session_id,
        "status": final.get("status", "failed"),
        "draft": final.get("draft"),
        "review": final.get("review"),
        "parsed": final.get("parsed"),
        "intent": final.get("intent"),
        "tone_spec": final.get("tone_spec"),
        "attempts": final.get("attempts", 0),
        "errors": final.get("errors", []),
        "trace": final.get("trace", []),
        "signature": (final.get("profile") or {}).get("signature", ""),
    }
