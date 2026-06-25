# AtomInfinite Claude Code Plugins

A small [Claude Code](https://docs.claude.com/en/docs/claude-code) plugin marketplace.

## Plugins

### `citation-gate` — catch fabricated citations before delivery

When writing papers, LLMs reliably hallucinate citation metadata — keeping a real
paper *title* but inventing the authors, venue, year, and pages. `citation-gate`
adds a **Stop hook** that, before each delivery, scans the `.tex/.bib/.md` files you
changed, reverse-looks-up every citation against **DBLP → Semantic Scholar → CrossRef
→ OpenAlex**, compares the first author / year / venue against the authoritative
record, and **blocks delivery (forcing a rework)** when a citation's metadata is
fabricated.

- **Confidence-gated** — only flags a hard failure when it high-confidence matched the
  *same* paper (title overlap ≥ 0.85), so it won't block correct citations.
- **Fails open** — any error / offline / timeout passes; at most 3 block rounds, then
  it lets you through. It can never deadlock you.
- **Zero Python dependencies** — needs only `python3` (standard library only).

→ Full docs: [`plugins/citation-gate/README.md`](plugins/citation-gate/README.md)

## Install

```
/plugin marketplace add Lauorie/claude-plugins
/plugin install citation-gate@atominfinite
```

## Requirements

- `python3` (3.8+) on `PATH` — no `pip install` needed.
- Node (ships with Claude Code).
- Network access to the four public scholarly APIs (only citation strings are sent;
  no other file content and no secrets leave your machine).

## Overrides

- Skip one file: put `<!-- citation-gate: skip -->` at the top of it.
- Disable for a session: `export CITATION_GATE=off`.
