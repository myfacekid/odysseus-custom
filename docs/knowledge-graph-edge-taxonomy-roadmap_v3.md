# Knowledge Graph Edge Taxonomy Roadmap

**From wikilinks to cognitive edges: a universal linking vocabulary for the personal knowledge graph.**

**Status:** **T0–T2 + T3 shipped** on `feature/projects` (2026-06-01).

**Last updated:** 2026-06-01

**Branch context:** Land on `main` after Projects Phases A–E + tabbed workspace (G1–G8) merge. Projects already surface link direction and edge kind in the UI — this roadmap extends that model with richer semantics.

**Use this doc when starting work:** *"Follow docs/knowledge-graph-edge-taxonomy-roadmap_v3.md Phase T0"* or *Phase T1*.

**Last updated:** 2026-06-08

**Related docs:**

| Doc | Relationship |
|-----|----------------|
| [`projects-roadmap.md`](projects-roadmap.md) | Projects use explicit graph links as the **breadth boundary**; today almost all project edges are `related`. |
| [`projects-ui-roadmap.md`](projects-ui-roadmap.md) | Links tab shows **direction** (←/→), **edge kind**, and **node type** — UI ready for more kinds. |
| [`paper-token-retrieval-roadmap_v1.md`](paper-token-retrieval-roadmap_v1.md) | Ad-hoc comparison labels ("Builds on", "Challenges") map to this taxonomy in T3; `summarizes` edge planned there — see edge families below. |
| [`learned-graph-connections-roadmap_v1.md`](learned-graph-connections-roadmap_v1.md) | **Next:** skills-style learned connections — pop-up Accept/Reject/Review later, Brain inbox, DR propose-not-write (L1–L6). |
| [`deep-research-roadmap.md`](deep-research-roadmap.md) | Research sessions create `research:` nodes with `related` edges today — candidate for typed output in T3. |

---

## Problem

Wikilinks and hyperlinks are the null hypothesis of knowledge graphs: a link is a link. But human cognition doesn't work that way. When we recall one idea from another, the connection has valence, direction, and affect. A paper that *refutes* your approach feels different from one that *extends* it. A task that *depends on* another carries different weight than one merely *related* to it.

Without typed **semantic** edges, the agent must traverse every link, read every target, and re-derive the relationship from scratch — burning context on rediscovery instead of reasoning.

### Current state in Nobody (2026-06)

Nobody already has a working knowledge graph (`src/knowledge_graph.py`) and project-scoped linking — but **manual semantic vocabulary is thin** and **relationship metadata is mostly not persisted**.

### On-disk storage (JSONL, not SQLite)

Graph data is **file-backed JSON Lines** under `data/knowledge/users/{owner}/` — one JSON object per line, not a single JSON blob and not in the session DB.

| File | Role |
|------|------|
| `nodes.jsonl` | Search index: tasks, papers, documents, projects, etc. |
| `manual_edges.jsonl` | **Source of truth for user/agent links** (`add_graph_link`, UI picker, accept on suggest) |
| `edges.jsonl` | **Merged view**: inferred edges + manual edges (rebuilt by `_sync_edges_from_manual` and full reindex) |
| `manifest.json` | `schema_version`, counts, `updated_at` |

**Write path today:** `POST /api/knowledge/links` → `add_graph_link()` → append to `manual_edges.jsonl` → `_sync_edges_from_manual()` rewrites `edges.jsonl`. Inferred kinds (`parent`, `wikilink`, `in_collection`) are produced only during `rebuild_owner_graph()` and merged in — they are **not** stored in `manual_edges.jsonl`.

**Row shape today (manual):**

```json
{"from": "project:abc", "to": "paper:XYZ", "kind": "related", "source": "manual"}
```

**Row shape today (inferred, in merged `edges.jsonl`):**

```json
{"from": "task:uuid", "to": "task:parent-uuid", "kind": "parent"}
```

**Uniqueness:** `(from, to, kind)` — the same pair may have **multiple edges** with different kinds (e.g. `relates` + `supports`).

**Critical gap:** `suggest_graph_link()` accepts `reason` and the UI shows it on the suggest card (`static/js/knowledge.js`), but **`add_graph_link()` / `save_manual_edges()` strip all fields except `from`, `to`, `kind`, `source`** — reasons are lost on accept. T0 must fix round-trip before T1 mandates reasons on new links.

**Node types in production:** `task`, `document`, `memory`, `skill`, `note`, `paper`, `collection`, `research`, `project`.

**Edge kinds in schema today:**

| Kind | How it appears | Manual? | Role today |
|------|----------------|---------|------------|
| `link` | Generic manual link | ✅ | Default in link picker; undifferentiated |
| `related` | Thematic association | ✅ | **Default for almost all project→paper/research/doc links** |
| `supports` | Evidence / confirmation | ✅ | Rare; agent can suggest via `suggest_link` |
| `parent` | Task → parent goal | ❌ inferred | One Thing goal hierarchy (`src/one_thing.py`) — **not** paper lineage |
| `wikilink` | Note ↔ note | ❌ inferred | Parsed from markdown / vault sync |
| `in_collection` | Item in Zotero collection | ❌ inferred | Catalog sync |

**Agent surface:** `search_knowledge` actions `link` / `suggest_link` accept only `link`, `related`, `supports` (`src/tool_schemas.py`, prompt in `src/agent_loop.py`). `reason` is in the tool schema for suggest but **not persisted** on link create (`routes/knowledge_routes.py` → `GraphLinkCreate` has no `reason` field).

**Projects workspace (shipped on `feature/projects`):**

- Links tab lists incoming **and** outgoing edges with direction icon, kind badge, and node-type badge (`static/js/projects/index.js` → `EDGE_KIND_LABELS`).
- Link picker offers the three manual kinds (`static/js/knowledge.js` → `LINK_KIND_OPTIONS`).
- Project chat preamble lists linked nodes with kind inline (`src/project_context.py` → `_format_link_row`).
- [`projects-roadmap.md`](projects-roadmap.md) deferred a dedicated `in_project` kind — "until stricter semantics than `related` are needed." **This taxonomy is that stricter semantics.**

**External agent skills (not shipped in this repo):**

- Cursor skills such as `link-new-paper-to-existing-knowledge-graph` and `zotero-paper-concept-extraction-and-linking` may use the same three manual kinds when run in the IDE — they are **prompt guidance only** until T0/T1 land in Nobody's graph code and API.
- Paper Token Retrieval roadmap — "Builds on / Challenges / Aligns with" labels and `compare_papers` / `summarizes` are **draft only** ([`paper-token-retrieval-roadmap_v1.md`](paper-token-retrieval-roadmap_v1.md)); none of those tools or edge kinds exist in `src/` today.
- Deep Research — `research:{session}` nodes auto-linked with flat `related` edges via `src/research_graph.py` → `sync_research_graph_links()` (no typed stance, no reason).

**Gap:** Users and agents can say *that* two things are connected, but rarely *how* — beyond a weak `supports` and an overloaded `related`. Structural edges (`parent`, `wikilink`, `in_collection`) solve hierarchy and syntax, not argumentative or causal stance between papers, scripts, and tasks.

---

## Nobody capability baseline (2026-06 audit)

Use this table when scoping T1–T3 — **do not assume features that are only described in other roadmaps.**

| Area | Shipped today | Not built yet |
|------|---------------|---------------|
| **`search_knowledge` actions** | `search`, `read`, `neighbors`, `suggest_link`, `link`, `unlink`, `rebuild`, **`merge_subgraph`** (`src/knowledge_graph.py` → `execute_knowledge_tool`) | kind-filtered `neighbors`, activation-weighted traversal |
| **Manual edge kinds** | Five semantic slugs + legacy `link`/`related` read aliases (`src/edge_taxonomy.py`, `src/knowledge_graph.py`) | T1: picker reason field, preamble sort |
| **Reason on edges** | Persisted on `add_graph_link` / research auto edges / API POST | T1: suggest accept passes reason from card |
| **Suggest → accept flow** | SSE card + accept POST includes `reason` | Batch review table (T2) ✅ |
| **Link UI** | Five kinds + reason field on picker; hub rows show reason | — |
| **Project preamble** | Kind-aware sort, reason in row, cap 8 weak `relates` | — |
| **Search expansion** | `expand_hops` returns neighbors + `expanded_links` (kind, reason) | Kind-filtered hop expansion in search API |
| **Deep Research → graph** | `upsert_research_node` + auto `research:{id}` → seed papers as `related` (`RESEARCH_EDGE_SOURCE`) | Typed completion edges; LLM-derived stance per seed |
| **Paper retrieval** | R0–R3 shipped: tiered read, sections, `summarizes`, `compare_papers` | — |
| **Concept / merge pipeline** | — | Paper-local subgraph extraction, boundary matching, batch merge API/UI |
| **In-repo skills** | Graph agent uses `search_knowledge` + prompts in `src/agent_loop.py` | No `link-new-paper-*` skill files in this repository |

**Phase dependency chain:** T0 (schema) → T1 (human/agent single-link paths) → T2 (batch merge — **requires a producer of candidate edges**, not in repo) → T3 (typed automation from retrieval/DR — **requires Paper Token Retrieval R2+ and DR graph changes**).

---

## North star

> **Every semantic edge in the knowledge graph carries a typed verb drawn from a small, universal vocabulary grounded in cognitive primitives. The agent traverses edges selectively — following excitatory paths, avoiding inhibitory ones — and the user links things the same way whether they're papers, tasks, documents, or memories.**

**Not in scope for this vocabulary:** replacing structural/inferred edges. Task goal `parent`, markdown `wikilink`, and collection membership stay as separate, machine-maintained kinds.

---

## Two families of edges

| Family | Examples | User picks type? | This roadmap |
|--------|----------|------------------|--------------|
| **Structural / inferred** | `parent` (task goals), `wikilink`, `in_collection` | No — derived from task UI, markdown, Zotero sync | Out of scope — keep as-is |
| **Semantic / manual** | Derives from, Refutes, Supports, Relates, Depends on | Yes — link picker, agent `suggest_link`, merge UI | **Replace** `link` / `related` / `supports` |
| **Artifact / derived (future)** | `summarizes` (paper → note summary, Paper Token Retrieval) | No — created by summary pipeline | **Separate kind**, not one of the five; do not overload `supports` |

Projects UI already treats semantic kinds as first-class labels. T1 extends `EDGE_KIND_LABELS`, link picker, and preamble formatting to the five-type set.

**Wikilink policy (T1):** Vault `[[links]]` stay `wikilink` (inferred). Do **not** auto-upgrade to typed edges. Agent may *suggest* a typed edge when a wikilink clearly implies stronger semantics — user confirms via suggest card.

---

## Cognitive foundations

This taxonomy is not an engineering convenience. It is grounded in how biological memory organizes experience.

### Toulmin's argument model (1958)

Every claim sits on **grounds** (data), backed by **warrants** (reasoning), and is open to **rebuttals**. Papers are arguments, and the relationships between them — "this provides the warrant for that," "this rebuts that claim" — are argumentative, not just associative. Our edge types encode argumentative stance.

### Spreading activation (Collins & Loftus, 1975)

In semantic memory, activation doesn't spread uniformly. It spreads along semantically weighted paths. A "refutes" edge should *inhibit* downstream nodes, not activate them. A "derives from" edge should carry inheritance. Typed edges let activation spread intelligently — the way a brain does, and the way an agent should.

### Dynamic memory & expectation failure (Schank, 1982)

Knowledge is indexed around failure and expectation violation. When something *refutes* an expectation, it gets indexed differently than when it confirms one. Contradiction is a primary organizational axis in memory, not a subtype of association. "Refutes" deserves its own type for the same reason the brain gives it special treatment.

### Peirce's triadic sign (semiotics)

A wikilink is a sign without an interpretant — a broken triangle. The link type is the sign, but the user needs the **one-line explanation** as the interpretant to complete the triad. Type + sentence together form a complete semiotic relationship. A wikilink says "there is a connection — go read the target." A typed edge with a one-liner says "this *is* the connection — read the target only if it's relevant."

---

## The five universal edge types

Storage/API slugs (snake_case) shown in parentheses.

| # | Label | Slug | Direction | Cognitive primitive | Meaning |
|---|-------|------|-----------|---------------------|---------|
| 1 | **Derives from** | `derives_from` | A → B | Causal origin | A extends, implements, adapts, forks, or was inspired by B |
| 2 | **Refutes** | `refutes` | A → B | Contradiction | A contradicts, disproves, or invalidates B |
| 3 | **Supports** | `supports` | A → B | Evidence | A provides evidence for, confirms, or strengthens B |
| 4 | **Relates** | `relates` | A ↔ B | Thematic co-occurrence | Same topic; no stronger claim |
| 5 | **Depends on** | `depends_on` | A → B | Enablement | A requires B to function or be understood |

### Migration from today's manual kinds

| Old kind | New default | Notes |
|----------|-------------|-------|
| `link` | `relates` | Generic link → honest weak bucket |
| `related` | `relates` | Same semantics, clearer name |
| `supports` | `supports` | **Keep slug** — already aligned |

Legacy rows without `reason` remain valid after migration. **New** manual links (T1+) should require `reason` except quick `relates` from the picker (optional but encouraged).

### Agent type picker (decision guide)

Use when proposing or creating semantic edges:

| Situation | Type |
|-----------|------|
| Method lineage, fork, implements, inspired by | `derives_from` |
| Contradicts, disproves, invalidates a claim | `refutes` |
| Evidence for, confirms, corroborates | `supports` |
| Same topic, no directional claim | `relates` |
| Cannot proceed without reading/using B first | `depends_on` |
| Unsure between `relates` and something stronger | **`relates`** + honest reason — do not guess `supports` |

### What makes these different from wikilinks

| Property | Wikilink / `related` today | Typed edge + one-liner |
|----------|----------------------------|-------------------------|
| Pre-retrieval filtering | None — must read target to discover relationship | Selective traversal by type |
| Agent context cost | Read all targets, re-derive relationship | Skip irrelevant targets |
| Cross-type reasoning | Impossible without case-by-case logic | Uniform traversal rules |
| User mental model | "This is linked to that" | "This *derives from* that because…" |

### Activation rules per type

| Type | Activation spread | Agent behavior |
|------|-------------------|----------------|
| **Derives from** | Excitatory, inheriting | Follow when tracing lineage, method origin, or intellectual debt |
| **Refutes** | Inhibitory | Follow when looking for challenges, contradictions, or alternative interpretations |
| **Supports** | Excitatory, confirming | Follow when seeking evidence, corroboration, or convergent findings |
| **Relates** | Neutral, weak | Follow only when exploring broadly; the weakest traversal signal |
| **Depends on** | Excitatory, prerequisite | Follow when understanding preconditions, requirements, or build order |

---

## Universal applicability across node types

### Papers

| Edge | Example |
|------|---------|
| Derives from | Smith 2025 adopts Chen 2024's optimization procedure but relaxes sparsity |
| Refutes | Lee 2024 finds Park's claimed 12% improvement disappears under a different split |
| Supports | Gupta 2025 independently confirms Morales' scaling-law conclusion |
| Relates | Both papers study small-batch training in transformers |
| Depends on | Understanding Smith 2025 requires reading Chen 2024's appendix |

### Projects (breadth boundary)

| Edge | Example |
|------|---------|
| Derives from | Project methodology derives from Smith 2025's training recipe |
| Refutes | Linked benchmark note refutes a README claim in the project cwd |
| Supports | Linked ablation paper supports the project's main hypothesis |
| Relates | Paper shares topic with project but no causal claim (today's default) |
| Depends on | Project analysis depends on linked methods paper before code makes sense |

### Documents (scripts, notes, code)

| Edge | Example |
|------|---------|
| Derives from | `train_v2.py` was refactored from `train_v1.py` |
| Refutes | Benchmark notes contradict the README's performance claim |
| Supports | Test results confirm the implementation matches the paper |
| Relates | Two design docs address the same architecture decision |
| Depends on | `eval.py` requires `model_checkpoint.pkl` to run |

### Tasks

| Edge | Example |
|------|---------|
| Derives from | "Implement Chen's method" derives from reading Chen 2024 |
| Refutes | Task result invalidates the assumption in a linked research question |
| Supports | "Run ablation study" supports validating the main result |
| Relates | Two tasks are about the same feature but independent |
| Depends on | "Deploy model" depends on "Run benchmarks" completing |

*Task goal hierarchy stays on `parent` edges (One Thing), not `depends_on` — different semantics.*

### Skills / memories / research

Same five types apply. Deep Research output should emit typed edges to seed papers and linked projects, not only `related`.

---

## Relationship to existing roadmaps and skills

### Projects (`feature/projects`)

| Today | After taxonomy |
|-------|----------------|
| Project links almost always `related` | User/agent pick among five types + reason |
| Links tab shows kind + direction | Same UI; richer `EDGE_KIND_LABELS` and picker |
| Preamble: `_format_link_row` shows kind | Include `reason` when present; traversal hints in agent prompt |
| Deferred `in_project` kind | Superseded by `depends_on` / `derives_from` where appropriate |

### Paper Token Retrieval roadmap

**Today:** Not implemented — comparison labels and tools exist only in [`paper-token-retrieval-roadmap_v1.md`](paper-token-retrieval-roadmap_v1.md).

**Target mapping (when R3 ships):**

- "Builds on" → **Derives from**
- "Challenges" → **Refutes**
- "Aligns with" → **Relates** or **Supports** (when evidence direction exists)

### Deep Research

**Today:** `src/research_graph.py` → `sync_research_graph_links()` appends `research:{session}` → target edges with kind **`related`** only (`RESEARCH_EDGE_SOURCE`).

**After T3 (partial, no Paper Token Retrieval required):** Completion hook may emit typed edges (`supports`, `refutes`, `derives_from`) to seed papers and linked `project:{id}` when the report states a clear stance — requires T0 kinds + LLM/rules over the saved report JSON.

### Skills (external — update when T1 ships)

External Cursor skills that link papers should adopt the five types + reason **after** T0/T1 change Nobody's API and tool enum. Until then, agents in Nobody only see `link` / `related` / `supports` in `src/tool_schemas.py`.

---

## Merging smaller networks into the larger graph

Concept-extraction would produce a **paper-local subgraph** that must merge into the **global knowledge graph**. **Nobody has no concept-extraction or merge pipeline today** — only single-edge `suggest_link` (one card) and manual picker links. T2 is the first time batch merge exists in the product.

### Merge procedure (target design for T2)

1. **Identify boundary nodes.** For each concept document in the new subgraph, search the global graph for overlapping topics.
2. **Propose typed edges.** For each match, propose one of the five types with a one-line reason.
3. **User confirms.** Merge table: proposed edge, type, explanation, accept/reject/edit (extend Projects link-review patterns).
4. **Union, not replacement.** Existing edges preserved; conflicting `supports` + `refutes` to same target flagged.
5. **Transitive inference.** Agent queries like "What papers support the assumptions underlying Task X?" traverse typed paths.

Typed edges make merge cheaper: the agent can filter proposals ("only `refutes` or `supports`; skip `relates` unless no stronger edge exists").

**Interim (before T2):** An agent can call `suggest_link` repeatedly — one edge per user confirmation. Works for small sets; does not scale to 10+ boundary edges without T2 batch UI.

---

## Edge record contract (T0 deliverable)

Target shape for **manual** rows in `manual_edges.jsonl` (merged into `edges.jsonl` with same fields):

```json
{
  "from": "project:abc",
  "to": "paper:XYZ",
  "kind": "derives_from",
  "reason": "Project training recipe follows Smith 2025 §3",
  "source": "user",
  "confidence": 1.0,
  "created_at": "2026-06-07T12:00:00+00:00",
  "updated_at": "2026-06-07T12:00:00+00:00"
}
```

| Field | Required | Notes |
|-------|----------|-------|
| `from`, `to` | ✅ | Canonical node ids (`paper:key`, `project:id`, …) |
| `kind` | ✅ | One of five semantic slugs **or** legacy until migration completes |
| `reason` | T1+ for new links | Max ~280 chars; optional on migrated rows |
| `source` | ✅ | `user` \| `agent` \| `manual` (legacy alias for user) |
| `confidence` | Optional | 0–1; default `1.0` when user confirms; agent suggest may be `<1` |
| `created_at`, `updated_at` | Optional | ISO-8601 UTC; set on write |

**Uniqueness key:** `(from, to, kind)` — unchanged. Adding `refutes` does not remove an existing `relates` on the same pair.

**Inferred rows** in merged `edges.jsonl` may omit `reason` / `confidence`; only `from`, `to`, `kind` required. `_merge_edge_lists()` must preserve optional manual fields when merging.

**Code touch points (T0):** `KnowledgeEdge` dataclass (or retire for manual rows), `load_manual_edges`, `save_manual_edges`, `_merge_edge_lists`, `add_graph_link`, bump `SCHEMA_VERSION` + `manifest.json`.

### Allowed semantic kinds by node-type pair (v1)

Blank = discouraged (agent should use `relates` only if user insists). ✅ = common.

| From → To | `derives_from` | `refutes` | `supports` | `relates` | `depends_on` |
|-----------|----------------|-----------|------------|-----------|--------------|
| paper → paper | ✅ | ✅ | ✅ | ✅ | ✅ |
| paper → document/note | ✅ | ✅ | ✅ | ✅ | ✅ |
| project → paper/research/doc | ✅ | ✅ | ✅ | ✅ | ✅ |
| project → project | | | | ✅ | |
| task → paper/doc/research | ✅ | ✅ | ✅ | ✅ | ✅ |
| task → task | | | ✅ | ✅ | ✅ |
| document → document | ✅ | ✅ | ✅ | ✅ | ✅ |
| research → paper | ✅ | ✅ | ✅ | ✅ | ✅ |
| memory/skill → * | | | ✅ | ✅ | |

Task **goal hierarchy** remains `parent` (inferred), not `depends_on`. Collection membership remains `in_collection`.

---

## Implementation phases

### Phase T0 — Vocabulary spec + JSONL schema

**Goal:** Persist richer manual edges on disk; migrate kinds; do not break reindex or inferred edges.

| Item | Details |
|------|---------|
| Finalize five types | Slugs, labels, activation rules (this doc) |
| **`manual_edges.jsonl` schema** | Round-trip `reason`, `confidence`, `source`, timestamps — fix `save_manual_edges` whitelist |
| **`_merge_edge_lists`** | Preserve manual metadata when building `edges.jsonl` |
| **`_EDGE_KINDS` / `_MANUAL_EDGE_KINDS`** | Add `derives_from`, `refutes`, `relates`, `depends_on`; keep `supports`; deprecate `link`, `related` (read legacy, write new slugs only) |
| **`add_graph_link`** | Accept optional `reason`, `confidence`, `source`; pass through to save |
| **`GraphLinkCreate`** | `routes/knowledge_routes.py` — add optional `reason`, `confidence` on POST `/api/knowledge/links` |
| **Migration script** | One-time per owner: rewrite `manual_edges.jsonl` — `link`/`related` → `relates`; idempotent on `(from,to,kind)` |
| **Manifest** | Bump `SCHEMA_VERSION`; document in manifest or README under `data/knowledge/` |

**Out of scope for T0:** UI picker changes, agent prompt, preamble sorting, `neighbors` filters — those are T1.

**Deliverable:** Tests prove reason survives save/load/sync; migration idempotent; rebuild leaves inferred kinds untouched.

**Key files:** `src/knowledge_graph.py`, `routes/knowledge_routes.py`, `tests/test_knowledge_graph.py`, new `scripts/migrate_edge_taxonomy.py` (or pytest fixture migration).

---

### Phase T1 — Agent, API, UI, and context policy (**shipped**)

**Goal:** All **new** manual links use five types + reason end-to-end; agent and project preamble consume them.

| Item | Status |
|------|--------|
| **`search_knowledge` tool enum** | Five semantic slugs + `kinds` filter on neighbors |
| **`suggest_link`** | **Requires** `reason`; typed kinds validated |
| **`link` action** | Passes `reason` to `add_graph_link` |
| **Agent prompt** | Vocabulary table + decision guide + inhibitory `refutes` note |
| **`expand_hops`** | Returns `expanded_links` with kind + reason |
| **Link picker** | Five kinds + reason field; human labels |
| **Suggest accept** | POST includes `reason` from card |
| **Projects Links tab** | Reason second line; kind filter dropdown |
| **Links hub rows** | Kind label + reason line |
| **Project preamble** | Reason in row; kind-aware sort; cap 8 weak `relates` |

**Key files:** `src/project_context.py`, `static/js/knowledge.js`, `static/js/projects/index.js`, `src/knowledge_graph.py`, `src/agent_loop.py`, `routes/knowledge_routes.py`.

---

### Phase T2 — Batch merge API + review UI (**shipped**)

**Goal:** Many proposed boundary edges reviewed in one step — not one suggest card at a time.

| Item | Status |
|------|--------|
| **`merge_subgraph` action** | Shipped — `search_knowledge` preview/apply + `POST /api/knowledge/merge/preview` + `/apply` |
| **Merge table UI** | Shipped — Links hub **Batch merge** button + modal; Projects Links rail entry; opens from `compare_papers` / agent SSE |
| **Conflict detection** | Shipped — `supports` vs `refutes` on same `(from, to)` flagged in preview |
| **Partial accept** | Shipped — checkbox per row; skipped rows do not write |
| **Duplicate handling** | Shipped — skip identical edge; **update reason** when kind matches |

**Edge producers (no LLM pipeline required):** `compare_papers` `suggested_edges`, JSON paste, agent `merge_subgraph` preview (≤20 proposals).

**Key files:** `src/graph_merge.py`, `src/knowledge_graph.py`, `routes/knowledge_routes.py`, `static/js/graph_merge.js`, `static/js/knowledge.js`, `tests/test_graph_merge.py`.

**Out of scope (unchanged):** Concept-extraction LLM pipeline — T2 only consumes proposal lists.

---

### Phase T3 — Retrieval + Deep Research typed edges (**shipped core**)

**Prerequisite:** T0 kinds on disk ✅; Paper Token Retrieval R2/R3 ✅.

| Item | Status today | Notes |
|------|--------------|-------|
| **Paper comparison labels** | `compare_papers` output groups **Builds on / Challenges / Aligns with** → five types | `src/paper_compare.py` + `suggested_edges` payload |
| **`compare_papers` tool** | Shipped (R3) | Side-by-side + taxonomy section |
| **`summarizes` edges** | Shipped (R2) | Pipeline kind separate from five cognitive types |
| **Deep Research session edges** | `build_research_graph_edges()` + `sync_research_graph_links()` | Typed `research→paper` + compare-mode `paper→paper` with reason |
| **`neighbors` kind filter** | `kinds` param on tool + inhibitory `refutes` formatting | Shipped in `execute_knowledge_tool` |
| **Activation / inhibitory hints** | `format_edge_for_agent()` in neighbor output | Agent prompt updated |
| **Zotero bibliographic cites** | Not implemented | Deferred |

**Key files:** `src/edge_taxonomy.py`, `src/research_typed_edges.py`, `src/research_graph.py`, `src/paper_compare.py`, `src/knowledge_graph.py`.

**Remaining (T1):** Link picker reason field, preamble reason/sort, full agent vocabulary block in all paths.

---

## Testing strategy

| Phase | Tests |
|-------|-------|
| T0 | Kind validation; `reason` round-trip through save → sync → load; migration idempotent; inferred `parent`/`wikilink`/`in_collection` unchanged after rebuild |
| T1 | API POST with reason; suggest requires reason; preamble sort/filter/cap; picker options; expanded_links on search |
| T2 | **`tests/test_graph_merge.py`** — batch merge partial accept; conflict flag; duplicate reason update; apply skip |
| T3 | DR hook writes typed edge when fixture report includes stance; `compare_papers` taxonomy section; **`tests/test_edge_taxonomy.py`**, **`tests/test_research_typed_edges.py`** |

---

## Open questions

| # | Question | Lean |
|---|----------|------|
| 1 | Should `relates` be symmetric (A ↔ B) while the other four are directional? | Yes. Store one directed row; UI may show ↔ for display. |
| 2 | Can an edge carry multiple types? | No. One edge = one type + one reason. |
| 3 | Should there be a `refines` type distinct from `derives_from`? | No. Specificity lives in the reason string. |
| 4 | How does confidence scoring work? | Agent-suggested 0–1; user-confirmed = 1. |
| 5 | Should edges have temporal validity? | Not in v1. |
| 6 | What happens to `parent`, `wikilink`, `in_collection`? | **Keep.** Separate from semantic taxonomy. Do not migrate task `parent` to `depends_on`. |
| 7 | Replace or supplement `link` / `related` / `supports`? | **Replace** manual kinds via migration. `supports` slug unchanged. |
| 8 | Project-scoped `in_project` kind from projects-roadmap? | **Drop** — use `depends_on` or `derives_from` instead. |
| 9 | Where does `summarizes` (paper → note) live? | **Separate artifact kind** from Paper Token Retrieval — not one of the five cognitive types. |
| 10 | Store edges in SQLite? | **No** — stay JSONL under `data/knowledge/`; optional index cache later. |
| 11 | When can T2 start? | After T1; **plus** any edge producer (even a script). No producer → stay on repeated `suggest_link`. |
| 12 | When can T3 start? | After T0+T1; DR typed edges can proceed independently of Paper Token Retrieval; `summarizes` / `compare_papers` wait for R2/R3. |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-07 | Initial draft: cognitive foundations, five-type vocabulary, merge protocol, T0–T3. |
| 2026-06-07 | **v3.1:** Ground in Nobody's current graph schema, Projects UI, and agent tools; distinguish structural vs semantic edges; map migration from `link`/`related`/`supports`; position as next initiative after `feature/projects`. |
| 2026-06-07 | **v3.2:** Document JSONL dual-file storage (`manual_edges.jsonl` + merged `edges.jsonl`); edge record contract; allowed-pairs matrix; agent decision guide; `reason` not persisted today; expand T0/T1 with concrete files, API, preamble policy; T2/T3 prerequisites and `summarizes` placement. |
| 2026-06-01 | **T1 shipped:** link picker reason field, suggest accept persists reason, preamble kind sort + relates cap, neighbors/search edge metadata, agent vocabulary block. |
