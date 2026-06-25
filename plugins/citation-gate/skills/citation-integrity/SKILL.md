---
name: citation-integrity
description: Use when writing or editing any document that contains citations or a bibliography (papers, related-work sections, surveys, technical reports) — enforces never writing bibliographic metadata (authors, venue, year, pages) from memory; retrieve and verify each citation before writing it.
---

# Citation Integrity

When writing any long-form document that contains citations:

- **Never write bibliographic metadata (authors, venue/journal, year, volume, pages) from memory.** Models reliably hallucinate these — keeping a real paper *title* but fabricating the authors/venue/year. Before writing a citation's fields, look the work up (DBLP / Semantic Scholar / CrossRef / OpenAlex) and copy the fields from the retrieved record.
- The **title** may come from memory, but **authors / venue / year / pages must come from a lookup**.
- If a work cannot be found in any source, mark it `[unverified]` rather than inventing plausible-looking metadata.
- This plugin's Stop hook verifies citations at delivery time and **blocks** on fabricated metadata (HARD_FAIL). Treat that as a hard gate, not a suggestion — fix flagged citations against the authoritative record it reports.

## Overrides

- Skip the gate for one file: put `<!-- citation-gate: skip -->` at the top of that file.
- Disable the gate for the session: `export CITATION_GATE=off`.

## Run the verifier manually

From the plugin directory (the one containing the `citation_gate/` package):

```
PYTHONPATH=. python3 -m citation_gate --json path/to/paper.md
```

Exit code is non-zero if any citation is a HARD_FAIL.
