# citation-gate

A Claude Code plugin that **catches fabricated bibliographic citations before you deliver them**.

Large models reliably hallucinate citation metadata — they keep a real paper title but invent the authors, venue, year, and pages. `citation-gate` adds a **Stop hook** that, each time Claude Code finishes a turn, scans the `.tex` / `.bib` / `.md` files changed in that session, reverse-looks-up each citation against **DBLP → Semantic Scholar → CrossRef → OpenAlex**, compares the first author / year / venue against the authoritative record, and **blocks delivery (forcing a rework)** when a citation's metadata is fabricated.

## Install

```
/plugin marketplace add atominfinite/claude-plugins
/plugin install citation-gate@atominfinite
```

> Replace `atominfinite/claude-plugins` with the GitHub repo that hosts this marketplace.

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
