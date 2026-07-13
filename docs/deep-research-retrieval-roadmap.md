# Deep Research Retrieval Roadmap

**Topical, seed-aware academic retrieval — policy and legacy IterResearch path.**

**Status:** **RT0 partial** + **RT0b/RT3 partial** on IterResearch. **Source discovery superseded by LDR** when `research_engine=ldr`.

**Last updated:** 2026-06-01

**Primary backend (active):** [`deep-research-ldr-migration.md`](deep-research-ldr-migration.md) — LangGraph agent + LDR search engines replace RT2/RT4/RT6 for gathering sources.

**Use this doc when:**

- Applying **retrieval policy** to LDR agent prompts and panel toggles
- Maintaining **IterResearch** path as explicit fallback (`research_engine=iterresearch` or missing LDR deps)
- Audit history and acceptance criteria shared with parent roadmap

**Parent doc:** [`deep-research-roadmap.md`](deep-research-roadmap.md) (UI, output, Library/Links). **Do not use this doc alone for new OpenAlex/S2 wiring** — see LDR migration L1–L2 instead.

**Related docs:**

| Doc | Relationship |
|-----|----------------|
| [`deep-research-ldr-migration.md`](deep-research-ldr-migration.md) | **Replaces RT2, RT4, RT6** for source discovery; implements S2/OpenAlex via LDR engines |
| [`paper-token-retrieval-roadmap_v1.md`](paper-token-retrieval-roadmap_v1.md) | Chat/agent paper tiers; DR should not re-dump full PDFs when seeds already loaded |
| [`knowledge-graph-edge-taxonomy-roadmap_v3.md`](knowledge-graph-edge-taxonomy-roadmap_v3.md) | Post-run typed edges; retrieval quality affects edge proposals |
| [`learned-graph-connections-roadmap_v1.md`](learned-graph-connections-roadmap_v1.md) | Research session → proposed edges |

---

## Superseded by LDR

When **`research_engine=ldr`** (see [`deep-research-ldr-migration.md`](deep-research-ldr-migration.md)), **do not implement** these IterResearch-only phases — LDR handles them:

| Phase | Was | LDR replacement |
|-------|-----|-----------------|
| **RT2** | Wire OpenAlex search/refs/cited-by in `research_similar_papers.py` | LDR `OpenAlexSearchEngine`, `SemanticScholarSearchEngine`, agent tool selection |
| **RT4** | Embedding hybrid gate in `research_relevance.py` | LDR relevance filter + optional future Odysseus embed overlay (P2) |
| **RT6** | Dynamic URL budget in `deep_research.py` | LDR agent iteration limits + `max_rounds` / `max_time` panel toggles |
| **RT2 S2 recs / OA `related_to`** | Co-citation APIs | **Never** — LDR uses keyword search only |

**Still apply under LDR:**

| Item | Why |
|------|-----|
| [Retrieval policy](#retrieval-policy-locked--2026-06) | Encoded in agent system prompt + toggle gates |
| [Panel toggles](deep-research-roadmap.md#panel-toggles-both-engines) | `include_preprints`, `include_zotero`, `include_knowledge`, seeds, mode |
| **RT0b / RT3 (partial)** | `research_retrieval_plan.py` → frozen plan JSON in agent context |
| **RT1 (partial)** | Rejection logging → progress UI; golden fixtures |
| **RT5 (partial)** | Scope/recency already map to mode + toggles; no duplicate UI required |

---

## Problem

Deep Research was built on an **IterResearch + general web search** stack. That stack optimizes for freshness and broad discovery. Users running **seed-centric** jobs (compare two papers, 3Di / Foldseek / ESM3, field overview) hit two failure modes:

1. **Wrong papers cited** — same broad field (bioinformatics), wrong sub-problem (e.g. GO function prediction when the question is structure representation).
2. **Missing expected papers** — web search and co-citation APIs surface recent SEO-friendly hits; seminal or seed-adjacent work is skipped.

Observed regression case: **FuseGO** entered via Semantic Scholar recommendations on an ESM3 seed — shared generic tokens (`protein`, `language model`, `function`) with seeds but did not address the user's compare question.

Root causes (audit summary):

| Layer | Old behavior | User expectation |
|-------|--------------|------------------|
| Ranking | News-style `recency_score` in `rank_search_results` | Topical fit first; recency only when asked |
| Query templates | Auto-append `systematic review OR meta-analysis` | Seed-title / DOI queries; reviews when appropriate |
| Gap rounds | Prompt + time filter pushed “recent” literature | Fill conceptual gaps relative to question/seeds |
| Similar papers | S2/OpenAlex fallback sorted by publication year | Citation neighborhood + seed topical overlap |
| Gating | Lexical overlap + bioinformatics-specific anchor/block lists | Plan-driven anchors + embeddings; no method whitelists |
| Seeding | Auto Zotero catalog + Links graph as seeds | **Explicit seeds only**; library on user request |
| Synthesis window | Last N findings by insertion order | Seeds + **best** N by relevance |

---

## Retrieval policy (locked — 2026-06)

Implement and test against these product rules. Do not regress them without an explicit decision update.

| # | Policy | Implementation note |
|---|--------|---------------------|
| 1 | Non-seed sources may be **topic-adjacent**, not seed-locked | User prompt supplies scope; gating rejects same-field / wrong-subtopic |
| 2 | **Publication date is not a ranking factor** unless the user asks for recent / time-bounded work | Soft age tie-break OK; never hard-filter by year by default |
| 3 | **Systematic reviews / meta-analyses** are normal sources; synthesis must **label** them as reviews | No extra URL/title rank boost for “systematic review” |
| 4 | Attached seeds appear in References **only if cited** | No forced seed citations |
| 5 | **No auto-seeding** | Only user-attached `seed_papers`; no “recent catalog” or implicit graph seeds |
| 6 | **Zotero is not prioritized over web** | Library search when user enables Zotero and/or query implies “my library”; not round-0 default |
| 7 | **Foundational vs frontier** follows the prompt | Broad overview → seminal work OK; narrow compare → stay on named papers/methods |
| 8 | Both failure modes matter | Tests must cover off-topic rejection **and** expected-paper recall |

---

## Capability baseline

### Shipped (RT0 partial + RT0b/RT3 partial — IterResearch path)

| Item | Where | Notes |
|------|-------|-------|
| Research search `recency_weight=0` | `research_web_search.py` → `rank_search_results` | Chat/news path unchanged |
| Time filters only on explicit recency | `infer_time_filter` + `user_requests_recency()` | Gap round year tokens no longer auto-filter |
| No auto Zotero / graph seeding | `deep_research.py` | Links expansion only when user attached seeds |
| Seed-only `_seed_findings()` | `deep_research.py` | `is_seed=True` only — not every `zotero_key` |
| Softer discovery templates with seeds | `enhance_query_for_kind(..., has_seeds=True)` | Skips forced systematic-review suffix |
| Prompt: topical fit over recency | `QUERY_GEN_PROMPT`, `current_date_context()` | |
| Similar-paper soft age + seed overlap sort | `research_similar_papers._rank_similar` | Replaced hard ≥2020 bonus |
| Synthesis window by relevance | `EvidenceRegistry.select_for_synthesis(..., relevance_query=)` | Seeds always included |
| Specific-term gating | `score_specific_*`, `is_similar_paper_relevant`, weak anchors | FuseGO regression test |
| S2 recommendations disabled with seeds / compare | `research_similar_papers.similar_papers_from_seeds` | Co-citation API only; no keyword search |
| Post-extraction relevance filter | `_search_and_extract` → `is_finding_relevant` | |
| Stricter relevance gate prompt | `RELEVANCE_GATE_WITH_SEEDS_PROMPT` | Reject broad-field / wrong-subtopic |
| **RT0b:** removed static anchor whitelists | `research_relevance.py` | `matches_avoid_topics()` from plan |
| **RT3:** structured retrieval plan | `research_retrieval_plan.py`, planner JSON | Feeds IterResearch + LDR agent context |

### Not built on IterResearch (superseded by LDR — do not start)

| Gap | Was RT phase | LDR instead |
|-----|--------------|-------------|
| Custom OpenAlex search/refs in `research_similar_papers.py` | RT2 | LDR OpenAlex engine + agent |
| Embedding similarity gate | RT4 | LDR filter; optional Odysseus embed later |
| Dynamic fetch budget in loop | RT6 | Agent caps + panel `max_rounds` |
| S2 `forpaper` / OA `related_to` as primary path | RT2 (explicitly off) | LDR keyword search only |

### Still open (both engines)

| Gap | Impact | Owner |
|-----|--------|-------|
| Rejection logging → progress UI | User cannot see why a source was rejected | RT1 → LDR progress mapper |
| Golden retrieval fixtures | Regression for compare/seed modes | RT1 |
| LDR agent respects all panel toggles | Preprints/Zotero/knowledge gating | [L2 migration](deep-research-ldr-migration.md#panel-toggles-preserved) |

**Key files:**

| Area | Path |
|------|------|
| Main loop | `src/deep_research.py` |
| Web search + templates | `src/research_web_search.py` |
| Relevance / gating | `src/research_relevance.py` |
| Similar papers (S2/OpenAlex) | `src/research_similar_papers.py` |
| Evidence / synthesis window | `src/research_evidence.py` |
| Shared search ranking | `services/search/ranking.py` |
| Zotero gatherer | `src/research_zotero.py` |
| Links gatherer | `src/research_knowledge.py` |
| Tests | `tests/test_research_relevance.py`, `tests/test_research_web_search.py`, `tests/test_research_evidence.py` |

---

## Academic API strategy (Semantic Scholar vs OpenAlex)

### Semantic Scholar — **deprioritized**

| Aspect | Today | Decision |
|--------|-------|----------|
| **Integration** | `GET /recommendations/v1/papers/forpaper/{DOI}` only | **Do not expand** recommendation usage |
| **Keyword search** | Not implemented | Optional **P2** — `GET /graph/v1/paper/search?query=` fed by plan `search_keywords` only if OpenAlex + web insufficient |
| **With seeds / compare** | Disabled in code (`use_semantic_scholar=False`) | **Keep off** by default |
| **Why** | Co-readership graph; FuseGO appears for Foldseek DOI; no topical control | Recommendations optimize “people also read”, not “answers this sub-question” |

S2 is a poor fit for seed-centric Deep Research. If we need a second bibliographic API after OpenAlex, S2 **paper search** (not recommendations) is the only form worth considering — and only with plan-driven keywords, not seed-DOI neighbors.

### OpenAlex — **keep, but replace `related_to`**

OpenAlex is worth keeping — open metadata, abstracts, DOI resolution, citation graph — but **the current call pattern is as bad as S2 recommendations**.

| OpenAlex capability | Used today? | Fit for our goals |
|---------------------|-------------|-------------------|
| `GET /works/{doi}` — metadata + abstract | Partial (via DOI → id) | **Yes** — seed enrichment |
| `filter=related_to:{work_id}` | **Yes** — `openalex_similar_works()` | **No** — opaque ML neighbor; empirically noisy (GFP, person re-id for protein-structure seeds) |
| `search={keywords}` | **No** | **Yes** — primary expansion with plan `search_keywords` |
| Seed `referenced_works` (bibliography) | **No** | **Yes** — intellectual lineage, foundational papers user asks for |
| `filter=cites:{work_id}` (cited-by) | **No** | **Yes** — downstream work citing seeds |
| Shared `concepts.id` with seed | **No** | **Maybe** — broader than keywords, needs gating |
| `filter=from_publication_date` | **No** | Only when user requests recency |

**Decision:** Deprioritize OpenAlex `related_to` alongside S2 recommendations. **Promote** OpenAlex keyword search + reference/cited-by expansion, all fed by structured plan keywords and seed DOIs.

---

## Hardcoded domain logic audit (RT0b)

Several paths use **static bioinformatics keyword lists** instead of per-run terms from the plan and seeds. Note: **`esm3`, `blast`, etc. are not S2 search terms** — they appear in gating whitelists only. Nobody does not keyword-search Semantic Scholar today.

### Tier 1 — Should become dynamic (plan / seed derived)

| Item | File | Problem | Target |
|------|------|---------|--------|
| `_DISTINCTIVE_SHORT_ANCHORS` (`esm3`, `blast`, `3di`, …) | `research_relevance.py` | Single-token accept whitelist | `plan.anchor_terms` + `extract_anchor_terms()` from seeds |
| `_GO_FUNCTION_MARKERS` + `_STRUCTURE_FOCUS_MARKERS` | `research_relevance.py` | Static subfield rules (FuseGO patch) | `plan.avoid_topics` + LLM relevance gate |
| `_GENERIC_SCIENCE_TERMS` | `research_relevance.py` | Comp-bio stoplist | Per-run IDF or plan-labeled “broad terms” |
| `_WEAK_ANCHOR_TERMS` | `research_relevance.py` | Growing blocklist | Require 2+ plan anchors or embeddings |
| `enhance_query_for_kind()` suffixes | `research_web_search.py` | Auto `systematic review`, `site:pubmed`, `peer-reviewed evidence` | Plan `expansion_queries` + scope |
| `apply_academic_query_templates()` fallback | `research_web_search.py` | `"{question} systematic review"` | Only when `scope: field_overview` |
| Round instructions / QUERY_GEN examples | `deep_research.py` | Hardcoded PubMed/Scholar/review patterns | Plan-driven round instructions |

### Tier 2 — Already dynamic (extend, don’t duplicate)

| Item | File | Role |
|------|------|------|
| `extract_anchor_terms()` | `research_relevance.py` | CamelCase, acronyms, digits from question + seeds |
| `build_relevance_query()` | `research_relevance.py` | Question + seed fingerprint |
| `similar_paper_queries_from_seeds()` | `research_web_search.py` | Title / DOI → PubMed/Scholar |
| `_generate_queries()` | `deep_research.py` | LLM query strings each round |

**Gap:** dynamic extraction exists for gating, but APIs and templates do not share one structured keyword list from the planner.

### Tier 3 — OK to keep hardcoded (infrastructure)

URL hosts (`pubmed`, `doi.org`, `scholar.google`), English stopwords, extraction boilerplate markers, recency-intent phrases, preprint hosts, research modes, export formats, PubMed/Scholar **site:** syntax (not domain keywords).

---

## Target retrieval workflow

### LDR path (default after migration)

```
Panel toggles + seeds + mode
    → ResearchRetrievalPlan (JSON): anchors, avoid_topics, scope, expansion_queries
    → LangGraph agent (LDR langgraph-agent)
          • LDR engines: S2/OpenAlex/PubMed/SearXNG keyword search
          • Odysseus tools (when toggles on): search_zotero, search_knowledge
          • LDR relevance filter on previews
    → EvidenceRegistry ← map collector results
    → Odysseus academic synthesis (decision B) — NOT LDR report assembler
```

See [`deep-research-ldr-migration.md`](deep-research-ldr-migration.md).

### Legacy IterResearch path (`research_engine=iterresearch`)

```
User question + optional explicit seed papers
    → Plan (JSON): sub_questions, anchor_terms, search_keywords, avoid_topics, scope
    → Phase A — Seeds: load PDF/abstract; register evidence
    → Phase B — Web + weak API fallback (research_similar_papers — being retired)
    → Gate: plan avoid_topics + anchors + LLM
    → Synthesize: seeds + top-K by relevance_query
```

---

## Phase RT0b — De-hardcode domain keywords

**Status:** ✅ **Partial shipped** on IterResearch (`matches_avoid_topics`, plan `anchor_terms`). LDR path uses same plan object in agent context.

**Remaining (IterResearch only until deprecated):** shrink `_GENERIC_SCIENCE_TERMS` usage; non-comp-bio fixtures.

<details>
<summary>Original RT0b tasks (reference)</summary>

| Task | Detail |
|------|--------|
| **Remove `_DISTINCTIVE_SHORT_ANCHORS`** | `_is_distinctive_anchor()` uses plan/seed `extract_anchor_terms` only (digit tokens, acronyms, title-derived method names) |
| **Replace subfield marker tables** | `is_subfield_mismatch()` → `plan.avoid_topics` substring gate + existing LLM gate |
| **Shrink `_WEAK_ANCHOR_TERMS`** | Keep minimal English function words; drop domain nouns — use 2+ anchor requirement |
| **Plan fallback for anchors** | If JSON plan missing, derive `anchor_terms` via `extract_anchor_terms(question, seed_fingerprint)` and store on `DeepResearcher` |
| **Stop template keyword stuffing** | `enhance_query_for_kind` only adds site syntax when plan/query already targets PubMed/Scholar; no auto “systematic review” when seeds or `narrow_compare` |
| **Tests** | Non-comp-bio fixture (e.g. ecology or policy) must not depend on `esm3`/`blast` lists |

**Acceptance:**

- [x] `_DISTINCTIVE_SHORT_ANCHORS` deleted; tests use `avoid_topics`.
- [x] FuseGO rejected via `avoid_topics`, not hardcoded GO markers.
- [ ] Fixture outside bioinformatics passes gating without comp-bio false negatives.

</details>

---

## Phase RT1 — Hardening & observability

**Status:** **Still relevant** for both engines (progress UI, fixtures).

| Task | Detail |
|------|--------|
| **Golden retrieval fixtures** | Extend `tests/fixtures/research/` with expected accept/reject lists (FuseGO reject; Foldseek/3Di neighbor accept) per mode |
| **Rejection logging → progress UI** | Emit `source_rejected` events with `reason` (`low_specific_overlap`, `llm_gate`, `off_topic_extraction`) |
| **Settings keys** | `research_min_specific_overlap`, `research_synthesis_window` (exists), `research_max_urls_per_round` — document defaults |
| **Compare-mode stricter defaults** | `research_mode=compare` → higher `min_specific_score`, skip broad discovery template entirely |
| **Review labeling in registry** | Set `study_type` / `is_review` when title or extractor marks systematic review/meta-analysis |
| **Doc sync** | Update parent `deep-research-roadmap.md` synthesis window row (now relevance-ranked, not “last 10”) |

**Deliverable:** Re-run ESM3 vs Foldseek compare fixture; FuseGO absent; progress log shows at least one rejection reason.

**Acceptance:**

- [ ] `tests/test_research_relevance.py` includes compare-mode FuseGO + positive Foldseek neighbor cases (partially done).
- [ ] Research panel or job log surfaces “Skipped off-topic: …” for at least web and similar-paper paths.
- [ ] No regression on `tests/test_research_web_search.py` time-filter and seed-template tests.

---

## Phase RT2 — OpenAlex keyword + citation expansion

> **Superseded by LDR** — implement [`deep-research-ldr-migration.md` Phase L1–L2](deep-research-ldr-migration.md#phase-l1--engine-layer-tier-a--b) instead. Do not wire `openalex_works_search` in `research_similar_papers.py`.

<details>
<summary>Original RT2 spec (historical — IterResearch only)</summary>

**Goal:** Replace web-first similar papers and co-citation recommenders with plan-driven OpenAlex search.

| Task | Detail |
|------|--------------|--------|
| **`openalex_works_search(query, limit)`** | `GET /works?search={keywords}` | Pass `plan.search_keywords` joined or per-term; rank by `score_specific_finding_relevance` |
| **`openalex_seed_references(doi)`** | `GET /works/{doi}` → `referenced_works` → batch fetch | Foundational / lineage papers the seeds cite |
| **`openalex_cited_by(doi, limit)`** | `filter=cites:{openalex_work_id}` | Downstream papers citing seeds — often more topical than `related_to` |
| **`openalex_concept_neighbors` (optional)** | Shared `concepts.id` | Secondary expansion; strict gating |
| **Invert `_fetch_similar_paper_findings`** | — | (1) OpenAlex keyword + references + cited-by, (2) plan PubMed/Scholar queries, (3) open web only if &lt; N on-topic hits |
| **Metadata enrichment** | `GET /works/{doi}` | Seed preview + abstract backfill when Zotero/PubMed sparse |
| **Per-seed quotas** | — | e.g. 4 references + 4 cited-by + 6 keyword hits; 15 total cap |
| **Scholar web budget** | — | Cap similar-paper web fetches at 4 when OpenAlex succeeded |

**Files:** `research_similar_papers.py` (new functions), `research_retrieval_plan.py` (RT3), `deep_research.py` (`_fetch_similar_paper_findings`).

**Deliverable:** Compare run with two DOI seeds expands via OpenAlex `search` + references before any web discovery; FuseGO absent; no S2 calls.

**Acceptance:**

- [ ] With 2 seeded DOIs, ≥50% of non-seed similar sources come from `similar_source=openalex` via **search/references/cited-by** (not `related_to`).
- [ ] Zero S2 recommendation calls when `seed_papers` non-empty.
- [ ] `openalex_similar_works(related_to)` not invoked unless explicit setting enabled.
- [ ] FuseGO-class paper not in `raw_findings` for structure-compare fixture.
- [ ] Unit tests mock OpenAlex search + references; assert web similar search deferred when enough hits.

</details>

---

## Phase RT3 — Structured retrieval plan

**Status:** ✅ **Partial shipped** — `research_retrieval_plan.py`, planner JSON, `avoid_topics` gate. **LDR path:** same plan object injected into agent system context (L2).

**Remaining (IterResearch only):** gap-round sub-question coverage tracking; full acceptance checklist below.

<details>
<summary>Original RT3 spec (reference)</summary>

**Goal:** Plan step outputs **retrieval strategy**, not only sub-questions for the LLM to freestyle into web queries.

### Plan JSON extension

```json
{
  "sub_questions": ["..."],
  "anchor_terms": ["..."],
  "search_keywords": ["..."],
  "scope": "narrow_compare | field_overview | gap_analysis",
  "must_stay_close_to_seeds": true,
  "foundational_ok": false,
  "expansion_queries": [
    "site:pubmed.ncbi.nlm.nih.gov \"<seed method>\" \"<distinctive term>\"",
    "site:scholar.google.com intitle:\"<seed paper title fragment>\""
  ],
  "avoid_topics": ["gene ontology function prediction", "unrelated subfield examples"],
  "openalex_search_queries": ["optional verbatim OpenAlex search strings"]
}
```

`anchor_terms` and `search_keywords` are **derived by the planner from seed abstracts and the user question** — never copied from a static code list. `openalex_search_queries` defaults to `search_keywords` if omitted.

| Task | Detail |
|------|--------|
| **Planner prompt** | `RESEARCH_PLAN_PROMPT` + seed abstract snippets → emit structured JSON above |
| **Query gen consumes plan** | Round 1 uses `expansion_queries` + drives `openalex_works_search(search_keywords)` |
| **`avoid_topics` gate** | Reject findings whose title+abstract hits any avoid phrase (replaces hardcoded GO/structure tables) |
| **Scope drives templates** | `field_overview` may add one review query; `narrow_compare` forbids generic topic restatement |
| **Gap round uses uncovered sub-questions** | Track which `sub_questions` lack supporting findings |
| **Optional S2 paper search** | Only if enabled in settings: `search_keywords` → S2 `/paper/search` — never recommendations |

**Files:** `deep_research.py` (plan + query gen), `research_templates.py`, new `research_retrieval_plan.py` (parse/validate).

**Deliverable:** Compare-mode plan lists anchor terms from seed titles; round-1 searches use DOI/title queries, not `"<question> systematic review"`.

**Acceptance:**

- [ ] Plan JSON validated; malformed plans fall back to current behavior with warning.
- [ ] `narrow_compare` run: zero round-1 queries contain only the user question + “systematic review”.
- [ ] `field_overview` run: at least one query may target reviews or seminal work (user prompt permitting).

</details>

---

## Phase RT4 — Semantic ranking & embeddings

> **Superseded for source discovery by LDR** — LDR relevance filter handles preview gating. Optional Odysseus embed overlay (P2) may augment synthesis window only.

<details>
<summary>Original RT4 spec (historical — IterResearch only)</summary>

**Goal:** Move beyond token overlap for “same field, wrong subtopic” and “missed obvious neighbor”.

| Task | Detail |
|------|--------|
| **Reuse Links / catalog embeddings** | If `paper:KEY` or catalog row has embedding, score candidates by cosine similarity to seed abstract vector |
| **Fallback: lightweight embed** | On-the-fly embed title+abstract for web hits (local model or API — settings-gated) |
| **Hybrid score** | `final = 0.4 * lexical_specific + 0.4 * embed + 0.2 * citation_proximity` (tune in RT1 fixtures) |
| **Gate threshold by mode** | Compare: higher embed threshold; literature_review: slightly lower |
| **Cache per session** | Store embed scores on finding dict to avoid recompute each round |

**Prerequisite:** Confirm embedding source in `knowledge_graph` / `zotero_catalog` (may be partial).

**Deliverable:** FuseGO rejected even when lexical score borderline; paraphrased neighbor (no shared tokens) accepted when embed similarity high.

**Acceptance:**

- [ ] Fixture: paraphrase title neighbor passes gate without shared anchor tokens.
- [ ] FuseGO fixture fails embed + lexical gate.
- [ ] Feature off when no embedder configured — lexical-only path unchanged.

</details>

---

## Phase RT5 — User controls & Zotero intent

**Status:** **Largely covered by panel toggles** — see [main roadmap panel toggles](deep-research-roadmap.md#panel-toggles-both-engines). L2 wires toggle → tool registration; no duplicate scope UI required unless product asks.

**Still open:** source provenance tags on report cards (`seed | citation_graph | web_discovery | zotero | links`).

<details>
<summary>Original RT5 spec (reference)</summary>

**Goal:** Surface retrieval policy in UI; align Zotero with “on request” policy.

| Task | Detail |
|------|--------|
| **Retrieval scope control** | Panel: *Focused* (default for compare) / *Balanced* / *Broad overview* — maps to `scope` + foundational_ok |
| **Recency toggle** | “Prefer recent literature” checkbox → enables `user_requests_recency` behavior + prompt line |
| **Zotero intent** | Only query library when: (a) user checked Include Zotero **and** (b) query contains library cues OR scope is Balanced/Broad **or** user @-mentioned library |
| **Include library in search** | Optional explicit chip: “Search my Zotero for this run” |
| **Source provenance in report** | Tag each source: `seed | citation_graph | web_discovery | zotero | links` |

**Files:** `static/js/research/panel.js`, `routes/research_routes.py`, `deep_research.py`, `visual_report.py`.

**Deliverable:** Compare run with Zotero enabled does **not** hit catalog unless user checks “Search my library”.

**Acceptance:**

- [ ] Default compare + Zotero on: zero `zotero_source` findings unless explicit library search.
- [ ] “Broad overview” + seeds: may fetch foundational papers (BLAST-class) without user typing “foundational”.
- [ ] Report source cards show retrieval channel.

</details>

---

## Phase RT6 — Dynamic budget & stop criteria

> **Superseded by LDR** — agent iteration + panel `max_rounds` / `max_time`. Do not implement score-proportional URL budget in `deep_research.py`.

<details>
<summary>Original RT6 spec (historical — IterResearch only)</summary>

**Goal:** Spend fetch/extract tokens on high-confidence hits, not fixed 3 URLs × queries.

| Task | Detail |
|------|--------|
| **Score-proportional URL budget** | If overlap &gt; 0.35, allow extra fetch slot (up to cap 8/round) |
| **Early stop on saturation** | Stop discovery when each sub-question has ≥2 independent sources above threshold |
| **Stop prompt uses coverage** | `_should_stop` sees sub-question coverage map, not only synthesis prose |
| **Token budget awareness** | Skip low-score web fetch when registry already has N high-quality sources |

**Deliverable:** Compare run analyzes fewer irrelevant URLs; same or better citation quality.

</details>

---

## Suggested priority order

### Active (LDR track)

```
L0 (partial) → L1 engines → L2 LangGraph + panel toggles → L3 output parity
```

See [`deep-research-ldr-migration.md`](deep-research-ldr-migration.md#migration-phases).

### Legacy IterResearch (maintenance only — L5 shipped)

```
src/research/iterresearch.py   ← legacy loop (fallback when LDR unavailable)
src/deep_research.py           ← deprecated shim; do not add new imports
```

**Do not start:** RT2, RT4, RT6 on IterResearch — superseded by LDR L1–L2.

---

## Open decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | Minimum OpenAlex hits before skipping web similar search? | **3** on-topic hits |
| 2 | Embed model: local vs API? | **Reuse catalog embed if present**; else lexical-only |
| 3 | Compare mode: require anchor overlap for *all* non-seed sources? | **Yes** — plan anchor or embed &gt; threshold |
| 4 | Show rejected sources in report appendix? | **No** — progress log only (debug setting) |
| 5 | Historical papers: max soft age penalty? | **No penalty** — only positive tie-break for &lt;5 years |
| 6 | Semantic Scholar with seeds? | **No recommendations.** Optional keyword **search** only (settings-gated, P2). |
| 7 | OpenAlex `related_to`? | **Default off** — same noise class as S2 recommendations |
| 8 | OpenAlex primary expansion? | **Yes** — `search`, seed `referenced_works`, `cites` (cited-by) |
| 9 | Static method whitelists (`esm3`, `blast`, …)? | **Remove** — plan `anchor_terms` only |

Record changes in this table when product decides otherwise.

---

## Acceptance criteria (“retrieval done”)

Use with parent roadmap acceptance criteria. **Source discovery** items satisfied by LDR L2–L3, not IterResearch RT2/RT6.

- [x] No auto-seeding from Zotero catalog or Links graph.
- [x] Web research ranking does not weight SERP recency by default.
- [x] FuseGO-class off-topic paper rejected in compare fixture (interim lexical gate).
- [x] S2 recommendations disabled when seeds attached or compare/similar_papers mode.
- [x] Structured plan drives keywords (`research_retrieval_plan.py`) — RT3 partial.
- [x] Plan `avoid_topics` replaces hardcoded GO/structure tables — RT0b partial.
- [ ] Hardcoded `_GENERIC_SCIENCE_TERMS` shrink / non-comp-bio fixture (RT0b remainder).
- [ ] LDR agent: S2/OpenAlex **keyword search** only; zero `forpaper` / `related_to` (L1–L2).
- [ ] All [panel toggles](deep-research-roadmap.md#panel-toggles-both-engines) honored when `research_engine=ldr` (L2).
- [ ] Progress UI shows rejection reasons (RT1 → LDR progress mapper).
- [ ] Optional embed overlay without FuseGO regressions (P2 — not blocking LDR v1).

---

## How to use in future chats

Examples:

- *“Wire LDR Phase L2 per docs/deep-research-ldr-migration.md; preserve panel toggles”*
- *“Apply retrieval policy from deep-research-retrieval-roadmap.md to LDR agent prompt”*
- *“Add RT1 rejection events to the research progress stream (both engines)”*
- *“Review deep-research-ldr-migration.md and pick the next unblocked L-phase”*

**Do not use:** *“Implement RT2 OpenAlex in research_similar_papers.py”* — superseded by LDR.

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-01 | Initial roadmap from retrieval audit + user policy lock-in; RT0 partial shipped |
| 2026-06-01 | Disabled S2 recommendations for seed/compare runs; subfield mismatch gate; fixed anchor “representation” leak |
| 2026-06-02 | RT0b hardcoding audit; S2 deprioritized; OpenAlex strategy revised (`search`/refs/cited-by yes, `related_to` no); RT2/RT3/RT0b reordered |
| 2026-06-01 | **LDR supersession:** RT2/RT4/RT6 marked legacy-only; active track → [`deep-research-ldr-migration.md`](deep-research-ldr-migration.md); panel toggles cross-linked |
