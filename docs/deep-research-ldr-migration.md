# Deep Research → Local Deep Research (LDR) Migration

**Branch:** `feature/ldr-deep-research`  
**Status:** LDR migration L0–L7 + L5 complete — ready for live evaluation  
**Baseline:** [LearningCircuit/local-deep-research](https://github.com/LearningCircuit/local-deep-research) (LDR)  
**Last updated:** 2026-06-01

---

## Goal

Replace Odysseus **IterResearch** (`src/deep_research.py`) as the research **orchestration and retrieval backend** with LDR’s **LangGraph agent strategy**, while **preserving**:

| Must keep (Odysseus-owned) | Notes |
|----------------------------|--------|
| Report output shape | Markdown + `visual_report.py` HTML, numbered `[N]` citations, References |
| `EvidenceRegistry` | Stable `src:*` IDs, export BibTeX/CSL, sourcing tiers |
| Zotero integration | Catalog seeds, save-to-library, `research_zotero*.py` |
| Links / knowledge graph | `search_knowledge`, seed neighbors, **typed edges** (`research_typed_edges.py`, `edge_taxonomy.py`) |
| Seed / compare workflows | Modes, seed picker UI, compare/gap/similar_papers semantics |
| User policy | No auto-seeding, recency only on request, preprint toggle, owner scope |
| Panel + jobs API | `/api/research/*`, SSE progress, session JSON on disk |

**Deferred (after LangGraph conversion):** Human-in-the-loop plan approval UI (plan generated → user edits/confirms → agent runs).

---

## Why LDR

LDR’s default **`langgraph-agent`** strategy:

- LLM chooses **which engine** to call (PubMed, Semantic Scholar, OpenAlex, SearXNG, …) per sub-question
- Uses **keyword search** on academic APIs (not co-citation recommenders)
- **Two-phase** preview → LLM relevance filter → fetch (matches our RT0b/RT3 direction)
- Proven retrieval quality (~95% SimpleQA on local hardware)

Our IterResearch loop is a fixed Plan → Query → Search → Extract → Synthesize pipeline. It cannot adapt engines mid-run and currently misuses S2 `forpaper` recommendations.

---

## Integration tiers (all three)

User requested **A + B + C** together — not pick-one.

### Tier A — Pattern port (Odysseus-native)

Port LDR concepts into our codebase without vendoring the whole app:

- `BaseSearchEngine`-style contract: preview → filter → fetch
- LLM relevance filter (`relevance_filter.py` pattern)
- Engine registry (PubMed, S2 search, OpenAlex search, SearXNG via existing `services/search`)
- LangGraph tool list mirroring LDR’s `search_*` tools

**Where:** `src/research_engines/` (new), adapter over `services/search/`.

### Tier B — Library dependency

Add **`local-deep-research`** (PyPI) as a dependency for:

- Search engine implementations (`SemanticScholarSearchEngine`, `OpenAlexSearchEngine`, …)
- Relevance filter, rate limiting, citation normalization utilities
- Optional: `ResearchClient` programmatic API for benchmarks

**Constraint:** LDR requires **Python ≥3.12**; Odysseus currently runs 3.14 in venv — OK. Adds **LangChain + LangGraph + Flask stack** as transitive deps (Flask not used at runtime if we import engines only).

**Integration point:**

```python
# services/research/ldr_adapter.py (planned)
from local_deep_research.web_search_engines.search_engine_factory import create_search_engine
from local_deep_research.advanced_search_system.strategies.langgraph_agent_strategy import LangGraphAgentStrategy
```

Wrap with Odysseus LLM endpoint (`src/llm_core.py` → LangChain chat model adapter).

### Tier C — Full LDR research engine

Replace `DeepResearcher.research()` with LDR **`AdvancedSearchSystem` + `langgraph-agent`**:

- Odysseus `ResearchHandler.call_research_service()` delegates to LDR
- LDR collector output → **`EvidenceRegistry`** mapper
- LDR markdown/citations → **`ResearchHandler._format_research_report()`** + `visual_report`
- Custom LangGraph tools registered for **`search_zotero`**, **`search_knowledge`**, seed context injection

**Not replaced:** FastAPI app, panel UI, Zotero catalog, Links graph, session persistence format (extended, not discarded).

---

## Comparable components (Odysseus vs LDR)

| Capability | Odysseus today | LDR | Gap / action |
|------------|----------------|-----|--------------|
| **Orchestration** | `DeepResearcher` IterResearch loop | `LangGraphAgentStrategy` | **Replace** — core migration |
| **LangChain / LangGraph** | None | langchain ~1.2, langgraph ~1.2 (transitive) | **Add** deps + LLM adapter |
| **Web search** | `services/search/core.py` (SearXNG, Brave, Tavily, …) | Same providers + meta-search | **Reuse Odysseus** via LDR engine wrapper or factory alias |
| **Academic APIs** | `research_similar_papers.py` (OA `related_to`, S2 recs) | S2/OpenAlex **search engines** + filter | **Replace** with LDR engines |
| **Relevance gating** | `research_relevance.py` heuristics + LLM gate | `relevance_filter.py` batch LLM index pick | **Merge** — plan `avoid_topics` into filter prompt |
| **Retrieval plan** | `research_retrieval_plan.py` (RT3) | Implicit (agent decides) | **Inject** plan into agent system prompt + tool query templates |
| **Citations** | `EvidenceRegistry` stable IDs | `SearchResultsCollector` + `CitationHandler` | **Map** LDR results → registry at ingest |
| **Report synthesis** | Multi-round `SYNTHESIZE_PROMPT` + thematic outline | LDR report assembler + citation handlers | **Keep Odysseus** final academic template initially |
| **Page fetch / extract** | `goal_based_extractor` + `research_paper_fetch` | LDR `fetch_url` tools (trafilatura, etc.) | **Evaluate** — may use LDR fetch or keep ours for PDF/Zotero |
| **Vector / RAG** | ChromaDB + fastembed (`memory_vector`, `rag_vector`) | LDR SQLCipher library + sentence-transformers | **Keep Odysseus** vectors; optional LDR library later |
| **Embeddings** | fastembed (ONNX) | sentence-transformers | Different stack; no need to unify for v1 |
| **Rate limiting** | Minimal in `research_web_search` | Per-engine `rate_limiting/tracker` | **Port or use LDR** |
| **Progress UI** | SSE phases (`planning`, `reading`, …) | WebSocket milestones | **Map** LDR callbacks → existing progress schema |
| **Plan step** | `_create_plan()` auto-runs | Settings-driven; no HITL in LDR | **Keep** plan generation; add HITL gate later |
| **Seed papers** | First-class (`research_seeds.py`, panel) | Library collections as retriever | **Odysseus extension** — seed tools + compare mode in agent prompt |
| **Zotero** | Catalog + live API + save | Not built-in | **Odysseus-only tools** |
| **Links / graph** | `research_knowledge.py`, typed edges | Generic collections | **Odysseus-only tools** + post-run `research_graph.py` |
| **Session storage** | `data/deep_research/*.json` | SQLCipher DB | **Keep JSON** format; store LDR metadata fields |
| **LLM calls** | `llm_call_async` OpenAI-compatible | LangChain chat models | **Adapter required** |

### Odysseus components **without** LDR equivalent (preserve)

- `src/research_seeds.py` — seed resolution, PDF load, preview API
- `src/research_evidence.py` — registry, export, synthesis window policy
- `src/research_graph.py` + `src/research_typed_edges.py` — session → graph links
- `src/research_zotero_save.py` — save sources to library
- `src/visual_report.py` — HTML report
- `src/research_templates.py` — academic report structure
- `static/js/research/panel.js` — seeds, modes, settings
- `src/research_retrieval_plan.py` — structured plan (feeds agent context)

### LDR components **without** Odysseus equivalent (adopt)

- `LangGraphAgentStrategy` — agent loop, subtopic parallel workers
- `web_search_engines/engines/search_engine_*.py` — 20+ engines
- `web_search_engines/relevance_filter.py` — batch relevance
- `web_search_engines/search_engine_base.py` — two-phase contract
- `citation_handler.py` — synthesis citation plumbing (map to our registry)
- Rate limit tracker, egress policy (optional)

---

## Target architecture

```mermaid
flowchart TB
    subgraph UI["Odysseus UI (unchanged v1)"]
        PANEL[research/panel.js]
        JOBS[jobs.js SSE]
    end

    subgraph API["Odysseus API"]
        RH[ResearchHandler]
        ROUTES[/api/research/*]
    end

    subgraph ADAPT["New: LDR adapter layer"]
        LLM_ADP[LangChain model ← llm_core]
        PLAN[Retrieval plan + seed context]
        REG_MAP[LDR results → EvidenceRegistry]
        PROG[Progress mapper]
    end

    subgraph LDR["local-deep-research (Tier B/C)"]
        LGS[LangGraphAgentStrategy]
        TOOLS[Agent tools]
        ENG[Search engines]
    end

    subgraph ODY_TOOLS["Odysseus-only agent tools"]
        ZOT[search_zotero]
        KNO[search_knowledge]
        SEED[seed_paper_context]
    end

    subgraph OUT["Odysseus output (unchanged)"]
        REG[EvidenceRegistry]
        MD[Academic markdown report]
        VR[visual_report HTML]
        GRAPH[research_graph + typed edges]
    end

    PANEL --> ROUTES --> RH
    RH --> PLAN --> LGS
    LLM_ADP --> LGS
    LGS --> TOOLS
    TOOLS --> ENG
    TOOLS --> ODY_TOOLS
    LGS --> REG_MAP --> REG
    REG --> MD --> VR
    RH --> GRAPH
    LGS --> PROG --> JOBS
```

---

## Seed / compare workflow (preserved)

LDR has no native “compare two seed papers” mode. We implement via **agent configuration**, not a separate pipeline:

1. **Pre-run:** Resolve seeds → `seed_findings` + abstracts (existing `research_seeds.py`)
2. **Plan:** `ResearchRetrievalPlan` with `scope: narrow_compare`, `anchor_terms`, `avoid_topics`
3. **Agent system prompt:** Mode-specific instructions (literature_review | compare | gap_analysis | similar_papers)
4. **Tools:**
   - `search_semantic_scholar`, `search_openalex`, `search_pubmed` — plan-driven queries
   - `search_zotero` / `search_knowledge` — Odysseus wrappers
   - **No** S2 `forpaper` recommendations
5. **Post-run:** `research_typed_edges.py` infers `derives_from` / `supports` / `refutes` from report text

Compare mode agent rule (draft): *“Stay close to seed topics; prefer papers citing or cited by seeds; reject unrelated subfields listed in avoid_topics.”*

---

## Panel toggles (preserved)

All existing panel fields must work when `research_engine=ldr` (Phase L2). Canonical table: [main roadmap — panel toggles](deep-research-roadmap.md#panel-toggles-both-engines).

| Toggle | API field | LDR wiring (L2) |
|--------|-----------|-----------------|
| Preprints | `include_preprints` | Filter preprint hosts in engine config + agent prompt when off |
| Zotero | `include_zotero` | Register `search_zotero` Odysseus tool **only when on**; no catalog dump at round 0 |
| Links / knowledge | `include_knowledge` | Register `search_knowledge` **only when on** |
| Seed papers | `seed_papers` | Pre-load via `research_seeds.py`; mode-specific agent context; **no auto-seeding** |
| Mode | `mode` | `literature_review` \| `compare` \| `gap_analysis` \| `similar_papers` → system prompt |
| Report length | `report_length` | Odysseus synthesis token budget (decision B — not LDR report assembler) |
| Search provider | `search_provider` | Primary web/meta-search engine for LDR bridge |
| Max rounds / time | `max_rounds`, `max_time` | LangGraph iteration cap + wall-clock timeout |

**Retrieval policy** (no auto-seed, recency on request, reviews labeled in synthesis) applies via plan + prompts — see [retrieval policy](deep-research-retrieval-roadmap.md#retrieval-policy-locked--2026-06).

---

## Supersedes (IterResearch retrieval phases)

| Legacy phase | Doc | LDR replacement |
|--------------|-----|-----------------|
| RT2 — OpenAlex/S2 in `research_similar_papers.py` | [retrieval roadmap RT2](deep-research-retrieval-roadmap.md#phase-rt2--openalex-keyword--citation-expansion) | L1 engines + L2 agent tools |
| RT4 — embedding gate in loop | [retrieval roadmap RT4](deep-research-retrieval-roadmap.md#phase-rt4--semantic-ranking--embeddings) | LDR relevance filter; optional P2 embed |
| RT6 — dynamic URL budget | [retrieval roadmap RT6](deep-research-retrieval-roadmap.md#phase-rt6--dynamic-budget--stop-criteria) | Agent caps + panel `max_rounds` / `max_time` |
| Phase 4 — custom agent loop | [main roadmap Phase 4](deep-research-roadmap.md#phase-4--agent-shaped-research-optional-superseded) | LangGraph via LDR |

**Still shared:** RT0b/RT3 partial (`research_retrieval_plan.py`), RT1 observability, RT5 toggle semantics (no duplicate UI).

---

## Migration phases

### Phase L0 — Branch + deps + spike (this branch)

- [x] Migration doc + decision B (LDR gather → Odysseus synthesis)
- [x] `research_engine` setting (`iterresearch` | `ldr`)
- [x] `src/research/ldr_llm_adapter.py` — OpenAI-compatible endpoint → LangChain
- [x] `src/research/ldr_progress.py` — SSE phase mapping
- [x] `src/research/ldr_runner.py` — full L2 orchestration + `ResearchHandler` dispatch
- [x] `requirements-optional-ldr.txt`
- [x] Spike tests: `tests/test_ldr_live_spike.py` (construct LangGraph stack when LDR installed)

### Phase L1 — Engine layer (Tier A + B)

- [x] `src/research_engines/` — registry + Odysseus web search bridge
- [x] Wire LDR S2/OpenAlex/PubMed engines with Odysseus settings (API keys in admin)
- [x] Replace `research_similar_papers.py` API fallback with LDR search engines
- [x] Retire S2 `forpaper` and OpenAlex `related_to` defaults

### Phase L2 — LangGraph replaces IterResearch (Tier C core)

- [x] `run_ldr_research()` wired; `ResearchHandler` dispatches with panel toggles
- [x] Custom tools: Zotero, knowledge graph (`ldr_tools.py`)
- [x] `EvidenceRegistry` ingest from LDR collector (`ldr_collector_mapper.py`)
- [x] Odysseus `research_templates` final synthesis (decision B — `ldr_synthesis.py`)
- [x] Live integration test with `local-deep-research` installed (Python 3.12–3.13; Docker + `tests/test_ldr_live_spike.py`)
- [x] Feature flag: `research_engine=ldr` default (falls back to IterResearch when LDR deps missing)

### Phase L3 — Output parity

- [x] Golden fixture: `tests/fixtures/research/ldr_compare_foldseek.json`
- [x] Session JSON parity tests (`research_engine`, registry, breakdown) — `tests/test_ldr_output_parity.py`
- [x] Export + `visual_report` regression on LDR fixture
- [x] `source_rejected` progress events on ingest (RT1 partial)
- [x] End-to-end live run validated (`scripts/ldr_e2e_smoke.py` — DeepSeek, 64 sources, ~51k-char report)
- [x] Flip `research_engine=ldr` default after live golden pass

### Phase L4 — Human-in-the-loop plan (UI)

- [x] `/api/research/plan` returns structured plan + retrieval plan
- [x] Panel: review/edit plan → confirm → `/api/research/start` with `approved_plan`
- [x] Agent receives frozen plan JSON in system context (`build_retrieval_plan` + IterResearch `_approved_plan`)

### Phase L5 — Cleanup ✅

- [x] Deprecate `src/deep_research.py` — thin shim re-exporting `src/research/iterresearch.py`
- [x] Shared prompts in `src/research/research_prompts.py` (LDR + IterResearch)
- [x] Cross-reference sync: retrieval RT2/RT4/RT6 marked superseded; panel toggles documented in all three roadmaps
- [x] Archive IterResearch-only RT2/RT6 detail into retrieval doc `<details>` blocks only
- [x] Update `docs/deep-research-roadmap.md` Phase 4 → **LangGraph via LDR**

### Phase L6 — Full content acquisition ✅

LDR gather + Fetch Content often leaves registry entries as **metadata/snippets only**. Phase L6 adds DOI-aware dedup, light abstract resolution, and **model-selected** full-text load (not dumped into synthesis for every source).

| Step | Status | Module |
|------|--------|--------|
| DOI batch dedupe (keep richest row) | ✅ | `ldr_doi.py`, `ldr_collector_mapper.py` |
| DOI dedupe at ingest + `duplicate_doi` rejection | ✅ | `ingest_ldr_links`, `EvidenceRegistry._by_doi` |
| DOI from `doi.org` landing URLs | ✅ | `ldr_link_to_finding` |
| Light DOI abstract pass (no full PDF) | ✅ | `ldr_content_enrich.enrich_ldr_metadata` |
| LLM picker → full text for ≤6 sources | ✅ | `pick_sources_for_deep_read` + heuristic fallback |
| Full text only in synthesis via `deep_read_context` | ✅ | `ldr_runner` → `ldr_synthesis` |
| Zotero PDF on deep-read when keyed | ✅ | `fetch_deep_read_for_finding` |
| Non-DOI scholarly URL HTML/PDF extract | ✅ | `ldr_url_enrich.py` |
| Golden sourcing fixture (Foldseek shape) | ✅ | `tests/fixtures/research/ldr_sourcing_foldseek.json` |
| Pre-flight eval script | ✅ | `scripts/ldr_eval_smoke.py` |

### Phase L7 — Full-text escalation & PDF resolution ✅ shipped (v1)

**Observed (2026-06-01 E2E, Foldseek):** LangGraph source discovery works well (64 registry sources), but LDR **Fetch Content** fails on Semantic Scholar page URLs, bioRxiv landing pages, and paywalled DOI redirects. Post-gather L6 enrichment left **~92% of sources metadata-only** (59/64) despite many papers having accessible OA PDFs or PubMed abstracts.

Root cause is split:

| Layer | Issue |
|-------|--------|
| **LDR gather** | Agent calls `fetch_url` on S2/paper landing URLs that block bots or return shells — not DOI-resolved OA endpoints |
| **L6 enrich** | Abstract pass capped at 40 DOI lookups; full-text limited to ≤6 LLM-picked sources; PMC-only ladder misses OpenAlex/S2 OA PDFs and preprint full-text |

Phase L7 adds an **Odysseus-owned escalation ladder** after gather (independent of LDR Fetch Content) and evaluation smoke tests.

| Step | Status | Module |
|------|--------|--------|
| OpenAlex work lookup → abstract + OA `pdf_url` | ✅ | `ldr_fulltext_escalate.py` |
| Semantic Scholar OA PDF URL | ✅ | `ldr_fulltext_escalate.py` |
| PDF bytes → text via pypdf (`search/content`) | ✅ | `ldr_fulltext_escalate.py` |
| bioRxiv / medRxiv full-text page fetch | ✅ | `ldr_fulltext_escalate.py` |
| Escalation wired into deep-read + abstract pass | ✅ | `ldr_content_enrich.py` |
| Sourcing coverage metrics in E2E smoke | ✅ | `scripts/ldr_e2e_smoke.py`, `sourcing_tier_counts()` |
| **Evaluation smoke tests** | ✅ | see table below |

**Planned smoke tests (evaluation):**

| Script / test | Purpose | Pass criteria (initial) |
|---------------|---------|-------------------------|
| `scripts/ldr_fulltext_smoke.py` | Offline-friendly ladder on **known DOIs** (Foldseek Nature Biotech, clustering paper, one bioRxiv) | ≥2/3 DOIs resolve abstract ≥400 chars; ≥1/3 resolves full text ≥900 chars |
| `tests/test_ldr_fulltext_escalate.py` | Mocked HTTP for OpenAlex/S2/PDF paths | Unit coverage for ladder ordering and shell rejection |
| `scripts/ldr_e2e_smoke.py` (extended) | Live run sourcing breakdown after enrich | Print tier histogram; warn if `adequate+abstract` < 30% of registry |
| `tests/fixtures/research/ldr_sourcing_foldseek.json` | Golden sourcing snapshot (mocked enrich) | Regression on tier counts when ladder is mocked |

**Escalation order (locked for L7):**

1. PubMed + Europe PMC abstract (`research_paper_fetch`)
2. **PMC full text** when Europe PMC returns a PMCID:
   - BioC JSON (NCBI REST)
   - Article HTML: `https://pmc.ncbi.nlm.nih.gov/articles/{PMC_ID}/`
   - PDF auto-resolve: `https://pmc.ncbi.nlm.nih.gov/articles/{PMC_ID}/pdf/` → pypdf extract
3. **DOI landing** (`https://doi.org/{DOI}`):
   - PDF via content negotiation (`Accept: application/pdf`)
   - Publisher HTML article page (follow redirect + extract)
4. OpenAlex abstract + OA PDF URL
5. Semantic Scholar OA PDF URL
6. Direct PDF fetch + pypdf extract (non-PMC OA URLs)
7. bioRxiv/medRxiv `.full` HTML text

**Deferred (L7+):** Unpaywall API (needs admin email key); publisher-specific scrapers; raising deep-read cap beyond 6 without token budget guard.

---

## Dependencies to add

From LDR `pyproject.toml` (minimal set for Tier B/C):

| Package | Purpose | Odysseus note |
|---------|---------|---------------|
| `local-deep-research` | Engine + strategy bundle | Pin version; import subset only |
| `langchain`, `langchain-core`, `langchain-community` | Agent + tools | New to Odysseus |
| `langgraph` | Agent strategy | Transitive via LDR |
| `langchain-openai` | Model adapter | Map to our endpoints |

**Already present:** `httpx`, `beautifulsoup4`, `pypdf`, `python-dateutil`, `numpy`

**Not needed for v1:** LDR Flask/SQLCipher/Playwright (unless we adopt LDR library feature later)

**Python version:** Confirm CI/production ≥3.12 before enabling LDR.

---

## Risk register

| Risk | Mitigation |
|------|------------|
| LDR dep weight (LangChain stack) | Optional extra; feature flag; import engines only first |
| LLM adapter mismatch (local endpoints) | Spike on Ollama/OpenAI-compatible endpoints early |
| Report format drift | Registry-first mapping; golden file tests |
| Seed/compare quality | Plan + avoid_topics + Odysseus tools; no S2 recs |
| Progress UI breaks | Explicit phase mapping table in L0 |
| Owner / multi-tenant | Pass `owner` into Zotero/knowledge tools; LDR `programmatic_mode=True` skips its DB |

---

## Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| 1 | **Final report** | **(B) LDR gathers sources → Odysseus academic template / thematic synthesis** on `EvidenceRegistry` at end |
| 2 | Integration tiers | A + B + C (pattern port + PyPI dep + LangGraph engine) |
| 3 | Orchestration | LangGraph replaces IterResearch entirely |
| 4 | Seed/compare | Odysseus-owned tools + prompts; preserved |
| 5 | HITL plan UI | After LangGraph conversion (Phase L4) |

---

## Open items

1. ~~**Final report:** LDR synthesis only, or Odysseus academic template on top of registry?~~ → **B (locked)**
2. **LDR library / download-to-collection:** Adopt in Phase 6+ or skip?
3. **Subagent parallelism:** LDR runs up to 4 subtopic workers — cap for Odysseus server load?
4. **License:** LDR is MIT — compatible with Odysseus; keep `licenses/DeepResearch-Apache-2.0.txt` attribution note if any Alibaba IterResearch code remains during transition.

---

## Related docs

| Doc | Relationship |
|-----|--------------|
| [`deep-research-roadmap.md`](deep-research-roadmap.md) | Product phases 0–5, UI, panel toggles, export |
| [`deep-research-retrieval-roadmap.md`](deep-research-retrieval-roadmap.md) | Retrieval **policy** + RT0–RT6 audit; RT2/RT4/RT6 superseded by L1–L2 here |
| [`learned-graph-connections-roadmap_v1.md`](learned-graph-connections-roadmap_v1.md) | Post-run graph proposals; quality depends on LDR source gathering |

**Next step:** Live evaluation complete (2026-06-01). Optional follow-ups: admin UI for `openalex_email` / `semantic_scholar_api_key`, Unpaywall API.
