"""The LangGraph pipeline.

    START -> input_parser -> intent_detection -> tone_stylist -> personalization
          -> draft_writer -> review -> (revise? back to draft_writer) -> router -> END

Two design points worth stating.

The revision loop is a conditional edge rather than a retry inside the writer.
That keeps the decision to re-write in one readable place, makes the loop bound
enforceable, and means the UI can show the loop firing — a retry buried inside a
node would be invisible to the caller.

Every node is bound to one ModelRouter instance for the whole run, so `trace`
accumulates across the run and a fallback that happens in the tone agent is
visible in the same list as one from the writer.
"""

from __future__ import annotations

import functools
from typing import Any, Callable, Iterator, Optional

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from ..agents.draft_writer_agent import draft_writer_agent
from ..agents.input_parser_agent import input_parser_agent
from ..agents.intent_detection_agent import intent_detection_agent
from ..agents.personalization_agent import personalization_agent
from ..agents.review_agent import review_agent
from ..agents.router_agent import router_agent
from ..agents.tone_stylist_agent import tone_stylist_agent
from ..integrations.base import LLMError
from ..integrations.router import ModelRouter
from ..memory.profile_store import ProfileStore
from ..state import MAX_REVISIONS, EmailState

# The order the UI draws the pipeline rail in.
AGENT_SEQUENCE = [
    "input_parser",
    "intent_detection",
    "tone_stylist",
    "personalization",
    "draft_writer",
    "review",
    "router",
]

AGENT_LABELS = {
    "input_parser": "Input Parser",
    "intent_detection": "Intent Detection",
    "tone_stylist": "Tone Stylist",
    "personalization": "Personalization",
    "draft_writer": "Draft Writer",
    "review": "Review & Validator",
    "router": "Routing & Memory",
}

# Node-level retries cover transient failures the router cannot see, such as a
# node raising while assembling its own prompt. Model-level retries and fallback
# already happened one layer down, so this number is small on purpose: three here
# on top of three there would mean nine calls before anyone hears about it.
_NODE_RETRY = RetryPolicy(max_attempts=2)


def route_after_review(state: EmailState) -> str:
    """Decide whether the draft goes back to the writer or on to the end.

    Returns a node name. The bound on `attempts` is what makes the loop finite:
    without it a reviewer that keeps objecting and a writer that keeps producing
    the same text would spin until LangGraph's recursion limit fired, which
    surfaces as an opaque framework error instead of a usable draft.
    """
    # A failed run has no draft to revise. Without this check the writer is
    # skipped (so `attempts` never increments), the reviewer is skipped, and the
    # loop spins until LangGraph's recursion limit fires.
    if state.get("status") == "failed":
        return "router"

    review = state.get("review") or {}
    attempts = int(state.get("attempts") or 0)

    if review.get("passed"):
        return "router"
    if attempts > MAX_REVISIONS:
        return "router"
    return "draft_writer"


def _guard(name: str, fn: Callable[[EmailState], dict[str, Any]]) -> Callable[[EmailState], dict[str, Any]]:
    """Turn an unrecoverable model failure into a state update, not a traceback,
    and skip the node entirely once the run has already failed.

    By the time an LLMError reaches here, the router has already tried every
    candidate model. Raising would abort the stream and leave the UI with a
    spinner; instead the run ends with status "failed" and a message that names
    the agent that could not complete.

    The skip matters as much as the catch. LangGraph has no global abort, so
    after one node fails the rest of the pipeline would otherwise run on empty
    state — burning tokens on a request that cannot succeed, and letting the
    terminal node overwrite "failed" with "complete".
    """

    @functools.wraps(fn)
    def wrapped(state: EmailState) -> dict[str, Any]:
        if state.get("status") == "failed":
            return {}
        try:
            return fn(state)
        except LLMError as exc:
            return {
                "status": "failed",
                "errors": [f"{AGENT_LABELS.get(name, name)} could not complete: {exc}"],
            }

    return wrapped


def build_graph(
    router: ModelRouter,
    store: Optional[ProfileStore] = None,
    *,
    checkpointer: Optional[Any] = None,
):
    """Compile the pipeline against a specific router and profile store."""
    store = store or ProfileStore()
    builder = StateGraph(EmailState)

    builder.add_node(
        "input_parser",
        _guard("input_parser", functools.partial(input_parser_agent, router=router)),
        retry_policy=_NODE_RETRY,
    )
    builder.add_node(
        "intent_detection",
        _guard("intent_detection", functools.partial(intent_detection_agent, router=router)),
        retry_policy=_NODE_RETRY,
    )
    builder.add_node(
        "tone_stylist",
        _guard("tone_stylist", functools.partial(tone_stylist_agent, router=router)),
        retry_policy=_NODE_RETRY,
    )
    builder.add_node(
        "personalization",
        _guard("personalization", functools.partial(personalization_agent, store=store)),
    )
    builder.add_node(
        "draft_writer",
        _guard("draft_writer", functools.partial(draft_writer_agent, router=router)),
        retry_policy=_NODE_RETRY,
    )
    builder.add_node(
        "review",
        _guard("review", functools.partial(review_agent, router=router)),
        retry_policy=_NODE_RETRY,
    )
    builder.add_node(
        "router",
        _guard("router", functools.partial(router_agent, store=store)),
    )

    builder.add_edge(START, "input_parser")
    builder.add_edge("input_parser", "intent_detection")
    builder.add_edge("intent_detection", "tone_stylist")
    builder.add_edge("tone_stylist", "personalization")
    builder.add_edge("personalization", "draft_writer")
    builder.add_edge("draft_writer", "review")
    builder.add_conditional_edges("review", route_after_review, ["draft_writer", "router"])
    builder.add_edge("router", END)

    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def run_graph(
    graph: Any,
    state: EmailState,
    *,
    thread_id: Optional[str] = None,
) -> EmailState:
    """Run to completion and return the final state."""
    config = {"configurable": {"thread_id": thread_id or state.get("session_id") or "default"}}
    return graph.invoke(state, config)


def stream_graph(
    graph: Any,
    state: EmailState,
    *,
    thread_id: Optional[str] = None,
) -> Iterator[dict[str, Any]]:
    """Yield normalized progress events as the graph runs.

    Emits {"kind": "node", "node": ..., "update": ...} when a node finishes and
    {"kind": "status", "message": ...} for the status lines agents push through
    the custom channel. The API layer maps these onto SSE frames; the CLI prints
    them. Normalizing here keeps LangGraph's chunk shape out of both.
    """
    config = {"configurable": {"thread_id": thread_id or state.get("session_id") or "default"}}

    for chunk in graph.stream(state, config, stream_mode=["updates", "custom"], version="v2"):
        kind = chunk.get("type")
        data = chunk.get("data")

        if kind == "updates" and isinstance(data, dict):
            for node_name, update in data.items():
                yield {"kind": "node", "node": node_name, "update": update or {}}
        elif kind == "custom" and isinstance(data, dict):
            message = data.get("status")
            if message:
                yield {"kind": "status", "message": message}
