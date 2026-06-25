# citation-gate

A Claude Code plugin that **catches fabricated bibliographic citations before you deliver them**.

Large models reliably hallucinate citation metadata — they keep a real paper title but invent the authors, venue, year, and pages. `citation-gate` adds a **Stop hook** that, each time Claude Code finishes a turn, scans the `.tex` / `.bib` / `.md` files changed in that session, reverse-looks-up each citation against **DBLP → Semantic Scholar → CrossRef → OpenAlex**, compares the first author / year / venue against the authoritative record, and **blocks delivery (forcing a rework)** when a citation's metadata is fabricated.

## Install

```
/plugin marketplace add Lauorie/claude-plugins
/plugin install citation-gate@atominfinite
```

> Replace `Lauorie/claude-plugins` with the GitHub repo that hosts this marketplace.

## Requirements

- **`python3` on PATH** (3.8+). No `pip install` needed — the verifier uses only the Python standard library.
- Node (ships with Claude Code).
- Network access to the four public scholarly APIs (see [Privacy](#privacy)).

## How it works

1. On `Stop`, the hook reads the session transcript and collects the `.tex/.bib/.md` files written/edited this turn.
2. Files with no citation markers are skipped (zero cost).
3. For each citation it runs the bundled `citation_gate` verifier: parse → reverse-lookup (DBLP→SS→CrossRef→OpenAlex, stops at the first source with hits) → compare first-author / year / venue against the authoritative record → grade.
4. **HARD_FAIL** (high-confidence same-paper match, but metadata differs) → the hook emits a `block` decision with the offending citations and their correct records, so Claude reworks them. **SOFT_WARN** (not found, or low-confidence match) → annotated `[unverified]`, not blocking. **SKIP** (network down) → not blocking.

Design choices that keep it usable:

- **Confidence-gated**: a HARD_FAIL requires a title-overlap ≥ 0.85 with the authoritative record, so it distinguishes real fabrication from "matched a different paper" and won't block correct citations.
- **Fails open**: any verifier error / offline / timeout → passes. At most **3** block rounds per session, then it passes with a manual-review note. It can never deadlock you.

## Recommended companion policy

The hook is the **enforcement** (it blocks fabricated metadata at delivery). Pair
it with the matching **behavioral policy** so the model gets citations right
*before* the gate runs and rarely trips it. Copy the `## Citation Integrity`
section from [`CLAUDE.md`](./CLAUDE.md) into your own user- or project-level
`CLAUDE.md`. (A plugin cannot inject a `CLAUDE.md` into your sessions — `CLAUDE.md`
is loaded only from your user/project directories — so this step is manual.)

## Use it from the Claude Agent SDK (Python)

The marketplace install above wires a Stop hook into Claude Code's settings for
the **interactive CLI**. If your users run agents through
**[anthropics/claude-agent-sdk-python](https://github.com/anthropics/claude-agent-sdk-python)**,
register the gate **in code** instead — the bundled `citation_gate.sdk_hook`
provides a ready-made Stop callback (verified against `claude-agent-sdk==0.2.110`):

```python
import sys
sys.path.insert(0, "/path/to/citation-gate")  # dir that contains citation_gate/
from claude_agent_sdk import ClaudeAgentOptions, HookMatcher, query
from citation_gate.sdk_hook import make_stop_hook

options = ClaudeAgentOptions(
    hooks={"Stop": [HookMatcher(hooks=[make_stop_hook(files=["paper.md"])])]},
    # If your app sets setting_sources=[] (common for isolation), the CLI's
    # settings.json hook is NOT loaded — registering here is what guarantees
    # the gate runs under the SDK.
)

async for msg in query(prompt="…write the related-work section…", options=options):
    ...
```

- `files` is a list of citation files, **or** a callable `lambda input_data: [...]`
  that computes the paths at stop time (e.g. from `input_data["cwd"]`).
- On a fabricated citation the callback returns the SDK's documented block
  contract `{"decision": "block", "reason": ...}` so the agent reworks it; a clean
  run returns `{}`. It **fails open** — any verifier/network error returns `{}`
  and never breaks the agent loop. The blocking network lookup runs in a worker
  thread (`asyncio.to_thread`), so it won't stall the event loop.
- Zero extra dependencies — only `python3` stdlib (plus the SDK itself).

> Why register in code: per the current SDK docs, omitting `setting_sources`
> loads `~/.claude/settings.json` (so the CLI hook would also fire), but a
> production SDK app that passes `setting_sources=[]` for hermetic behavior
> would silently skip it. Programmatic registration is bypass-proof.

## Overrides

- **Skip one file**: put `<!-- citation-gate: skip -->` at the top of it.
- **Disable for a session**: `export CITATION_GATE=off`.
- **Politeness email** for CrossRef/OpenAlex (optional): `export CITATION_GATE_MAILTO=you@example.com`.

## Run the verifier manually

```
cd "$(dirname "$(/plugin ...)" )"   # the plugin's directory containing citation_gate/
PYTHONPATH=. python3 -m citation_gate --json paper.md
```

## Privacy

Citation **strings/titles** are sent as search queries to DBLP, Semantic Scholar, CrossRef, and OpenAlex (public scholarly APIs). No other file content leaves your machine, and no secrets are sent.

## Uninstall

```
/plugin uninstall citation-gate@atominfinite
```
