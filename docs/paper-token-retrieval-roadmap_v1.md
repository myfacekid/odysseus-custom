# Paper Token Retrieval Roadmap

**Surgical paper context without context-window blowout.**

**Status:** Active direction — **Projects Phase D/E prerequisites met** on `feature/projects`. **R0–R3 not implemented**; tier model describes target behavior. **v1.1 audited against `src/` (2026-06-08).**

**Last updated:** 2026-06-08

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
| **`compare_papers` tool** | — | Entire R3 deliverable |
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

**Today:** Multiple `search_knowledge` reads with default PDF extraction, or `trigger_research` for a full DR job. No `compare_papers`.

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

### Phase R0 — Retrieval discipline (prompt + defaults + PDF floor fix)

**Prerequisite:** Projects Phase D ✅ (shipped).

**Goal:** Make Tier 1 the default path; Tier 3 requires explicit opt-in.

| Item | Status today | R0 work |
|------|--------------|---------|
| **Agent prompt block** | PDF extraction encouraged on every paper read | Tiered rules: search → abstract (`include_pdf=false`) → section (R1) → full PDF only when needed |
| **`read_knowledge_content` PDF floor** | `pdf_budget = min(max(max_chars, 12000), 50000)` forces large PDF pulls | Respect `max_chars` for PDF portion; separate metadata budget from PDF budget |
| **`search_knowledge` read defaults** | `max_chars=8000`, `include_pdf=true` (`execute_knowledge_tool`) | Default `include_pdf=false` for `paper:`; document in tool schema; agent overrides for full text |
| **`search_zotero` defaults** | `include_pdf=true` for all calls (`execute_search_zotero_tool`) | `false` for broad search/list; `true` only with `zotero_key` or explicit flag |
| **Tool schema + agent examples** | Example `max_chars: 20000` for papers | Examples show abstract-first read; full PDF as second step |
| **Deep Research seed reads** | `node_to_finding(..., include_pdf=True, content_max_chars=15000)` | Abstract-only for initial seed scan; PDF only for promoted sources (separate change in `research_knowledge.py`) |
| **General chat Zotero preface** | `extract_pdfs=True` in `search_zotero_for_chat` | Metadata/snippet only unless query targets one paper |
| **Project preamble** | Snippets only — already safe | Optional: sort paper links; no change required for R0 minimum |
| **Server policy cap** | 50k char hard max on read | Optional lower policy cap (e.g. 25k) with chunked read message |

**Deliverable:** Reading one linked paper via default tool args returns abstract + metadata, not 12k+ PDF chars. Agent prompt matches server defaults.

**Key files:** `src/knowledge_graph.py` (`read_knowledge_content`, `execute_knowledge_tool`), `src/zotero_client.py` (`execute_search_zotero_tool`, `search_zotero_for_chat`), `src/tool_schemas.py`, `src/agent_loop.py`, `src/research_knowledge.py` (DR seed policy).

---

### Phase R1 — Section-aware extraction (**net-new**)

**Prerequisite:** R0 discipline in place.

| Item | Status today | R1 work |
|------|--------------|---------|
| **Section parsing** | Full PDF text only | PDF text → section boundaries (regex + heading heuristics) |
| **Section API** | No `section` param | `search_zotero` and/or `search_knowledge` read accept `section="methods"` |
| **Section cache** | Zotero catalog is **JSON** under `data/zotero/users/{owner}/` — metadata only, no PDF sections | Store section boundaries in catalog rows or sidecar file on first parse |
| **Fallback** | N/A | No clear sections → Tier 1 abstract; user insist → Tier 3 full text |

**Deliverable:** Agent can pull a single section from a paper without loading the entire PDF into the context window.

**Key files:** `src/zotero_client.py` (`fetch_paper_pdf_text`, PDF extract path), `src/zotero_catalog.py`, `src/knowledge_graph.py` (read path), `src/tool_schemas.py`.

**Note:** `src/goal_based_extractor.py` extracts relevance from **web pages** for Deep Research — not PDF section boundaries. Do not confuse with R1.

---

### Phase R2 — Deep Research summary notes (**net-new**)

**Prerequisite:** R0 (R1 optional but helps). Projects Phase E research linking ✅.

| Item | Status today | R2 work |
|------|--------------|---------|
| **Auto-summary on research** | DR saves session JSON + report; graph gets `research:{id}` node | Structured summary as `document` or `note` node linked to `paper:{key}` |
| **Summary edges** | Only `related` from research sessions (`src/research_graph.py`) | `paper → note` with kind **`summarizes`** (add to graph kinds — see edge taxonomy doc) |
| **Staleness** | — | `generated_at` on summary; re-summarize on request |
| **Manual override** | User can re-run DR | "Re-summarize Chen 2025 focusing on limitations" → new note or replace |

**Deliverable:** Cross-comparison on previously researched papers reads ~300-token summary notes instead of re-extracting PDFs.

**Key files:** `src/research_handler.py` (completion hook), `src/research_graph.py`, `src/knowledge_graph.py` (new kind + node upsert), optional vault/doc store.

---

### Phase R3 — Multi-paper comparison tool (**net-new**)

**Prerequisite:** R1 (section extract) + R2 (summaries help but optional for ≤3 papers).

| Item | Status today | R3 work |
|------|--------------|---------|
| **`compare_papers` tool** | **Not in codebase** — use `trigger_research` or manual reads today | New agent tool: `compare_papers(paper_keys=[...], focus="methods")` |
| **Output shape** | — | Side-by-side section extract; optional mapping to edge taxonomy labels ("Builds on" → `derives_from`, etc.) |
| **Diff highlighting** | — | Flag contradictions / incompatible assumptions |
| **Deep Research routing** | `trigger_research` for large jobs | >3 papers → async DR compare session |

**Deliverable:** One agent call produces structured comparison at section-level token cost.

**Key files:** New tool in `src/tool_schemas.py` + implementation module; reuses R1 section extract + R2 summaries when present.

**Interim (before R3):** Agent loops `search_knowledge` read with `include_pdf=false` then explicit section/full reads — works but burns turns and relies on R0 discipline.

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
| R3 | Side-by-side methods comparison across 3 papers; >3 papers routes to DR; **`compare_papers` not tested until tool exists** |

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
| 2026-06-08 | **v1.1:** Capability baseline audit vs `src/`; Phase D/E prerequisites marked met; document today vs target tiers; R0 adds PDF floor fix + real default gaps; R1 catalog storage corrected (JSON not SQLite); R2/R3 marked net-new; token budget table split today/target; cross-link edge taxonomy doc; open questions 6–7. |
