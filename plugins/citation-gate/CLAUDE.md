# Citation Integrity Policy

> Copy this into your own `CLAUDE.md` (user- or project-level) so the model
> follows it. The `citation-gate` plugin **enforces** the gate rule at Stop time;
> this policy makes the model get citations right **before** the gate runs, so it
> rarely has to.

## Citation Integrity

When writing anything with references (papers, surveys, related-work sections,
technical reports):

- **Never write bibliography metadata from memory** (authors, venue/conference,
  year, volume/issue, pages). Before filling those fields, verify each entry with
  a lookup tool (DBLP / Semantic Scholar / CrossRef) and fill from the result.
  Mark entries you genuinely cannot find as `[unverified]` — do **not** invent
  plausible-looking metadata.
- A title may come from memory, but **authors / venue / year / pages must come
  from a lookup**.
- Before delivery, every citation passes the citation gate (Stop hook →
  `python3 -m citation_gate`). A **HARD_FAIL** (a field that disagrees with the
  authoritative record) must be fixed before delivering — this is a hard
  constraint, not a suggestion.
- To skip the gate deliberately (e.g. offline, with all citations already
  hand-verified against obscure sources), put `<!-- citation-gate: skip -->` at
  the top of the file or set `CITATION_GATE=off`, and tell the user why.
