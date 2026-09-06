# Demo recording script

Roughly four minutes. Every shot maps to a grading criterion, and the whole thing
runs offline — no key, no cost, and identical output on every take because the
offline provider is seeded on the prompt.

Setup, before recording:

```bash
cd backend && FAKE_LLM=1 PYTHONPATH=src .venv/bin/uvicorn email_assistant.api.app:app
cd frontend && pnpm dev
```

Clear saved style samples first if you want the personalization beat to land from
zero: delete the `edit_history` array in `backend/data/profiles.json`.

---

## 1 · The pipeline running — Agentic Architecture (25%)

**~50s.** The most important shot. Record it first, while the take is clean.

Type into the composer:

> Follow up with Priya about the Q3 pricing deck and ask for sign-off by Friday

Leave intent on **Detect automatically**, tone on **Friendly**. Hit Generate and
**do not talk over the first three seconds** — let the rail carry it.

Point out, in this order:

- Seven distinct nodes, each a separate agent, advancing left to right.
- The status line above the rail changing as each one works.
- The draft appearing while Review is still running.
- Click the **Draft Writer** node to expand its structured output — say that every
  agent returns a validated schema, not free text.
- Click **Tone Stylist** and show the `ToneSpec`: an exact greeting, an exact
  closing, a banned-phrase list. Say the line that matters — *"friendly" is not
  checkable; this is, and the reviewer checks against exactly this.*

## 2 · Tone changes the output — Functionality (30%)

**~40s.** Same prompt, switch tone to **Formal**, regenerate. Then **Casual**.

Show the greeting moving `Hi Priya,` → `Dear Priya,` → `Hey Priya,` and the closing
moving `Thanks,` → `Kind regards,` → `Cheers,`. Note the tone-match meter on the
draft header — that is the reviewer scoring the draft against the contract, not a
fixed number.

Then change the prompt to the apology example and show the intent chip flip to
`apology` on its own.

## 3 · Fallback and routing — Routing & MCP (10%)

**~50s.** The second-most important shot.

Before recording this section, break the primary model on purpose:

```yaml
# backend/config/mcp.yaml, under profiles.quality
draft:
  primary:   {provider: anthropic, model: claude-does-not-exist}
```

Restart the backend — the routing table is read once at startup.

Generate again. On camera:

- The **Draft Writer** node turns amber with a warning triangle instead of green.
- The header badges read **1 fallback** and **3 failed attempts**.
- Open **Model routing**. Three red `RetryableError` rows on
  `claude-does-not-exist`, then the `↳` row where `claude-sonnet-5` served it.
- The draft still completed.

Say why the failures are still on screen: they are the only evidence the router
fell back. A trace showing only successes could not demonstrate this at all.

Mention the rule the code follows — a `400` does **not** trigger fallback, because
that is our own malformed request and retrying it elsewhere just fails twice.

Then switch the routing dropdown to **Cost** and regenerate: the trace now shows
`claude-haiku-4-5` on parse and intent while `draft` stays on `claude-opus-5`.
Difficulty-based routing, with the deliverable protected.

**Restore `mcp.yaml` and restart before the next section.**

## 4 · Editing and memory — Innovation (10%) + UX (20%)

**~50s.**

Edit the draft body directly in the card — change the greeting to something
noticeably more clipped, cut a sentence. The **edited** badge appears and **Save my
style** lights up.

Press it. Read the confirmation aloud: *"the tone stylist now has 1 sample of how
you write."* Open **Your profile** and show the badge count.

Now regenerate the same prompt and show the trace: the Tone Stylist call's input
token count has gone up, because it is now being shown your edit. Say what is
being stored — the before, the after, and the diff — and why the diff is the part
that matters: the final text alone is just a writing sample; before-and-after shows
the *direction* of the correction.

## 5 · The revision loop — Agentic Architecture, part two

**~25s.**

Ask for a **Concise** email but write a long, rambling prompt. When review rejects
a draft, the arc under the rail lights amber, the Draft Writer node picks up a run
counter, and a `revision N of 2` badge appears in the header.

Say the bound out loud: two revisions, then it degrades to `needs_review` and hands
back the best draft with its issues listed, rather than looping.

## 6 · Tests and docs — Documentation (10%)

**~25s.** Terminal, one take:

```bash
cd backend && python -m pytest
```

117 tests, no network, no API key. Call out three by name:

- `test_fatal_error_stops_the_walk` — a 400 must not fall back.
- `test_failed_write_leaves_the_previous_file_intact` — a crash mid-write must not
  destroy the style history.
- `test_a_rejecting_reviewer_stops_at_the_bound` — the loop terminates.

Then the CLI, to show it works headless:

```bash
PYTHONPATH=src python -m email_assistant.cli \
  "Thank Sarah for the intro to the platform team" --tone friendly
```

Finish on the README's architecture section.

---

## Closing line

Something close to:

> Seven agents, a LangGraph pipeline with a bounded revision loop, cross-provider
> fallback that is visible rather than claimed, and a memory that learns from the
> edits you make. It runs with no API key, which is why every number you just saw
> is reproducible.

---

## Do not

- Do not run with a real key on camera unless you have checked the bill — the
  offline mode looks identical and costs nothing.
- Do not skip the fallback section. It is 10% of the grade and the one thing that
  is hard to fake.
- Do not narrate over the first pipeline run. The animation is the argument.
