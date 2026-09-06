"""Headless driver: generate a draft from the terminal.

Exists for three reasons. It is the fastest way to check a prompt change without
starting two servers; it is what the demo recording uses to show the pipeline
without UI chrome in the way; and it gives the whole stack a smoke test that does
not depend on a browser.

Exit codes: 0 complete, 1 the draft needs review, 2 the run failed.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from typing import Optional, Sequence

from .config import get_routing_config, get_settings
from .integrations.router import ModelRouter
from .memory.profile_store import ProfileStore
from .state import Intent, Tone, new_state
from .workflow.langgraph_flow import AGENT_LABELS, build_graph, merge_update, stream_graph

_STATUS_EXIT = {"complete": 0, "needs_review": 1, "failed": 2}


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="email-assistant",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    result.add_argument("prompt", help="What the email should say, in plain language")
    result.add_argument("--tone", choices=[t.value for t in Tone], default=None)
    result.add_argument(
        "--intent",
        choices=["auto"] + [i.value for i in Intent],
        default="auto",
        help="Skip detection and use this intent",
    )
    result.add_argument("--to", dest="recipient", default=None, help="Recipient name")
    result.add_argument("--length", choices=["short", "medium", "long"], default="medium")
    result.add_argument("--user", default="default", help="Profile to write as")
    result.add_argument("--profile", default=None, help="Routing profile from mcp.yaml")
    result.add_argument("--json", action="store_true", help="Emit the final state as JSON")
    result.add_argument("--quiet", action="store_true", help="Only print the finished draft")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)

    try:
        settings = get_settings()
        routing = get_routing_config()
        profile = args.profile or settings.routing_profile or routing.active_profile
        # Fail on a bad profile name now, rather than after the first agent has
        # already spent a call.
        routing.route("draft", profile)

        router = ModelRouter(profile=profile)
        graph = build_graph(router, ProfileStore())
        session_id = uuid.uuid4().hex[:12]

        state = new_state(
            raw_prompt=args.prompt,
            user_id=args.user,
            session_id=session_id,
            requested_tone=args.tone,
            requested_intent=args.intent,
            recipient=args.recipient,
            length_hint=args.length,
            routing_profile=profile,
        )

        if not args.quiet and not args.json:
            mode = "offline (no API key)" if settings.offline else "live"
            print(f"Routing profile: {profile}  |  Mode: {mode}\n", file=sys.stderr)

        final: dict = dict(state)
        for event in stream_graph(graph, state, thread_id=session_id):
            if event["kind"] == "status":
                if not args.quiet and not args.json:
                    print(f"  · {event['message']}", file=sys.stderr)
            else:
                merge_update(final, event["update"] or {})
                if not args.quiet and not args.json:
                    label = AGENT_LABELS.get(event["node"], event["node"])
                    print(f"✓ {label}", file=sys.stderr)

        if args.json:
            print(json.dumps(final, indent=2, ensure_ascii=False, default=str))
            return _STATUS_EXIT.get(str(final.get("status")), 2)

        _print_result(final, quiet=args.quiet)
        return _STATUS_EXIT.get(str(final.get("status")), 2)

    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _print_result(final: dict, *, quiet: bool) -> None:
    status = str(final.get("status"))
    draft = final.get("draft") or {}

    if not draft:
        for error in final.get("errors") or ["No draft was produced."]:
            print(f"error: {error}", file=sys.stderr)
        return

    if not quiet:
        print()
    print(f"Subject: {draft.get('subject', '')}")
    print()
    print(draft.get("body", ""))
    if signature := (final.get("profile") or {}).get("signature"):
        print(signature)

    if quiet:
        return

    review = final.get("review") or {}
    trace = final.get("trace") or []
    print("\n" + "-" * 60, file=sys.stderr)
    print(
        f"status: {status}  |  tone match: {review.get('tone_match', 0):.0%}  "
        f"|  words: {draft.get('word_count', 0)}  |  passes: {final.get('attempts', 0)}",
        file=sys.stderr,
    )

    for issue in review.get("issues") or []:
        print(f"  [{issue.get('severity')}] {issue.get('category')}: {issue.get('detail')}", file=sys.stderr)

    if trace:
        print("\nmodel calls:", file=sys.stderr)
        for call in trace:
            marker = "!" if call.get("outcome") == "error" else " "
            tag = " (fallback)" if call.get("is_fallback") else ""
            detail = f" {call.get('error_type')}" if call.get("outcome") == "error" else ""
            print(
                f" {marker} {call.get('task'):<7} {call.get('provider')}/{call.get('model')}"
                f"  {call.get('latency_ms')}ms"
                f"  in={call.get('input_tokens')} out={call.get('output_tokens')}{tag}{detail}",
                file=sys.stderr,
            )

    for error in final.get("errors") or []:
        print(f"  ! {error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
