# Deep Research Roadmap

Living plan to bring Deep Research up to date with Links, Zotero catalog, and web search work. Use this doc when starting future chats: *"Follow docs/deep-research-roadmap.md Phase X"*.

**Last updated:** 2026-06-01

---

## Current state (baseline)

**Engine:** `src/deep_research.py` — Plan → query generation → web search → page fetch + LLM extract → synthesize → stop decision → final polish (IterResearch-style loop).

**Integrations today:**

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
| Research engine | `src/deep_research.py` |
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

1. From seed: title, abstract, keywords, DOI, references (if extractable from PDF).
2. Generate **similarity queries** (not generic topic queries):
   - DOI → Crossref/OpenAlex/Semantic Scholar (if connectors added).
   - Title/author variants on web search.
   - Zotero catalog fuzzy match + same collection siblings.
3. Rank candidates: citation overlap, semantic title match, recency, peer-review status.
4. Dedupe against seeds + `_zotero_keys_seen`.

**Deliverable:** “Given these 3 papers, find related work and summarize key findings” works end-to-end.

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

---

## Phase 4 — Agent-shaped research (optional)

**Goal:** Align with app-wide tool calling. **Estimate:** 3+ weeks.

Research agent with constrained tools:

| Tool | Use in research |
|------|-----------------|
| `search_knowledge` | Seeds, graph neighbors, read `paper:KEY` |
| `search_zotero` | Catalog + PDF |
| `web_search` | Discovery & similar papers |
| `web_fetch` | Specific DOI/PDF URLs |
| Internal `register_evidence` | Add to registry with stable ID |

Orchestrator caps rounds/time/cost; each step auditable in progress UI.

**Deliverable:** Progress shows tool calls (“Read PDF …”, “Web search …”, “Found 4 similar papers”).

---

## Phase 5 — Library & Links integration

**Goal:** UI polish and cross-linking. **Estimate:** ~1 week.

- Deep Research panel: “Add from Library” / “Add from Links”.
- Completed report → save sources to Zotero + link graph nodes (`paper` ↔ `research:SESSION`).
- Library Research tab: show seed papers, source count by type (web / Zotero / PDF).

---

## Suggested priority order

```
Phase 0 (citations & synthesis)
    → Phase 1a (web) + 1b (Zotero catalog) + 1c (Links)
    → Phase 2 (seed papers + similar)
    → Phase 3 (academic templates)
    → Phase 4 (agent orchestration, optional)
    → Phase 5 (UI polish)
```

**Recommended first slice:** Phase **0 + 1a + 1b + minimal Phase 2** (stable citations, proper web search, catalog/PDF Zotero, seed keys in panel).

---

## Open decisions

Record choices here when made:

| # | Question | Decision |
|---|----------|----------|
| 1 | Similar-paper sources: web only first, or OpenAlex/Semantic Scholar early? | **OpenAlex + Semantic Scholar early** |
| 2 | Report length default: 1200 vs 3000+ words? | **User toggle** (Standard ~1200 / Extended 3000+) |
| 3 | Preprints: default include vs peer-review-only for “professional academic”? | **Keep toggle; include on by default** |
| 4 | Seed papers: optional add-on vs first-class panel mode? | **First-class panel mode** |
| 5 | Phase 4 agent model: worth complexity vs improved IterResearch loop? | **Improve IterResearch loop** (defer agent-shaped Phase 4) |

---

## Acceptance criteria (“done”)

- [ ] User selects 1–5 papers from Library/Links → runs Deep Research.
- [ ] Engine reads PDFs, finds related papers via web + Zotero, stores all in a source registry.
- [ ] Final report: themed Key Findings, numbered citations, References matching body, no invented statistics.
- [ ] Every source traceable (Zotero key, URL, or graph node id).
- [ ] Web search failures surface clearly (same as chat), with provider fallback.

---

## How to use in future chats

Examples:

- *“Implement Phase 0 evidence registry from docs/deep-research-roadmap.md”*
- *“Start Phase 1a — unify web search for Deep Research per the roadmap”*
- *“Review deep-research-roadmap.md and pick the next unblocked task”*
