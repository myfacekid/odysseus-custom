# Deep Research Roadmap

Living plan for Deep Research in Odysseus — UI, output, Zotero/Links integration, and session persistence.

**Use this doc for:** panel UX, report/export, graph linking, Library integration.

**Use [`deep-research-ldr-migration.md`](deep-research-ldr-migration.md) for:** backend orchestration and source discovery (LangGraph + LDR).

**Last updated:** 2026-06-01

---

## Doc map

| Doc | Scope | When to use |
|-----|--------|-------------|
| **[`deep-research-ldr-migration.md`](deep-research-ldr-migration.md)** | **Active backend track** — LangGraph agent, LDR search engines, `research_engine` flag | Source discovery, agent tools, Phase L0–L5 |
| **This doc** | Product phases 0–5, UI, output, Zotero/Links polish | Panel, visual report, export, graph edges |
| [`deep-research-retrieval-roadmap.md`](deep-research-retrieval-roadmap.md) | Legacy IterResearch retrieval (RT0–RT6); **policy + partial RT0b/RT3** still apply | Policy rules, iterresearch-only gaps, audit history |

---

## Status

| Track | State |
|-------|--------|
| **Phases 0–3, 5** | ✅ Shipped — evidence registry, seeds/modes, academic templates, Library/Links seed UX, export, typed graph edges |
| **Backend migration** | ✅ **LDR default** — LangGraph gather + Odysseus synthesis ([migration doc](deep-research-ldr-migration.md)); IterResearch fallback when LDR deps missing |
| **Default runtime** | `research_engine=ldr` (auto-fallback to `iterresearch` without `local-deep-research`) |
| **Phase 4 (custom agent loop)** | **Superseded** by LDR LangGraph — see [open decision #5](#open-decisions) |
| **Legacy retrieval RT2/RT4/RT6** | **Not planned on IterResearch path** — LDR handles academic/web source discovery instead ([retrieval roadmap](deep-research-retrieval-roadmap.md#superseded-by-ldr)) |

**Retrieval policy** (no auto-seed, recency on request, etc.) applies to **both** engines via agent prompts + panel toggles — see [retrieval policy](deep-research-retrieval-roadmap.md#retrieval-policy-locked--2026-06).

### Panel toggles (both engines)

See also [LDR migration — panel toggles](deep-research-ldr-migration.md#panel-toggles-preserved).

| Toggle / field | API / setting | LDR behavior (planned L2) |
|----------------|---------------|---------------------------|
| Include preprints | `include_preprints` | Agent prompt + engine filters exclude preprint hosts when off |
| Include Zotero | `include_zotero` | Registers Odysseus `search_zotero` tool only when on; no round-0 catalog dump |
| Include Links / knowledge | `include_knowledge` | Registers `search_knowledge` tool only when on |
| Seed papers | `seed_papers` | Pre-load seeds + compare/gap/similar mode prompts; no auto-seeding |
| Research mode | `mode` | `literature_review` \| `compare` \| `gap_analysis` \| `similar_papers` → agent system context |
| Report length | `report_length` | `standard` \| `extended` → Odysseus synthesis token budget (unchanged) |
| Search provider | `search_provider` | Primary web engine for LDR meta-search / SearXNG bridge |
| Max rounds / time | `max_rounds`, `max_time` | Agent iteration cap + wall-clock timeout |

---

## Current state (baseline)

**Engines (dual):**

| Engine | Setting | Role |
|--------|---------|------|
| **LDR LangGraph** (default) | `research_engine=ldr` | `src/research/ldr_runner.py` → LDR `langgraph-agent` gathers sources; Odysseus synthesizes ([decision B](deep-research-ldr-migration.md#decisions-locked)) |
| **IterResearch** (legacy fallback) | `research_engine=iterresearch` or LDR deps missing | `src/research/iterresearch.py` — Plan → query → search → extract → synthesize loop |

**Integrations today (IterResearch path):**

| Source | How research uses it | Gap vs recent work |
|--------|----------------------|--------------------|
| **Web** | Search provider chain (SearXNG/Brave/etc.) + academic URL ranking | Not the same path as chat `web_search`; no shared query/time-filter behavior |
| **Zotero** | Live API via `fetch_zotero_findings()` (keyword match on query) | Does **not** use local catalog, PDF keys, or `search_knowledge` / Links graph |
| **Links** | Not used | No paper nodes, collections, or `read_knowledge_content` |

**Report pipeline:** Evolving synthesis (last **10 findings only** per round via `synthesis_window`) → final academic template (1200+ words, numbered citations, References). Failures fall back to a raw findings dump (`_fallback_report`).

**UI:** `static/js/research/panel.js` — query box + settings (preprints, Zotero on/off). **No way to attach seed papers** from Library or Links.

**Key files:**

| Area | Path |
|------|------|
| Research engine (legacy) | `src/research/iterresearch.py` (`src/deep_research.py` shim) |
| Research engine (LDR) | `src/research/ldr_runner.py`, `src/research/ldr_llm_adapter.py` |
| Retrieval plan (feeds both) | `src/research_retrieval_plan.py` |
| Handler / persistence | `src/research_handler.py` |
| API routes | `routes/research_routes.py` |
| Visual HTML report | `src/visual_report.py` |
| Panel UI | `static/js/research/panel.js`, `static/js/research/jobs.js` |
| Zotero for research | `src/zotero_client.py` (`fetch_zotero_findings`) |
| Local catalog | `src/zotero_catalog.py` |
| Knowledge graph | `src/knowledge_graph.py` |
| Agent trigger | `src/tool_implementations.py` (`do_trigger_research`) |

---

## Target workflow

```
User provides seed paper(s)
    → Read full text + metadata (Zotero PDF / Links)
    → Extract key claims, methods, gaps
    → Find similar / related work (web + catalog + citation APIs)
    → Synthesize across all evidence
    → Produce a proper academic literature review
```

Three evidence channels with explicit roles, not one blended search loop.

---

## Phase 0 — Audit & fix what’s broken

**Goal:** Trustworthy reports before adding features. **Estimate:** 1–2 weeks.

| Item | Problem | Fix direction |
|------|---------|---------------|
| **Evidence registry** | Citations `[1]`…`[N]` renumbered each synthesis round; References drift | Stable source IDs (`src:web:…`, `src:zotero:KEY`, `src:paper:KEY`); synthesis uses registry, not free-form markdown |
| **Synthesis window** | Only last 10 findings fed to LLM — early Zotero seeds drop out | Tiered context: always include seeds + top-K by relevance; window for new findings only |
| **Fallback report** | Timeout → bullet dump, not academic | Structured fallback using registry + mandatory References from actual sources |
| **Final report validation** | LLM invents stats/citations | Post-pass: every `[N]` must exist in registry; strip uncited References; optional regen pass |
| **Visual report** | HTML can diverge from stored markdown / broken sections | Single canonical `raw_report` + regression tests on sample outputs |

**Deliverable:** Research on 2–3 topics produces consistent citations and a complete References section.

---

## Phase 1 — Unify tool context (web = highest priority)

**Goal:** Research uses the **same tools and semantics** as chat/agents. **Estimate:** 2–3 weeks.

### 1a. Web search (most important)

- Route research search through shared `web_search` / provider layer (time filters, academic query templates, error messages).
- Query types by round:
  - **Discovery:** `"systematic review"`, `"meta-analysis"`, site filters (PubMed, DOI).
  - **Similar papers:** `"cited by"`, title + author, DOI, `"related work"`.
  - **Gap filling:** targeted sub-questions from the plan.
- Track provider + query + result URL in the evidence registry.

### 1b. Zotero (local catalog first)

Replace/supplement live-only `fetch_zotero_findings` with:

1. **`search_catalog()`** — fast browse/search (collections, `has_pdf`).
2. **`fetch_paper_pdf_text()` / `read_knowledge_content(paper:KEY)`** — full PDF text for seeds and matches.
3. Live API as **fallback** when catalog stale or item missing.

### 1c. Links / knowledge graph

- Seed paper → `get_neighbors()` (related docs, tasks, other papers in collection).
- Collection-scoped search: papers in folder X.
- Optional: `search_knowledge` for cross-type links.

**Deliverable:** Internal `ResearchEvidenceGatherer` calling the same backends as `search_zotero`, `search_knowledge`, and `web_search`.

---

## Phase 2 — Seed papers & “find similar” UX

**Goal:** Start from **user literature**, not only a text question. **Estimate:** 2 weeks.

### UI (Deep Research panel)

- **Seed papers** picker: Library Papers section, Links Papers tab, or paste Zotero keys/DOIs.
- Show seed metadata (authors, year, PDF status) before run.
- Modes:
  - **Literature review** — seeds + similar work + synthesis.
  - **Gap analysis** — what seeds don’t cover.
  - **Compare** — 2+ seeds, contrast findings.

### API extension (`ResearchStartRequest`)

```json
{
  "query": "...",
  "seed_papers": ["98XWP3CH", "ABC12345"],
  "mode": "literature_review | similar_papers | gap_analysis"
}
```

### “Similar papers” pipeline

> **LDR path:** When `research_engine=ldr`, similar/related work is discovered by the LangGraph agent via LDR search engines (S2/OpenAlex/PubMed keyword search + relevance filter) — **not** by implementing RT2 on `research_similar_papers.py`. See [`deep-research-ldr-migration.md` Phase L1–L2](deep-research-ldr-migration.md#migration-phases).

**Legacy (IterResearch only)** — superseded if LDR is default:

1. From seed: title, abstract, keywords, DOI, references (if extractable from PDF).
2. Generate **similarity queries** (not generic topic queries):
   - DOI → Crossref/OpenAlex/Semantic Scholar (if connectors added).
   - Title/author variants on web search.
   - Zotero catalog fuzzy match + same collection siblings.
3. Rank candidates: citation overlap, semantic title match, recency, peer-review status.
4. Dedupe against seeds + `_zotero_keys_seen`.

**Deliverable:** “Given these 3 papers, find related work and summarize key findings” works end-to-end — via LDR agent + Odysseus synthesis when migrated.

---

## Phase 3 — Academic report quality

**Goal:** Output suitable for investigative / academic use. **Estimate:** 2–3 weeks.

### Report structure (field-aware templates)

- Default: literature review (Background, Methods overview, Key findings by theme, Conflicting evidence, Gaps, Limitations, Conclusion, References).
- Optional variants: **clinical**, **methods/methodology**, **policy**, **historical**.

### Synthesis upgrades

- Thematic clustering of findings before write-up.
- Evidence tables (study | design | N | outcome | quality) when extractors return structured fields.
- Claim → source mapping in metadata (UI “jump to source”, export to Zotero).
- Separate **Executive summary** (~300 words) vs **full report** (3000+ words option).

### Extraction upgrades

- Zotero PDFs: full PDF text path (same as agents).
- Web PDFs: detect DOI/journal; mark peer-review vs preprint explicitly.
- Pass `study_type`, `sample_size`, `effect_size` into registry — final report must not invent them.

**Deliverable:** Structured review; export Markdown + BibTeX/CSL JSON from registry.

**Remaining (optional Phase 3b — defer until token budget allows testing):**

| Item | Status | Notes |
|------|--------|-------|
| Export Markdown / BibTeX / CSL JSON | Done | `GET /api/research/{id}/export` |
| Thematic clustering + evidence tables | Done | Pre-final context blocks |
| Mode templates (literature / similar / gap / compare) | Done | `research_templates.py` |
| Report length toggle (standard / extended) | Done | Panel + `research_max_tokens` bump |
| Field variants (clinical, policy, historical) | Not started | Lower priority than integration |
| Claim → source UI (“jump to source”) | Done | Visual report sidebar + Library preview citation jumps |
| Separate Executive summary export | Partial | Section in report; no split export |

---

## Phase 5 — Library & Links integration

**Goal:** Make Deep Research feel native to the rest of the app — easy to start from anywhere, easy to trace results back to Library/Links/Zotero. **Estimate:** 1–2 weeks.

This is the **recommended next phase**. Phase 4 (agent tool orchestration) stays deferred; polish and cross-linking deliver more value per complexity than re-architecting the loop.

### 5a. Seed paper UX (panel + Library)

| Task | Detail |
|------|--------|
| **Add from Library** | ✅ Paper card menu → “Use as research seed”. Browse opens inline paper cards in the research panel (not the Documents modal). |
| **Add from Links** | ✅ Papers tab in Links graph: “Use as research seed” on paper detail → seed chip + Papers compose tab. |
| **Paste improvements** | ✅ `paper:KEY`, bare DOI, `doi:` prefix, doi.org links; inline validation hint (no journal-site URLs). |
| **Pre-run seed summary** | ✅ Before Start: catalog sourcing preview (tier, DOI, collection path) via `/api/research/seeds/preview`. |
| **Persist seeds per session** | ✅ `seed_papers` + `seed_paper_details` on completed research JSON. |

**Files:** `static/js/research/panel.js`, `routes/research_routes.py`, optional `static/js/library*.js`, Links graph UI.

### 5b. Completed report → Library & graph

| Task | Detail |
|------|--------|
| **Research record enrichment** | ✅ `session_id`, `source_breakdown`, seeds/mode on JSON; evidence registry persisted. |
| **Library Research tab** | ✅ Mode badge, seed count, source breakdown, seeds list, export + View in Links. |
| **Save sources to Zotero** | ✅ Batch save cited web sources; Library checkboxes + panel/report quick save; skips seeds/library hits; catalog sync after write. `POST /api/research/{id}/save-to-zotero` |
| **Graph linking** | ✅ `research:{session}` node + edges to seed papers and top cited (cap 20). |
| **Open in chat** | ✅ Spinoff includes evidence registry with stable `[N]` citation numbers. |

**Files:** `src/research_handler.py`, `src/knowledge_graph.py`, `static/js/research/library.js` (or panel), `routes/research_routes.py`.

### 5c. Report UI polish

| Task | Detail |
|------|--------|
| **Jump to source** | ✅ Visual report + Library preview: `[N]` scrolls to source card with URL, Zotero key, retrieval tier. |
| **Source panel** | ✅ Right sidebar (mobile: below report) with filters Seeds / Full text / Limited; expandable excerpt. |
| **Export from UI** | ✅ Markdown, BibTeX, CSL JSON in report toolbar + Library preview. |
| **Sourcing disclosure** | ✅ Header chips: full text vs abstract only vs limited retrieval (from registry tiers). |

**Files:** `src/visual_report.py`, `static/js/research/*.js`.

### 5d. Operational hardening (small, ship with Phase 5)

| Task | Detail |
|------|--------|
| **Configurable content limits** | ✅ Settings keys `research_max_content_chars`, `research_synthesis_window` (defaults 15k / 10). |
| **Catalog sync prompt** | ✅ Seed preview compares catalog vs live Zotero PDF; nudges sync when stale. |
| **Regression fixtures** | ✅ Golden compare + gap-analysis JSON fixtures in `tests/fixtures/research/`. |

**Deliverable:** User can start compare mode from Library or Links, run research, open a report with clickable citations and source provenance, export bibliography, and see the session linked in Library + graph.

### Phase 5 acceptance criteria

- [x] Add 2+ papers as seeds from Library or Links without manual key paste.
- [x] Completed research JSON lists seeds, mode, and source-type counts.
- [x] Visual report: click `[N]` → source detail with Zotero key or URL.
- [x] Export Markdown + BibTeX from Library or report view.
- [x] At least one graph edge: `research:SESSION` ↔ seed `paper:KEY` (typed proposals enqueued on complete).

### Suggested implementation order (Phase 5)

```
5a (seed UX from Library/Links)
  → 5b (persist + Library tab + graph links)
  → 5c (report UI: jump-to-source + export buttons)
  → 5d (settings + fixtures, as time allows)
```

### Phase 5 open decisions

| # | Question | Proposed default |
|---|----------|------------------|
| 1 | Auto-add all web sources to Zotero on complete? | **No** — user selects via “Save to library” |
| 2 | Graph node for every source vs seeds + top cited? | **Seeds + top cited** (cap ~20 edges) |
| 3 | Links picker: single or multi seed? | **Multi**, same as panel |

---

## Phase 4 — Agent-shaped research ~~(optional)~~ **superseded**

> **Replaced by** [`deep-research-ldr-migration.md`](deep-research-ldr-migration.md) — LDR `langgraph-agent` with Odysseus custom tools (`search_zotero`, `search_knowledge`, seeds). Do not build a separate Phase 4 orchestrator.

<details>
<summary>Original Phase 4 spec (historical)</summary>

**Goal:** Align with app-wide tool calling. **Estimate:** 3+ weeks.

Research agent with constrained tools:

| Tool | Use in research |
|------|-----------------|
| `search_knowledge` | Seeds, graph neighbors, read `paper:KEY` |
| `search_zotero` | Catalog + PDF |
| `web_search` | Discovery & similar papers |
| `web_fetch` | Specific DOI/PDF URLs |
| Internal `register_evidence` | Add to registry with stable ID |

</details>

---

## Suggested priority order

```
Phases 0–3, 5        ✅  UI, output, seeds, export, graph
    → LDR L0–L7      ✅  LangGraph default + full-text escalation + L6 URL enrich
    → LDR L5         ✅  IterResearch → iterresearch.py; deep_research shim
    → LDR L1         ✅  research_engines + keyword similar-paper fallback
```

**Evaluate:** `python scripts/ldr_eval_smoke.py` → `python scripts/ldr_e2e_smoke.py --max-time 420`

**Do not start:** IterResearch-only RT2 (OpenAlex wiring in `research_similar_papers.py`) — superseded by LDR engines.

## Open decisions

Record choices here when made:

| # | Question | Decision |
|---|----------|----------|
| 1 | Similar-paper / academic API strategy? | **LDR LangGraph + keyword search engines** ([`deep-research-ldr-migration.md`](deep-research-ldr-migration.md)); legacy RT2 **not planned**. IterResearch: S2 recs off; see [retrieval roadmap](deep-research-retrieval-roadmap.md). |
| 2 | Report length default: 1200 vs 3000+ words? | **User toggle** (Standard ~1200 / Extended 3000+) — applies to Odysseus synthesis pass |
| 3 | Preprints: default include vs peer-review-only? | **Keep toggle; include on by default** — `include_preprints` gates LDR + legacy |
| 4 | Seed papers: optional add-on vs first-class panel mode? | **First-class panel mode** |
| 5 | Phase 4 custom agent vs IterResearch loop? | **LangGraph via LDR** ([migration doc](deep-research-ldr-migration.md)); IterResearch deprecated on migration branch |
| 6 | Final report synthesis? | **(B) LDR gathers → Odysseus `research_templates` / registry synthesis** ([migration doc](deep-research-ldr-migration.md#decisions-locked)) |

---

## Acceptance criteria (“done”)

- [x] User selects 1–5 papers from catalog picker → runs Deep Research (Phase 2).
- [x] Engine reads PDFs / PubMed abstracts, finds related papers, stores sources in registry (Phases 1–2 + sourcing work).
- [x] Final report: themed Key Findings, numbered citations, References repair, sourcing disclosure (Phases 0–3).
- [x] Export Markdown / BibTeX / CSL JSON from registry (Phase 3).
- [x] Add seeds from **Links** paper detail (Phase 5a).
- [x] Add seeds from **Library** paper card menu (Phase 5a).
- [x] Paste DOI/URL validation and pre-run seed preview (Phase 5a).
- [x] Click citation → source detail; graph links for session (Phase 5b–c).
- [x] Web search failures surface with provider fallback (Phase 1a).

---

## How to use in future chats

Examples:

- *“Implement LDR Phase L2 per docs/deep-research-ldr-migration.md”*
- *“Wire panel include_zotero toggle into LDR search_zotero tool”*
- *“Phase 5 graph linking from docs/deep-research-roadmap.md”*
- *“Review retrieval policy in docs/deep-research-retrieval-roadmap.md — apply to LDR agent prompt”*
