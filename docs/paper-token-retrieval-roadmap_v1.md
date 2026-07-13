# Paper Token Retrieval Roadmap

**Surgical paper context without context-window blowout.**

**Status:** **Phase R0–R3 shipped** on `feature/projects` (2026-06-01). R3 adds `compare_papers`.

**Last updated:** 2026-06-01

**Related docs:**

| Doc | Relationship |
|-----|----------------|
| [`projects-roadmap.md`](projects-roadmap.md) | Phase D (project chat + preamble) and Phase E (research → project linking) **shipped** — this work is the next layer on top. |
| [`knowledge-graph-edge-taxonomy-roadmap_v3.md`](knowledge-graph-edge-taxonomy-roadmap_v3.md) | T3 typed edges (`summarizes`, comparison labels) **depend on R2/R3 here** — not built in either doc yet. |

---

## Problem

Papers are 5k–20k tokens each. Pulling 3–4 full PDFs into context can consume a quarter of the window before the model does any useful reasoning. Meanwhile, the researcher's actual need is often narrow:

> *"Compare the optimization procedures in Smith 2024 vs Chen 2025 — what assumptions differ?"*

The Projects roadmap's **breadth boundary** gives the model tools to traverse linked papers on demand, but without retrieval discipline those tools become a footgun. This roadmap defines **how** the agent retrieves paper content surgically — so cross-comparison stays cheap and precise.

---

## Relationship to Projects roadmap

| Projects concern | This doc's concern |
|------------------|-------------------|
| **Graph linking** (breadth boundary): which papers are connected to a project? | **How much** paper content the agent retrieves per query, and **how** it targets specific sections. |
| Phase D: project chat, tool policy, context injection | Prompt + server defaults so `search_knowledge` / `search_zotero` don't front-load PDFs |
| Phase E: research → project linking (E1 done; bulk Zotero import skipped) | R2 summaries + R3 comparison tooling on linked papers |

**Prerequisite (met):** Projects Phase D — project chat, two-boundary tool policy, linked-knowledge preamble (`src/project_context.py`). Phase E research→project linking is also shipped; bulk collection import was **skipped** intentionally (would flood preamble).

**Safe to start R0** once this branch merges — no need to wait on further Projects phases.

---

## North star

> **The model retrieves exactly the paper content needed for the question — abstract, section, or full text — with defaults that favor the cheapest sufficient tier.**

A researcher asking "compare methods across these three papers" should never burn 60k tokens on PDF dumps. The system should route through the right retrieval tier automatically.

---

## Nobody capability baseline (2026-06 audit)

| Area | Shipped today | Not built yet |
|------|---------------|---------------|
| **Project preamble** | Link titles, kinds, graph snippets only — **no PDF bodies** (`build_linked_knowledge_block`, 24 links / 4k chars) | Paper-specific token budget; abstract-only injection for top N papers |
| **Tier 0 (snippet)** | `search_knowledge` search hits; paper node snippets (~120 char abstract clip in graph index) | Deliberate "scan only" agent workflow |
| **Tier 1 (abstract)** | `read_knowledge_content` with `include_pdf=false` returns metadata + full abstract from Zotero catalog | **Not the default** — see gaps below |
| **Tier 2 (section)** | — | Section parsing, `section` param, section cache |
| **Tier 3 (full PDF)** | `fetch_paper_pdf_text()` + `include_pdf=true` on read/search | Tiered opt-in defaults; section-limited extract |
| **`compare_papers` tool** | **`compare_papers` agent tool** — sync for ≤3 papers; >3 auto-starts DR compare | Shipped R3 |
| **`summarizes` edges** | — | R2 note nodes + graph kind (see edge taxonomy doc) |
| **Deep Research on papers** | Seed/neighbor papers read with **`include_pdf=true`**, up to **15k chars** per paper (`src/research_knowledge.py`) | Abstract-first seeding; cached summary notes |
| **General chat + Zotero toggle** | `search_zotero_for_chat` uses **`extract_pdfs=True`** | Snippet/abstract-first preface injection |
| **Agent prompts** | Instruct agent to **read PDFs** via `search_knowledge` read on `paper:` ids (`src/agent_loop.py`) | Tiered-retrieval discipline block |
| **Hard caps** | `read_knowledge_content` clamps `max_chars` to 500–**50,000**; PDF truncated at requested budget | Separate abstract vs PDF budgets; lower default ceiling (~25k policy cap) |

### Critical gaps today (why R0 matters)

1. **`include_pdf` defaults to `true`** on `search_knowledge` read, `search_zotero`, and Deep Research paper findings — opposite of tiered "abstract first."
2. **PDF floor bug:** In `read_knowledge_content` for papers, `pdf_budget = min(max(max_chars, 12000), 50000)` — even a low `max_chars` intent still pulls **≥12k chars of PDF** when `include_pdf=true`.
3. **Agent examples encourage full reads:** Tool docs show `max_chars: 20000` for paper read; system prompt says PDF extraction is automatic and expected.
4. **Preamble is already safe** — the footgun is **on-demand tool reads**, not project context injection.

**Phase dependency chain:** **R0** (discipline + fix PDF floor) → **R1** (sections) → **R2** (summary notes + `summarizes`) → **R3** (`compare_papers`). Edge taxonomy T3 items that need `summarizes` / compare output wait on **R2/R3**.

---

## Tiered retrieval model

*Target behavior after R0–R3. "Today" column reflects shipped code.*

### Tier 0 — Snippet (essentially free)

| Property | Target | Today |
|----------|--------|-------|
| Source | Knowledge graph search hit or Zotero metadata | ✅ `search_knowledge` search; catalog search rows |
| Content | Title, authors, abstract snippet (< 200 chars) | ✅ Graph `_snippet(abstract, 120)` on paper nodes |
| Token cost | ~50–100 tokens per paper | ~same when using search hits only |
| Use case | "Which of my linked papers discusses reinforcement learning?" | Works if agent stops at search — **not enforced** |

### Tier 1 — Abstract + metadata

| Property | Target | Today |
|----------|--------|-------|
| Source | `search_knowledge` read **`include_pdf=false`** or `search_zotero` **`include_pdf=false`** | ✅ Data exists in catalog; ⚠️ not default |
| Content | Full abstract, publication metadata, key terms | ✅ `read_knowledge_content` paper branch |
| Token cost | ~200–500 tokens per paper | ~same when PDF skipped |
| Default `max_chars` (R0 target) | ~1500–3000 | **8000** on tool read; preamble uses snippets not abstracts |

### Tier 2 — Section extraction

| Property | Target | Today |
|----------|--------|-------|
| Source | PDF full-text with section-level search | ❌ Full PDF or nothing |
| Content | Single targeted section (Methods, Results, Discussion) | ❌ |
| Token cost | ~500–2000 tokens per section per paper | N/A |
| Use case | "Extract the optimization procedure from Smith 2024 Methods section." | Agent must read large PDF chunk or use Deep Research |

### Tier 3 — Full text

| Property | Target | Today |
|----------|--------|-------|
| Source | Explicit `include_pdf=true` + high `max_chars` | ✅ Always on by default |
| Content | Full PDF extraction (truncated) | ✅ `fetch_paper_pdf_text`, min 12k char PDF budget |
| Token cost | 5k–20k tokens per paper | **Default path today** |
| Use case | Deep analysis when user explicitly asks | Matches current agent prompt |

---

## Retrieval strategies by use case

*Target agent workflows after R0+. Today the agent often jumps to Tier 3 on first `read`.*

### "Compare methods across papers"

1. **Identify candidates** — Tier 0/1 across linked papers to find relevant ones.
2. **Extract sections** — Tier 2 on Methods for each candidate (R1).
3. **Synthesize** — Model works with 2k–6k tokens total, not 60k.
4. **Optional: Deep Research** — Offload full systematic comparison to a research session; link result to project.

**Today:** `compare_papers` with `paper_keys` + `focus=methods` (≤3 sync; >3 → DR compare). Fallback: multiple `search_knowledge` reads with `section=methods`.

### "Compare philosophies / theoretical frameworks"

Same pattern, but target Introduction + Discussion sections instead of Methods.

### "Check a specific claim against our results"

1. **Tier 1** — Confirm which paper makes the claim.
2. **Tier 2** — Extract the specific section making the claim.
3. **Cross-reference** — Model compares extracted claim to project's own outputs (run results, cwd files, linked notes).
4. **Tier 3 only if disputed** — Pull full text if the section alone is ambiguous.

### "What does my library say about X?"

1. **Tier 0 scan** — Broad `search_zotero` or `search_knowledge` across the library.
2. **Tier 1 filter** — Read abstracts for the top N hits (`include_pdf=false`).
3. **Stop** — Return a summary of which papers are relevant and why. Let the researcher decide which to dive into.

**Today:** General chat Zotero preface (`search_zotero_for_chat`) may include PDF excerpts (`extract_pdfs=True`).

---

## Implementation phases

### Phase R0 — Retrieval discipline (prompt + defaults + PDF floor fix) ✅

**Prerequisite:** Projects Phase D ✅ (shipped).

**Goal:** Make Tier 1 the default path; Tier 3 requires explicit opt-in.

**Shipped (2026-06-08):**

| Item | Implementation |
|------|----------------|
| **Constants** | `src/paper_retrieval.py` — `PAPER_READ_DEFAULT_MAX_CHARS=3000`, `PAPER_PDF_MAX_CHARS=25000` |
| **PDF floor fix** | `read_knowledge_content` — no 12k minimum; PDF budget respects `max_chars` capped at 25k |
| **`search_knowledge` read** | Paper nodes default `include_pdf=false`, `max_chars=3000` |
| **`search_zotero`** | `include_pdf` defaults false for broad search; true when `zotero_key` set |
| **Agent + tool schema** | Tiered examples in `src/agent_loop.py`, `src/tool_schemas.py`, `src/tool_index.py` |
| **DR graph channel** | `node_to_finding` default `include_pdf=false`; broad Zotero DR search `extract_pdfs=false` |
| **User seed papers in DR** | Still `extract_pdfs=true` — explicit user-selected seeds |
| **General chat Zotero** | `search_zotero_for_chat` — metadata only unless query resolves to one key |
| **API** | `GET /api/knowledge/content` — paper-aware defaults + `include_pdf` query param |

**Tests:** `tests/test_paper_retrieval.py`

**Key files:** `src/paper_retrieval.py`, `src/knowledge_graph.py`, `src/zotero_client.py`, `src/research_knowledge.py`, `src/research_zotero.py`, `src/deep_research.py`, `routes/knowledge_routes.py`

---

### Phase R1 — Section-aware extraction ✅

**Prerequisite:** R0 discipline in place ✅.

**Goal:** Agent can pull a single section from a paper without loading the entire PDF.

**Shipped (2026-06-08):**

| Item | Implementation |
|------|----------------|
| **Section parser** | `src/paper_sections.py` — heading heuristics + alias map (methods, introduction, results, discussion, limitations) |
| **`search_knowledge` read** | `section` param on paper nodes — Tier 2 extract alongside abstract metadata |
| **`search_zotero`** | `section` + `zotero_key` — same section extract path |
| **Section cache** | `data/zotero/users/{owner}/sections/{key}.json` — invalidated on catalog `date_modified` |
| **Fallback** | No headings → error message pointing to abstract (Tier 1) or `include_pdf=true` (Tier 3) |
| **API** | `GET /api/knowledge/content?section=methods` |

**Tests:** `tests/test_paper_sections.py`, section cases in `tests/test_paper_retrieval.py`

**Key files:** `src/paper_sections.py`, `src/zotero_catalog.py` (cache), `src/zotero_client.py` (`fetch_paper_section_text`), `src/knowledge_graph.py`, `src/tool_schemas.py`, `src/agent_loop.py`

---

### Phase R2 — Deep Research summary notes ✅

**Prerequisite:** R0 ✅. Projects Phase E research linking ✅.

**Goal:** Cross-comparison on previously researched papers uses cached summary documents instead of re-reading PDFs.

**Shipped (2026-06-08):**

| Item | Implementation |
|------|----------------|
| **Completion hook** | `link_research_on_complete` → `sync_paper_summaries_on_complete()` |
| **Summary documents** | Library `Document` rows (markdown), owner-scoped, no session required |
| **Structured body** | Claim, method, results, assumptions from evidence registry excerpts |
| **`summarizes` edges** | `paper:{key}` → `document:{id}` via `add_pipeline_edge()` |
| **Staleness / replace** | Re-running DR on same paper updates the same document + edge `generated_at` |
| **Tier 1.5 read** | Default `search_knowledge read` on `paper:` injects cached summary when edge exists |
| **Graph persistence** | `summarizes` in `_PIPELINE_EDGE_KINDS`; manual edge load/save preserves pipeline metadata |

**Tests:** `tests/test_paper_summaries.py`

**Key files:** `src/paper_summaries.py`, `src/research_graph.py`, `src/knowledge_graph.py` (`add_pipeline_edge`, read injection)

**Manual re-summarize:** Start a new Deep Research job with the same seed papers — summaries refresh in place. Agent-driven “re-summarize focusing on X” can follow in R3 or edge-taxonomy work (LLM pass over report).

---

### Phase R3 — Multi-paper comparison tool (**shipped**)

**Prerequisite:** R1 (section extract) + R2 (summaries help but optional for ≤3 papers).

| Item | Status today | R3 work |
|------|--------------|---------|
| **`compare_papers` tool** | **`src/paper_compare.py` + agent wiring** | Shipped — `compare_papers(paper_keys=[...], focus="methods")` |
| **Output shape** | Side-by-side section/summary extract + at-a-glance table | Shipped |
| **Diff highlighting** | Heuristic tension notes (method contrasts, directional language) | Shipped v1 |
| **Deep Research routing** | >3 papers → auto `mode=compare` via `/api/research/start` | Shipped |

**Deliverable:** One agent call produces structured comparison at section-level token cost.

**Key files:** `src/paper_compare.py`, `src/tool_schemas.py`, `src/tool_implementations.py` (`do_compare_papers`); reuses R1 section extract + R2 summaries when present.

---

## Security & policy

| Concern | Today | Target (R0+) |
|---------|-------|--------------|
| Agent overrides `max_chars` to dump PDFs | Hard max **50k** chars on read; PDF truncated with `… [PDF truncated]` | Policy cap ~25k + chunked read hint; abstract default reduces accidental dumps |
| Section extraction parses full PDF anyway | Full parse on every PDF read | Parse once, cache sections (R1), serve slice only |
| Summaries contain hallucinations | N/A until R2 | Citation + `generated_at`; verify against original when stakes high |
| Tool bypasses (`read_file` on Zotero storage) | Blocked by project depth boundary ✅ | Unchanged |
| General chat PDF injection | Zotero preface may extract PDFs | R0: snippet/abstract preface only |

---

## Token budget model

*Target policy after R0. "Today" for project preamble is already conservative.*

| Session type | Linked-paper context injection | Per-retrieval default cap |
|--------------|-------------------------------|---------------------------|
| **Project chat (today)** | All linked nodes: title + kind + graph snippet; **≤4000 chars / 24 links** — not full abstracts | Tool read: **8000 chars + PDF (≥12k)** default |
| **Project chat (R0 target)** | Same preamble (snippets) or optional top-5 abstract block ≤2000 tokens | **`include_pdf=false`**, ~3000 chars metadata+abstract |
| **Research session (today)** | — | Seed papers up to **15k chars with PDF** (`research_knowledge`) |
| **Research session (R0 target)** | — | Abstract for seeds; PDF only for promoted sources |
| **General chat (today)** | Zotero search preface may include PDF excerpts | 1500–8000 depending on path |
| **General chat (R0 target)** | Snippet/metadata preface | 1500 chars Tier 1 unless single-paper deep read |

Agent can always request more after R0, but defaults make over-retrieval an explicit choice.

---

## Testing strategy

| Phase | Tests |
|-------|-------|
| R0 | `include_pdf=false` read returns abstract, no PDF body; fixing PDF floor: `max_chars=2000` does not pull 12k PDF; `search_zotero` broad search skips PDF; project preamble still ≤4k chars |
| R1 | Section extraction with/without clear headers; cache hit/miss; fallback to Tier 1 |
| R2 | Summary note created after DR on paper seeds; `summarizes` edge in graph; agent read prefers note over PDF |
| R3 | Side-by-side methods comparison across 3 papers; >3 papers routes to DR; **`tests/test_paper_compare.py`** |

---

## Open questions

| # | Question | Lean |
|---|----------|------|
| 1 | Section extraction: regex heuristics vs. ML-based parser (GROBID, etc.)? | Regex first (R1); GROBID only if precision is unacceptable. |
| 2 | Should summaries be auto-generated on Zotero import or only on demand? | On-demand after first Deep Research pass. Avoid bulk summarization on sync. |
| 3 | How to handle papers behind paywalls where PDF isn't available? | Tier 1 only (abstract); flag "no full text available" in UI — **partially today** via `pdf_note` strings. |
| 4 | `compare_papers` — synchronous tool call or async (returns job ID)? | Async for >3 papers; sync for ≤3. Same pattern as `trigger_research` vs research sessions. |
| 5 | Should tiered retrieval apply outside project sessions? | Yes — R0 must fix global defaults (`search_zotero_for_chat`, DR seeds), not just project chat. |
| 6 | Fix PDF floor in R0 or wait for R1 section cache? | **Fix in R0** — current `max(max_chars, 12000)` undermines any abstract-first prompt. |
| 7 | Store section cache in SQLite? | **No** — extend JSON Zotero catalog under `data/zotero/` (consistent with existing storage). |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-06 | Initial draft: tiered model, retrieval strategies, Phases R0–R3, token budgets, open questions. |
| 2026-06-01 | **R3 shipped:** `compare_papers` tool, side-by-side output, DR routing for >3 papers, `tests/test_paper_compare.py`. |
| 2026-06-08 | **R0 shipped:** `src/paper_retrieval.py`; abstract-first defaults; PDF floor fix; tiered agent/tool guidance; DR graph channel abstract-only; tests in `tests/test_paper_retrieval.py`. |
| 2026-06-08 | **R1 shipped:** `src/paper_sections.py`; `section` param on read/search_zotero; section cache under `data/zotero/users/{owner}/sections/`; tests in `tests/test_paper_sections.py`. |
| 2026-06-08 | **R2 shipped:** `src/paper_summaries.py`; DR completion creates summary documents + `summarizes` edges; cached summary on default paper read; `add_pipeline_edge` in knowledge graph. |
