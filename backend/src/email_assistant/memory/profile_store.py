"""Durable per-user memory: identity, style, past drafts, and past edits.

A JSON file rather than a database. The whole store is one small document per
user, it is read once per request and written once, and keeping it as a file
means the personalization data is inspectable and diffable — which matters more
here than concurrent-write throughput, since there is one user per process.

Writes go through a temp file and os.replace. A half-written profiles.json would
take the user's accumulated style history with it, and os.replace is atomic on
both Windows and POSIX, so a crash mid-write leaves the previous version intact.
"""

from __future__ import annotations

import difflib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..config import PROFILES_PATH

# Caps exist because these lists feed a prompt. Unbounded history would grow the
# token bill on every request and eventually push out the actual instructions.
MAX_EDIT_HISTORY = 20
MAX_DRAFT_HISTORY = 20
# How many recent edits the tone stylist is shown as evidence of real style.
STYLE_EVIDENCE_COUNT = 3


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_profile(user_id: str) -> dict[str, Any]:
    """A blank but complete profile.

    Returned for unknown users rather than raising, so a first-time request needs
    no setup step before it can produce a draft.
    """
    return {
        "user_id": user_id,
        "name": "",
        "role": "",
        "company": "",
        "signature": "",
        "default_tone": "friendly",
        "tone_examples": [],
        "draft_history": [],
        "edit_history": [],
    }


class ProfileStore:
    """Read/write access to profiles.json."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else PROFILES_PATH

    # --- persistence --------------------------------------------------------

    def _read_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            # A corrupt store must not take the app down. Personalization is an
            # enhancement; losing it degrades draft quality but not the feature.
            return {}
        return raw if isinstance(raw, dict) else {}

    def _write_all(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".profiles-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            # Clean up the temp file on any failure, including KeyboardInterrupt,
            # so a run of aborted writes cannot litter the data directory.
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    # --- profile access -----------------------------------------------------

    def get(self, user_id: str) -> dict[str, Any]:
        """Return a user's profile, or a complete blank one if absent."""
        profile = self._read_all().get(user_id)
        if not isinstance(profile, dict):
            return default_profile(user_id)
        merged = default_profile(user_id)
        merged.update(profile)
        merged["user_id"] = user_id
        return merged

    def list_users(self) -> list[str]:
        return sorted(self._read_all())

    def save(self, user_id: str, updates: dict[str, Any]) -> dict[str, Any]:
        """Merge `updates` into a profile and persist. Returns the merged profile.

        Only known fields are accepted, so a malformed API payload cannot inject
        arbitrary keys that later end up interpolated into a prompt.
        """
        allowed = set(default_profile(user_id))
        data = self._read_all()
        profile = self.get(user_id)
        for key, value in updates.items():
            if key in allowed and key != "user_id":
                profile[key] = value
        data[user_id] = profile
        self._write_all(data)
        return profile

    # --- history ------------------------------------------------------------

    def record_draft(
        self,
        user_id: str,
        *,
        draft_id: str,
        subject: str,
        body: str,
        tone: str,
        intent: str,
    ) -> None:
        """Append a generated draft to the user's history."""
        data = self._read_all()
        profile = self.get(user_id)
        history = list(profile.get("draft_history") or [])
        history.append(
            {
                "draft_id": draft_id,
                "created_at": _utc_now(),
                "subject": subject,
                "body": body,
                "tone": tone,
                "intent": intent,
            }
        )
        profile["draft_history"] = history[-MAX_DRAFT_HISTORY:]
        data[user_id] = profile
        self._write_all(data)

    def record_edit(
        self,
        user_id: str,
        *,
        draft_id: str,
        original_body: str,
        edited_body: str,
        subject: str = "",
    ) -> dict[str, Any]:
        """Record how the user rewrote a draft.

        The diff is what makes this useful later: the tone stylist is shown the
        before and after, so it learns the direction of the correction rather
        than just the final text, which on its own reads as an unrelated sample.
        """
        diff = "\n".join(
            difflib.unified_diff(
                original_body.splitlines(),
                edited_body.splitlines(),
                fromfile="generated",
                tofile="edited",
                lineterm="",
                n=1,
            )
        )
        entry = {
            "draft_id": draft_id,
            "created_at": _utc_now(),
            "subject": subject,
            "original": original_body,
            "edited": edited_body,
            "diff": diff,
        }
        data = self._read_all()
        profile = self.get(user_id)
        history = list(profile.get("edit_history") or [])
        history.append(entry)
        profile["edit_history"] = history[-MAX_EDIT_HISTORY:]
        data[user_id] = profile
        self._write_all(data)
        return entry

    def style_evidence(self, user_id: str, limit: int = STYLE_EVIDENCE_COUNT) -> list[dict[str, str]]:
        """The most recent edits, trimmed for use as few-shot style evidence.

        Unchanged edits are dropped: a user who pressed save without changing
        anything has told us nothing about their style, and feeding identical
        before/after pairs to the stylist just wastes tokens.
        """
        profile = self.get(user_id)
        evidence: list[dict[str, str]] = []
        for entry in reversed(profile.get("edit_history") or []):
            original = (entry.get("original") or "").strip()
            edited = (entry.get("edited") or "").strip()
            if not edited or original == edited:
                continue
            evidence.append({"original": original, "edited": edited})
            if len(evidence) >= limit:
                break
        return list(reversed(evidence))
