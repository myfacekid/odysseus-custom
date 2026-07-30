# Projects Roadmap

Living plan for **Projects** — a new app section and graph node type that bridges knowledge work (papers, research, documents, tasks) with an **IDE-like workspace** (files, Python editing, execution, project-scoped chat).

Use this doc when starting future chats: *"Follow docs/projects-roadmap.md Phase X"*.

**Branch:** `feature/projects` (first step toward IDE work; projects and IDE functionality are intentionally intertwined).

**Last updated:** 2026-06-01

**Status:** Phase D complete. Phase E narrowed: E1 done; **E2/E3 skipped**; E4/E5 (Links hub + stale links) largely done — verify UX.

**Phase E — scope revision (2026-06-01):** Skip Zotero collection bulk-import and Library-by-project filter — curated explicit links only; bulk paper edges would flood agent context at current preamble limits. Prioritize Links hub navigation from project workspace + stale-link cleanup UI.

**Phase E — research → project (2026-06-01):** Compare/gap project picker in research panel; post-complete confirm dialog; manual “Add to project” on done jobs; `project_id` on `/api/research/start` + saved JSON.

**Phase E — agent tool context (2026-06-01):** Project preamble tool-routing table + active editor file injection (`active_project_file`); auto agent-mode when cwd file open.

**Phase D — tool routing (2026-06-01):** `apply_session_tool_policy()` centralizes depth denylist in chat routes; integration tests verify schema filter, execution blocks, and `_build_system_prompt` preamble with linked research.

**Phase D — chat visibility fix (2026-06-01):** Dock only `#chat-history` in grid; input bar stays below workspace; skip fade in project workspace; larger chat grid row.

**Phase D — context injection (2026-06-01):** `src/project_context.py` — linked graph summaries in project session preamble; stale links marked; truncated at 4k chars / 24 links.

**Phase D — chat sidebar (2026-06-01):** `static/js/projects/chatSidebar.js` — list/create/rename project chats via project session API; docks main chat UI in workspace region; `selectSession({ inProjectWorkspace: true })` avoids closing workspace.

**Phase C — safety UX (2026-06-01):** Save-before-run + first-run intro in run panel; runner stdout cap 100k; agent tool result cap 10k (`output_truncated`); write-before-run guidance in project session prompt.

**Phase C — agent tool (2026-06-01):** `run_project_script` in `tool_execution.py` — project session only; same backend as Run API; `.py` path + optional args JSON/lines; agent output capped at 10k with `output_truncated` flag.

**Phase C — run panel UI (2026-06-01):** `static/js/projects/runPanel.js` — Run on editor toolbar (`.py` only), stdout/stderr panel, re-run/clear/copy, save-before-run prompt, first-run intro per project session.

**Phase C — network policy (2026-06-01):** `project_run_allow_network` in `settings.py` (default **false**). Subprocess gets minimal env + stripped proxy/TLS vars; `NOBODY_PROJECT_RUN_NETWORK=0|1` marker; `network_allowed` in run response. Not kernel-level socket blocking — see open question #6.

**Phase B — agent tools (2026-06-01):** `read_project_file` / `write_project_file` in `tool_execution.py` — project session only; path relative to cwd; traversal rejected.

**Phase B — agent prompt block (2026-06-01):** Project sessions inject three-paradigm rules + working dir in `agent_loop._build_system_prompt`.

**Phase B — file tree API (2026-06-01):**
| Endpoint | Method | Role |
|----------|--------|------|
| `/api/projects/{id}/files?path=` | GET | List immediate children (relative paths) |
| `/api/projects/{id}/file?path=` | GET | Read UTF-8 text + `modified_at` |
| `/api/projects/{id}/file` | PUT | Write/create text file |
| `/api/projects/{id}/file?path=&recursive=` | DELETE | Delete file or directory |
| `/api/projects/{id}/rename` | POST | Move/rename within cwd |
| `/api/projects/{id}/mkdir` | POST | Create directory |

All ops: owner → project → `resolve_project_path` (depth boundary only).

**Phase B — file tree UI (2026-06-01):** `static/js/projects/fileTree.js` — lazy tree, create/rename/delete.

**Phase B — editor (2026-06-01):** `static/js/projects/editor.js` — highlight.js overlay, line numbers, autosave PUT, disk conflict check via `modified_at`.

**Phase A verification (2026-06-01 audit):**

| Check | Result |
|-------|--------|
| Graph `project` node + rebuild index | ✅ |
| Re-validate cwd on list/open; persist status drift | ✅ |
| Server-host path picker + broad-path warnings | ✅ |
| Projects nav: list / create / rename / archive / change folder | ✅ |
| Workspace shell with depth/breadth labels; no run/chat UI | ✅ |
| Manual link add/remove from workspace + Links browser | ✅ |
| Open workspace from Links; project filter in graph | ✅ |
| Owner isolation (404 cross-user) | ✅ |
| ES module paths (`../ui.js`) | ✅ fixed |

---

## Mission

**Nobody Projects connects computational work to structured knowledge — so the model gets the right context, in the right place, without touching everything else.**

Research projects are complex: papers, methods, prior runs, notes, and code all matter at once. Generic IDEs and note tools keep these in separate silos. VS Code gives you files but not your literature graph. Zotero gives you citations but not your analysis workspace. Obsidian gives you links but not scoped execution and agent-safe file boundaries.

Nobody closes that gap by letting researchers work in a **project workspace** (user-chosen working directory for code and outputs) while the agent **traverses the knowledge graph in a controlled way** — papers, Deep Research sessions, documents, tasks, and collections linked to the project, not dumped into every prompt.

**Two boundaries, one experience:**

| Boundary | What it does |
|----------|----------------|
| **Graph (breadth)** | The model follows explicit links and search tools to papers, research, and notes — curated context instead of guessing or reading the whole disk. |
| **Working directory (depth)** | The model reads, writes, and runs code **only** inside the project folder — safe, predictable manipulation of computational artifacts. |

Over time this should **reduce token waste** (retrieve linked evidence on demand instead of front-loading everything) and **improve alignment** (the researcher’s literature, hypotheses, and code share one project boundary the agent can reason about).

Projects is how Nobody becomes the workspace for **computational researchers** — not another generic IDE, but literature-aware, graph-guided, locally scoped work.

---

## North star

**Projects** are a first-class section in the app (like Chats) that give the user a **scoped workspace** built on **two boundaries, one experience**:

| Boundary | Role in the product |
|----------|---------------------|
| **Graph (breadth)** | Linked papers, research, documents, tasks, and collections supply **curated context** — the model traverses the knowledge graph via explicit tools, not by reading the whole disk. |
| **Working directory (depth)** | User-chosen folder for scripts and outputs — the model **reads, writes, and runs** only here. |

Together:

- A **user-chosen working directory** on disk for scripts, outputs, and project-local files (**depth**).
- **Graph membership** linking the project to papers, research sessions, documents, tasks, notes, collections, and other knowledge nodes (**breadth**) — same linking model as the rest of Links.
- **Project-scoped chat** as its own session type, with multiple chats attached to one project (VS Code–like panel), inheriting both boundaries in tool policy and system context.
- **Python-first** edit and run inside the working directory, reusing document editor **patterns** (not the document data layer); room for Jupyter notebooks and other languages later.

Projects are the **entry point** into IDE-like behavior. Documents remain normal document nodes; they are **linked** to a project, not embedded inside it. **Graph access does not replace the cwd limit** — each boundary controls a different class of capability.

---

## Locked decisions

These are settled unless explicitly revisited in this doc.

| # | Decision | Choice |
|---|----------|--------|
| 1 | **Working directory** | **One per project**, path **selected by the user** (not auto-assigned under `data/` only). The agent/model is **restricted to direct file manipulation within that directory** (**depth boundary**). Links, Zotero, research, documents, and other graph-backed tools remain available (**breadth boundary**) — cwd limits OS-wide file access, not knowledge access. |
| 2 | **Languages & execution** | **Python first.** Reuse existing document **UI patterns** (syntax highlight, run button UX). Execution uses a **new cwd-scoped runner**, not generic `/api/shell/exec`. Future: **Jupyter notebook** compatibility; extensibility for other languages. |
| 3 | **Chat model** | **Project-scoped chat** — `project` is a **new session type**. Chats belong to a project, are listed/opened in a **VS Code–like** manner (sidebar + editor layout), and inherit project context (cwd + linked entities). |
| 4 | **Fork / branch strategy** | Work continues on **`feature/projects`** in this repo. Projects is phase 1 of a longer IDE trajectory; do not treat it as a small isolated feature. |

### Deployment assumption (clarified)

**Working directory = a path on the host where the Nobody process runs.**

| Model | Implication |
|-------|-------------|
| **Local / single-user** (primary v1 target) | User picks a real folder on the same machine; natural fit for computational researchers running Nobody locally. |
| **Remote server** | Path must exist on the **server**, not the user's laptop. Browser folder pickers do not map to client disk without a future sync/agent bridge. v1: validated text input + optional server-side browse API; document limitation in UI. |
| **Multi-user** | Every file op checks `project.owner`; user A's paths never resolve for user B. |

Document this in the working-dir picker UI so expectations stay aligned.

### Hybrid membership (manual + derived)

| Mode | Behavior |
|------|----------|
| **Manual** | User links/unlinks any graph node from the project UI or Links. |
| **Derived (opt-in)** | e.g. import edges from a Zotero collection; sync optional, never silent bulk spam. |
| **Suggested** | After research completes or when viewing related papers: “Add to project X?" — confirm, don't auto-add. |

`collection` nodes stay Zotero-synced; `project` is the user-facing workspace hub. A project may **relate** to a collection without merging types.

---

## Three “file” paradigms (product + agent rules)

Users and the model will encounter three distinct concepts. v1 must make these explicit in UI copy and project-session system prompts. They map onto the **two boundaries**: cwd paradigms use **depth**; graph paradigms use **breadth**.

| Paradigm | Boundary | What it is | Agent guidance |
|----------|----------|------------|----------------|
| **Project cwd files** | Depth | Real files under `working_dir` (`.py`, outputs, configs) | Use `read_project_file` / `write_project_file` / `run_project_script` only |
| **Documents** | Breadth (Library) | SQLite-backed Library entities (`document:{id}`) | Use `create_document` / `edit_document` for long-form Library content |
| **Graph links** | Breadth | Edges to papers, research, docs, tasks — metadata, not file contents | Use `search_knowledge`, research tools, Zotero tools |

**Rule of thumb for project sessions:**

- *Scripts, analysis code, generated outputs → cwd.*
- *Notes, reports, articles for the Library → document tools (optionally **link** doc to project).*
- *Literature → graph / Zotero / Deep Research tools (unchanged).*

Optional later: “Link as document” promotes a cwd file into the Library without duplicating by default (link, not copy).

---

## Current state (baseline)

**Graph today** (`src/knowledge_graph.py`):

- Node types: `task`, `document`, `memory`, `skill`, `note`, `paper`, `collection`, `research`.
- **No `project` type yet.** Research already upserts `research:{session_id}` and auto-links seed papers + top cited sources (`src/research_graph.py`).

**Documents / code today:**

- Library + document editor support Python (and other langs) with syntax highlighting.
- **Run** for documents: `codeRunner.js` → `POST /api/shell/exec` with `python3 -c …` — **admin-only** (`routes/shell_routes.py`).
- Documents are SQLite-backed — **not** arbitrary filesystem paths.
- `document.js` is tightly coupled to doc IDs, save-to-API, and Library flows — **partial reuse only** (see Phase B).

**Agent file access today** (`src/tool_execution.py`):

- `read_file` / `write_file` are **admin-only**, confined to `DATA_DIR`, `/tmp`, and optional `tool_path_extra_roots` — **not** user-picked project paths.
- Project sessions need **new tools** plus **tool policy** that disables escape hatches (`bash`, generic `python`, MCP filesystem, unscoped `read_file`/`write_file`) for non-admin project chats.

**Chats today** (`core/database.py`):

- Sessions have `mode` (`agent`, `chat`, `research`), `folder`, etc. — **no `project_id`**.
- Main Chats nav only; no workspace container or cwd-scoped tools.

**Gap:** No unified workspace combining cwd-scoped files (**depth**), graph links (**breadth**), scoped chat, and run panel — and no enforceable agent boundary for a user-chosen directory. Today, graph tools and file tools are not paired under a single project scope.

---

## Implementation risks & mitigations

Summary of concerns discovered during planning. Each phase below references these; **Phase 0** de-risks the hardest parts before UI polish.

| Risk | Why it matters | Mitigation |
|------|----------------|------------|
| **Tool boundary is cosmetic without policy** | Existing agent tools can bypass cwd | Project session kind gets explicit **allowlist** in `agent_loop.py` / tool router; block `bash`, unscoped file tools, shell/exec |
| **User path on server vs client** | Remote deploy breaks “pick folder” mental model | Document deployment assumption; v1 local-first; validated path + owner checks |
| **Path traversal / symlinks** | Escaping cwd = high severity | `realpath` containment; reject paths outside root; policy on symlinks (reject escape or ban) |
| **Broken working dir** | User deletes/moves folder externally | Project health state: `ok` / `missing` / `permission_denied`; banner + block run until fixed |
| **Three file paradigms confusion** | Model mixes cwd, documents, links | System prompt block + UI labels; Phase B agent rules |
| **document.js reuse overstated** | Data layer differs from cwd files | New `static/js/projects/editor.js` sharing CSS/helpers, not fork of full document app |
| **shell/exec reuse for run** | Generic RCE, no cwd discipline | **Dedicated** `run_project_script` subprocess: cwd, timeout, output cap, no shell |
| **Session refactor scope** | Chat touches DB, routes, streaming, Library | Early DB column + queries; workspace UI after spikes pass |
| **IDE layout scope** | Resizable VS Code UI is large | Fixed regions in Phases A–C; resizable + persisted layout in Phase D |
| **Jupyter later** | Not “py file + run” | File API designed for `kind: text` now; notebook kind in Phase F |
| **Stale graph links** | Same as Links today | Distinguish “linked entity missing” vs “file on disk” in context rail |

---

## Phase 0 — Spikes & prerequisites (do before Phase A UI)

**Goal:** Prove the three hardest foundations without building the full Projects section.

**Estimate:** 1 week.

| Spike | What to build | Pass criteria | Status |
|-------|---------------|---------------|--------|
| **Path resolver** | `src/project_paths.py`: `resolve_project_path(owner, project_id, rel_path) → Path` | Unit tests: `..`, absolute outside root, symlink escape (if allowed policy), missing root | ✅ Done |
| **Scoped file CRUD API** | Minimal routes: list/read/write under resolved root; owner gate | Integration tests with `tmp_path` as fake working dir | ✅ Done |
| **Scoped Python runner** | `POST /api/projects/{id}/run` — subprocess, `cwd=working_dir`, timeout, stdout/stderr cap, **no** `/api/shell/exec` | Runs only `.py` under cwd; rejects path traversal | ✅ Done |
| **Session column** | Migration: `sessions.project_id` nullable + index; filter list by project | Create session with project_id; query works | ✅ Done |
| **Tool policy sketch** | Document allowlist/denylist for `session.mode == 'project'` or new `session_kind` | Table in doc + one test that project session rejects `bash` | ✅ Done |

**Deliverable:** Spikes merged or documented; go/no-go for Phase A. **Do not skip** — cwd security and session schema affect everything downstream.

**Phase 0a implemented (path resolver):**

| File | Role |
|------|------|
| `src/project_paths.py` | `validate_working_dir`, `resolve_path_under_root`, `resolve_project_path` |
| `src/project_workspace.py` | JSON project records under `data/projects/{owner}/`; `resolve_owned_project_path` |
| `tests/test_project_paths.py` | Traversal, symlink escape, owner gate, missing root |
| `src/project_files.py` | list/read/write/mkdir/delete under cwd |
| `routes/project_routes.py` | `GET/POST/PATCH /api/projects`, file endpoints |
| `tests/test_project_files.py` | File round-trip + API auth/traversal |
| `src/project_runner.py` | `run_python_script` via subprocess (no shell) |
| `tests/test_project_runner.py` | Run success, args, timeout, traversal rejection |
| `src/project_sessions.py` | Create/list project-linked chat sessions |
| `tests/test_project_sessions.py` | Migration, session filter, API |
| `src/project_tool_policy.py` | Allowlist/denylist for `mode == 'project'`; wired in chat + execute |
| `tests/test_project_tool_policy.py` | Project session rejects `bash`; breadth tools unchanged |

**Phase 0e tool policy (implemented):**

| Layer | Allowed | Denied in project sessions |
|-------|---------|----------------------------|
| **Depth (cwd)** | `read_project_file`, `write_project_file`, `run_project_script` (agent wrappers in Phase B/C) | `bash`, `python`, `read_file`, `write_file`, `mcp__filesystem__*` |
| **Breadth (graph)** | `search_knowledge`, Zotero, research, document tools — unchanged | — |

Enforcement: `disabled_tools_for_project_session()` in `chat_routes.py` (hide from LLM) + `project_tool_block_reason()` in `execute_tool_block` (fail closed at execution).

---

## Target experience

```
Projects nav (like Chats)
    → List / grid of projects
    → Open project workspace
        ├── Sidebar: file tree (user working dir only)
        ├── Editor: open .py (later .ipynb) — project editor module
        ├── Run panel: stdout/stderr from scoped Python execution
        ├── Context rail: linked papers, research, documents, tasks
        └── Chat panel: project session type, multiple chats per project
```

**Agent boundaries (two layers):**

| Layer | Tools | Disabled in project sessions |
|-------|-------|------------------------------|
| **Depth (cwd)** | `read_project_file`, `write_project_file`, `run_project_script` | `read_file`, `write_file`, `bash`, generic `python`, MCP filesystem, `/api/shell/exec` |
| **Breadth (graph)** | `search_knowledge`, Zotero, research, `create_document` / `edit_document` (per policy) | Unchanged — graph traversal is the point |

Graph tools supply context; cwd tools mutate computation. **Neither replaces the other.**

---

## Graph schema (target)

**Node id:** `project:{uuid}` (uuid in id; optional display slug in meta).

**Node payload (sketch):**

```json
{
  "id": "project:abc123",
  "type": "project",
  "title": "AlphaFold comparison",
  "snippet": "3 chats · 12 files · 5 links",
  "meta": {
    "working_dir": "/home/user/work/alphafold-compare",
    "working_dir_status": "ok",
    "created_at": 0,
    "updated_at": 0,
    "source": "user"
  }
}
```

**Edges:**

| From | To | Kind | Notes |
|------|-----|------|--------|
| `project:{id}` | `paper:{key}` | `related` | Manual or suggested |
| `project:{id}` | `research:{session}` | `related` | On assign or suggest after complete |
| `project:{id}` | `document:{id}` | `related` | Linked doc, not cwd file |
| `project:{id}` | `task:{id}` | `related` | Optional |
| `project:{id}` | `collection:{key}` | `related` | Derived import source |
| `project:{id}` | `note:{id}` | `related` | Optional |

Defer dedicated `in_project` edge kind until stricter semantics than `related` are needed.

**Session linkage:** `sessions.project_id` (FK-style string) when session is project-scoped; list/filter in workspace UI. Consider `session_kind = 'project'` or extend `mode` — pick one at Phase 0 spike.

---

## Phase A — Project entity + section shell

**Goal:** Projects exist in data model and UI as a new nav section; linking and path validation; **no execution, no project chat yet**.

**Estimate:** 2–3 weeks (after Phase 0).

**Prerequisites:** Phase 0 path resolver + owner checks passing tests.

| Item | Direction | Clarifications | Status |
|------|-----------|----------------|--------|
| **`project` node type** | Add to `_NODE_TYPES`; CRUD + API | Mirror `research` indexing patterns in `knowledge_graph.py` | ✅ Done |
| **Project record** | `working_dir`, title, description, `working_dir_status`, owner | Re-validate path on open; update status if missing | ✅ Done |
| **Working dir picker** | User enters path; validate exists, readable, canonical | Warn if home or overly broad path; explain server-host path in help text | ✅ Done |
| **Projects nav section** | Like Chats: list, create, rename, archive/delete | Feature flag optional for early rollout | ✅ Done |
| **Project detail (shell)** | **Fixed** layout regions (no resize yet): placeholders for tree, editor, run, chat, links rail | CSS grid tokens in `static/style.css` | ✅ Done |
| **Manual linking** | Link/unlink from project detail + Links | Reuse link picker patterns from `knowledge.js` | ✅ Done |
| **Path guard** | Wire Phase 0 `resolve_project_path` into service layer | No file tree yet — only validate stored path | ✅ Done (Phase 0) |

**Deliverable:** User creates project, sets working dir, links papers/research/docs, opens hub shell. Path validation and owner scope proven.

**Key files:**

| Area | Path (expected) |
|------|------------------|
| Path safety | `src/project_paths.py` (from Phase 0) |
| Graph + service | `src/knowledge_graph.py`, `src/project_workspace.py` |
| API | `routes/project_routes.py` |
| UI shell | `static/js/projects/` (list + workspace shell) |

**Tests:** Graph CRUD; cross-owner 404; working dir validation; link/unlink edges.

**Phase A implemented:**

| File | Role |
|------|------|
| `src/project_graph.py` | Graph node upsert/delete/index; link helpers |
| `src/project_paths.py` | `working_dir_warning()` for broad paths |
| `routes/project_routes.py` | validate-dir, archive, links CRUD |
| `static/js/projects/index.js` | Sidebar list, create flow, workspace shell |
| `tests/test_project_graph.py` | Graph sync, links API, owner gate, archive |

---

## Phase B — Working directory file tree + Python editor

**Goal:** Real files under working dir; edit Python with shared editor UX; agent read/write tools live.

**Estimate:** 2–3 weeks.

**Prerequisites:** Phase A project CRUD; Phase 0 file CRUD API extended.

| Item | Direction | Clarifications | Status |
|------|-----------|----------------|--------|
| **File tree API** | list / read / write / rename / delete / mkdir under `resolve_project_path` only | Every op: owner → project → path; audit optional | ✅ Done |
| **File tree UI** | Sidebar tree; create file/folder; open in editor tab | Show path relative to root; handle external deletes gracefully | ✅ Done |
| **Editor module** | **`static/js/projects/editor.js`** — new module | Share: highlight.js setup, line numbers, language map from `document.js`; **do not** bind to SQLite doc IDs | ✅ v1 (autosave + conflict check; not full document.js parity) |
| **Save model** | PUT relative path; conflict if changed on disk since open (optional etag) | Autosave policy matches documents where sensible | ✅ Mostly (editor autosave + `modified_at`; native confirm on conflict) |
| **New vs linked docs** | Cwd `.py` ≠ document node until user links | UI: “Add to Library as document” = explicit action |
| **Agent tools** | `read_project_file`, `write_project_file` — path relative to project root | Register in `tool_schemas.py`; implement in project service; **project session allowlist only** | ✅ Done |
| **Agent prompt block** | Inject three-paradigm rules (see above) | Prevents `create_document` for a script that should be `analysis.py` in cwd | ✅ Done |

**Deliverable:** Browse/edit/save `.py` in user directory; agent writes only under cwd when in project session.

**Reuse vs new:**

| Reuse | New |
|-------|-----|
| `document_processor.py` extension → language | `projects/editor.js`, `projects/fileTree.js` |
| `document.js` CSS classes / highlight patterns | Project file API routes |
| Owner gating pattern from `document_routes.py` | Agent tool implementations |

**Tests:** Traversal rejection; round-trip read/write; agent tool rejects `../../etc/passwd`; owner isolation.

---

## Phase C — Python execution + run panel

**Goal:** Run scripts from workspace; agent `run_project_script`; **not** reuse admin shell/exec.

**Estimate:** 1–2 weeks.

**Prerequisites:** Phase B file API; Phase 0 runner spike promoted to production.

**Status:** Phase C complete.

**Phase C — Run API (2026-06-01):** `POST /api/projects/{id}/run` — `{ path, args?, timeout? }`; `subprocess` with `cwd=working_dir`, no shell, 60s default timeout, 100k output cap, `.py` only, path confinement + owner gate. Python runs with `-I` (isolated mode).

| Item | Direction | Clarifications | Status |
|------|-----------|----------------|--------|
| **Run API** | `POST /api/projects/{id}/run` — body: `{ path, args? }` | Subprocess: `python3 script.py` with `cwd=working_dir`; **no shell**; timeout (e.g. 60s); max output chars | ✅ Done |
| **Network policy** | Off by default for subprocess env | Optional setting `project_run_allow_network`; document in open questions | ✅ Done |
| **Run panel UI** | stdout/stderr; exit code; re-run; “Run” on editor toolbar | UX reference: `cookbookRunning.js` output panel | ✅ Done |
| **Agent tool** | `run_project_script` — relative path, optional args allowlist | Same backend as Run API; no arbitrary `-c` strings in v1 (file path only) | ✅ Done |
| **Safety UX** | Confirm if unsaved buffer; warn on first run in session | Cap output size server-side | ✅ Done |

**Do not:** Route through `/api/shell/exec` or `codeRunner.runServer` for project files — those are admin-oriented and not cwd-scoped.

**Deliverable:** User and agent run `.py` files; output in-panel; execution confined to project directory context.

**Tests:** cwd verification; timeout; output truncation; cannot run `/usr/bin/id` via path escape.

---

## Phase D — Project-scoped chat (session type)

**Goal:** Chats inside project workspace; tool policy enforced; layout connects chat + editor + run.

**Estimate:** 2–3 weeks.

**Prerequisites:** Phases B–C; Phase 0 `project_id` on sessions.

**Status:** D1–D6 done. Next: Phase E (hybrid suggestions + research integration).

| Item | Direction | Clarifications | Status |
|------|-----------|----------------|--------|
| **Session model** | `project_id` + distinguish project sessions in UI (extend `mode` or add `session_kind`) | Migration + backfill; main Chats nav may hide or badge project sessions | ✅ Done |
| **Chat sidebar** | List/create/rename chats for this project only | New chat inherits `project_id` | ✅ Done |
| **Layout v1** | **Fixed** split: chat \| editor+run \| links (no drag-resize yet) | Persist last open file + active chat id in project meta or localStorage | ✅ Done |
| **Layout v2** (optional same phase or follow-up) | Resizable panels; persist sizes per project | Defer if schedule tight | → see **`docs/projects-ui-roadmap.md`** (Phase G) |
| **Context injection** | System preamble: project title, cwd, linked summaries (papers, recent research) | Pull from graph + project record; truncate | ✅ Done |
| **Tool routing** | **Depth allowlist:** project file + run tools. **Breadth allowlist:** graph/Zotero/research/document tools (unchanged). | **Depth denylist:** `bash`, `python` (inline), `read_file`, `write_file`, MCP filesystem, shell/exec. Graph tools stay enabled — they do not bypass cwd writes. | ✅ Done |
| **Integration tests** | Phase 0 tool policy test expanded with mock agent loop paths | `tests/test_project_tool_routing.py` — schema filter, execute blocks, preamble | ✅ Done |

**Deliverable:** Multiple chats per project in workspace; agent respects cwd + links; escape tools blocked.

**Touch:** `core/database.py`, `core/session_manager.py`, `routes/chat_routes.py`, `src/agent_loop.py`, `static/js/projects/workspace.js`.

**Tests:** Session filtered by project_id; tool denial in project mode; context includes linked research id.

---

## Phase E — Hybrid suggestions + research integration

**Goal:** Connect Deep Research to projects without auto-spam; navigate linked knowledge via Links hub.

**Estimate:** ~1 week remaining (E4/E5 only).

**Prerequisites:** Phase A linking UI; Deep Research on `feature/knowledge-graph`.

**Status:** E1 done. **E2 and E3 skipped** (see rationale). E4/E5 in progress.

| Item | Direction | Clarifications | Status |
|------|-----------|----------------|--------|
| **Research → project** | Optional project picker when starting compare/gap; post-complete suggest | Same confirm pattern as Save-to-Zotero | ✅ Done |
| **Zotero collection import** | ~~Opt-in: bulk create `related` edges from collection members~~ | **Skipped** — bulk paper edges would flood agent preamble/context at current truncation (24 links / 4k chars); prefer explicit one-at-a-time linking via Links picker | ⏭ Skipped |
| **Library filter** | ~~Research tab filter by project~~ | **Skipped** — same token-budget concern; low distinct value vs explicit graph links | ⏭ Skipped |
| **Links hub** | Open Links modal from project workspace; link rows → node detail in hub; `project:{id}` → workspace | `openKnowledgeAtNode()` from links rail; “Browse in Links” on project | ✅ Done (verify) |
| **Stale links** | Show “missing from graph”; one-click remove stale; agent preamble marks stale | Rail UI + bulk remove; preamble already truncates | ✅ Done (verify) |

**Deliverable:** Curated literature → project workflow with Links as the navigation hub — no bulk import.

**Reuse:** `src/research_graph.py`, Library research preview, `research_zotero_save.py` confirm UX, `static/js/knowledge.js`.

**Deferred (revisit only if context budget changes):** Zotero collection → project bulk edges; Research Library filter by `project_id`. Would need summarization caps or lazy-load, not raw member lists in preamble.

---

## Phase F — Notebook & multi-language (future)

**Goal:** Extend beyond plain `.py` files.

| Item | Direction | Clarifications |
|------|-----------|----------------|
| **Jupyter `.ipynb`** | Cell model; kernel lifecycle; **not** the Phase C runner | Separate design doc when Phase C ships |
| **File API extensibility** | Optional `meta.kind: text \| notebook` on file entries | Plan in Phase B API shape |
| **Other languages** | JS/bash only if scoped runner equivalents exist | Same cwd + policy constraints |
| **LSP / IntelliSense** | Out of scope until workspace stable | — |

**Deliverable:** TBD — spec after Phase C retrospective.

---

## IDE trajectory (beyond Projects)

Projects are **phase 1** of a longer IDE direction on `feature/projects`:

| Later capability | Depends on | Notes |
|------------------|------------|-------|
| Multi-pane editor (diff, split) | Phase B | — |
| Integrated terminal (cwd-scoped) | Phase C | Still not generic shell |
| Git status in file tree | Phase B | Read-only first |
| Drag-resize layout persistence | Phase G6+ in `projects-ui-roadmap.md` | Was “Phase D v2” |
| Debug / breakpoints | Far future | — |
| Client-side path bridge (remote users) | Far future | Sync agent or SFTP |

---

## Security & sandboxing (consolidated)

The two-boundary model drives security policy: **containment applies to depth (cwd); breadth (graph) uses existing authenticated tools.**

| Layer | Policy |
|-------|--------|
| **Depth — file R/W** | `resolve_project_path` + owner; path must stay under `working_dir` after `realpath` |
| **Depth — symlinks** | Resolve with `realpath`; reject if resolved path outside project root |
| **Depth — run** | Subprocess, no shell, cwd locked, timeout, output cap, network off by default |
| **Depth — agent** | Project session denies unscoped file/shell tools; project tools only for mutation |
| **Breadth — graph** | Existing owner-scoped knowledge/Zotero/research routes; no cwd required for read-only context |
| **UX** | Warn on broad paths (home, `/`); show `working_dir_status` |
| **Audit** | Optional log: writes and runs per project id |

---

## Open questions (iterate here)

| # | Question | Default lean |
|---|----------|--------------|
| 1 | Project id: uuid vs slug? | **uuid** in id; slug optional in meta |
| 2 | Move/rename working dir after create? | Allow with re-validation + `working_dir_status` |
| 3 | Copy vs link when importing document into cwd? | **Link** by default |
| 4 | Max projects per user / disk quota? | max projects should be based on disk quota |
| 5 | Share projects across users? | Out of scope, we need to make a seperate roadmap for this as the plan would be to share linked webs |
| 6 | Network during `run_project_script`? | **Off** by default via `project_run_allow_network` in `data/settings.json`. Minimal env + proxy strip when off; not kernel socket blocking. Set `true` for scripts that need urllib/pip/etc. |
| 7 | Symlinks inside project root? | **Allow** if resolved path stays inside root; else reject |
| 8 | `session_kind` vs extend `mode`? | clarfy this point |
| 9 | Show project sessions in main Chats nav? | **Badge/filter** or hide — avoid duplicate chats, chats can be linked to web tool and appear in session |
| 10 | Bulk-link Zotero collection to project? | **Deferred** — explicit links only; bulk import floods agent context until summarization improves |
| 11 | Filter Research Library by project? | **Deferred** — same rationale as #10 |

---

## Testing strategy

| Phase | Tests |
|-------|--------|
| **0** | Path traversal matrix; runner cwd; session project_id query |
| **A** | Graph CRUD; owner gate; working dir validation states |
| **B** | File API round-trip; agent tools scoped; editor save |
| **C** | Run timeout; output cap; no shell escape |
| **D** | Tool denylist in project session; chat list by project |
| **E** | Suggest UI never auto-links without confirm; Links hub from project rail; stale link remove |

Fixtures: `tmp_path` as fake project roots; never use real `/etc` in CI.

---

## Feasibility & product fit (Nobody)

*Assessment as of 2026-06-01 — revisit after Phase 0.*

### Is it feasible?

**Yes, incrementally** — if we respect phasing and do not ship “VS Code + Jupyter + remote paths” as v1.

| Factor | Assessment |
|--------|------------|
| **Technical fit** | Strong. Nobody already has graph nodes, Deep Research, Zotero, documents with Python UX, and agent tools. Projects **compose** existing pieces rather than replacing them. |
| **Hardest part** | Session + workspace UI + **enforceable** tool policy — not the file tree itself. Phase 0 spikes de-risk this. |
| **Timeline (realistic)** | Phase 0–D ≈ **8–12 weeks** focused work for a credible v1 (hub, files, run, project chat). Phase E + polish add 2–4 weeks. Jupyter (F) is a separate project. |
| **Team size assumption** | Solo or small team — sequential phases; avoid parallel UI + agent refactors without Phase 0 done. |
| **Deployment** | **Most feasible local-first** (researcher runs Nobody on their machine, points project at `~/experiments/...`). Remote multi-tenant needs extra path UX — not v1 blocker if primary audience is local. |

**Not feasible as a single release:** Full IDE parity (LSP, debugger, notebooks, git UI, resizable dock everywhere) in one pass.

### Is it worthwhile for Nobody?

**Yes — especially for computationally inclined researchers** — if positioned as **“literature + code in one graph-linked workspace”**, not as a generic IDE competitor.

| Value | Why it matters for Nobody |
|-------|---------------------------|
| **Closes the loop** | Deep Research finds papers → project links them → scripts analyze results → chat remembers both. Today those live in separate silos (Research tab, Documents, Chats, Links). |
| **Differentiated** | Notion/Obsidian + Zotero don't offer cwd-scoped agent + run + evidence-linked research in one app. VS Code doesn't own your literature graph. |
| **Audience match** | Computational biologists, ML-for-science, reproducible pipelines — people who already have a `~/project/` folder **and** a paper library. |
| **Agent safety story** | “AI can edit **this folder only**” is a sellable constraint for researchers wary of agents touching their whole disk. |
| **Extends moat** | Builds on completed Deep Research investment (seeds, registry, Zotero save, graph links) instead of a greenfield IDE. |

| Risk to product | Mitigation |
|-----------------|------------|
| Scope creep → half-built IDE | Strict phases; Phase A usable without run; Phase C usable without perfect layout |
| Confusing UX (3 file types) | Prompt + UI copy; Phase B rules |
| Security incident | Phase 0 non-negotiable; no shell/exec shortcut |
| Niche audience | Acceptable for Nobody — depth over mass-market generic chat |

**Recommendation:** **Proceed** on `feature/projects` after **Phase 0 spikes** (one week). Ship **Phase A→C** as first user-visible milestone (“project folder + Python + links”); add project chat in Phase D as the agent-native differentiator.

---

## Related docs

| Doc | Relationship |
|-----|--------------|
| `docs/projects-ui-roadmap.md` | **Workspace UI redesign** — tabbed layout, visual polish (Phase G) |
| `docs/deep-research-roadmap.md` | Research → project linking (Phase E) |
| `ROADMAP.md` | Link Projects when section ships |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-01 | Initial roadmap: locked decisions 1–4, Phases A–F, graph schema, IDE trajectory |
| 2026-06-01 | Expanded: deployment assumption, three paradigms, implementation risks, Phase 0 spikes, per-phase clarifications, feasibility/product fit |
| 2026-06-01 | Phase 0d: sessions.project_id migration + project session API |
| 2026-06-01 | Phase 0e: project tool policy module + bash rejection test |
| 2026-06-01 | Phase B started: file tree API (rename, recursive delete, list payload, modified_at on read) |
| 2026-06-01 | Phase B: project editor (highlight overlay, autosave, modified_at conflict check) |
| 2026-06-01 | Phase B: file tree UI (lazy tree, CRUD toolbar, read-only preview pane) |
| 2026-06-01 | Phase A: project graph node, Projects nav, workspace shell, manual linking |
| 2026-06-01 | Phase D5/D6: `apply_session_tool_policy`, integration tests in `test_project_tool_routing.py` |
| 2026-06-01 | Phase D: project chat visibility fix (dock history only, input below panel) |
| 2026-06-01 | Phase E scope: skip Zotero collection import + Library filter; prioritize Links hub + stale links |
| 2026-06-01 | Phase E: Links rail → `openKnowledgeAtNode`; stale bulk remove; tool-routing preamble |
| 2026-06-01 | Added `docs/projects-ui-roadmap.md` — tabbed workspace UI (Phase G) |
