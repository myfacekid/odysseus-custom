# Projects Roadmap

Living plan for **Projects** — a new app section and graph node type that bridges knowledge work (papers, research, documents, tasks) with an **IDE-like workspace** (files, Python editing, execution, project-scoped chat).

Use this doc when starting future chats: *"Follow docs/projects-roadmap.md Phase X"*.

**Branch:** `feature/projects` (first step toward IDE work; projects and IDE functionality are intentionally intertwined).

**Last updated:** 2026-06-01

**Status:** Planning — no implementation yet. Deep Research phases 0–5d land on `feature/knowledge-graph` (`84cbf78`); Projects begins from that baseline.

---

## North star

**Projects** are a first-class section in the app (like Chats) that give the user a **scoped workspace**:

- A **user-chosen working directory** on disk for scripts, outputs, and project-local files.
- **Graph membership** linking the project to papers, research sessions, documents, tasks, notes, collections, and other knowledge nodes — same linking model as the rest of Links.
- **Project-scoped chat** as its own session type, with multiple chats attached to one project (VS Code–like panel).
- **Python-first** edit and run inside the working directory, reusing document editor/runner patterns; room for Jupyter notebooks and other languages later.

Projects are the **entry point** into IDE-like behavior. Documents remain normal document nodes; they are **linked** to a project, not embedded inside it.

---

## Locked decisions

These are settled unless explicitly revisited in this doc.

| # | Decision | Choice |
|---|----------|--------|
| 1 | **Working directory** | **One per project**, path **selected by the user** (not auto-assigned under `data/` only). The agent/model is **restricted to direct file manipulation within that directory**. Links, Zotero, research, documents, and other graph-backed tools remain available — this boundary limits OS-wide file access, not knowledge access. |
| 2 | **Languages & execution** | **Python first.** Reuse existing document viewing/editing and server-side run (`static/js/document.js`, code runner). Future: **Jupyter notebook** compatibility; extensibility for other languages. |
| 3 | **Chat model** | **Project-scoped chat** — `project` is a **new session type**. Chats belong to a project, are listed/opened in a **VS Code–like** manner (sidebar + editor layout), and inherit project context (cwd + linked entities). |
| 4 | **Fork / branch strategy** | Work continues on **`feature/projects`** in this repo. Projects is phase 1 of a longer IDE trajectory; do not treat it as a small isolated feature. |

### Hybrid membership (manual + derived)

| Mode | Behavior |
|------|----------|
| **Manual** | User links/unlinks any graph node from the project UI or Links. |
| **Derived (opt-in)** | e.g. import edges from a Zotero collection; sync optional, never silent bulk spam. |
| **Suggested** | After research completes or when viewing related papers: “Add to project X?” — confirm, don’t auto-add. |

`collection` nodes stay Zotero-synced; `project` is the user-facing workspace hub. A project may **relate** to a collection without merging types.

---

## Current state (baseline)

**Graph today** (`src/knowledge_graph.py`):

- Node types: `task`, `document`, `memory`, `skill`, `note`, `paper`, `collection`, `research`.
- **No `project` type yet.** Research already upserts `research:{session_id}` and auto-links seed papers + top cited sources (`src/research_graph.py`).

**Documents / code today:**

- Library + document editor support Python (and other langs) with syntax highlighting and **Run** via server (`document.js` → code runner).
- Documents are SQLite-backed entities with owner scope — separate from arbitrary filesystem paths.

**Chats today:**

- Session list in main nav; spinoffs from research/library; no project container or cwd-scoped file tools.

**Gap:** No unified “workspace” that combines cwd-scoped files, graph links, scoped chat, and run panel in one layout.

---

## Target experience

```
Projects nav (like Chats)
    → List / grid of projects
    → Open project workspace
        ├── Sidebar: file tree (user working dir only)
        ├── Editor: open .py (later .ipynb) — borrow document editor
        ├── Run panel: stdout/stderr from scoped Python execution
        ├── Context rail: linked papers, research, documents, tasks
        └── Chat panel: project session type, multiple chats per project
```

**Agent boundary:** Tools like `read_project_file`, `write_project_file`, `run_project_script` resolve paths **only** under the project’s registered working directory (canonicalize + reject `..` and paths outside root). Graph tools unchanged.

---

## Graph schema (target)

**Node id:** `project:{uuid}` (or stable slug — pick one at implementation; prefer uuid for rename safety).

**Node payload (sketch):**

```json
{
  "id": "project:abc123",
  "type": "project",
  "title": "AlphaFold comparison",
  "snippet": "3 chats · 12 files · 5 links",
  "meta": {
    "working_dir": "/home/user/work/alphafold-compare",
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

Defer a dedicated `in_project` edge kind until we need stricter semantics than `related`.

**Session linkage:** Chat sessions store `project_id` (or `parent_project`) when type is project-scoped; list/filter in project workspace UI.

---

## Phase A — Project entity + section shell

**Goal:** Projects exist in data model and UI as a new nav section; no execution yet.

**Estimate:** 2–3 weeks.

| Item | Direction |
|------|-----------|
| **`project` node type** | Add to `_NODE_TYPES`; CRUD in `knowledge_graph.py` + API routes |
| **Project record** | Persist `working_dir`, title, description, timestamps, owner |
| **Working dir picker** | UI to choose/create directory; validate exists and is readable; store absolute canonical path |
| **Projects nav section** | New section modeled on Chats: list, create, rename, archive/delete |
| **Project detail (shell)** | Layout regions: file tree placeholder, editor placeholder, links rail, chat placeholder |
| **Manual linking** | Link/unlink graph nodes from project detail + Links modal |
| **Path guard (stub)** | Server helper: `resolve_project_path(project_id, relative_path) → Path` rejects escape |

**Deliverable:** User can create a project, set working dir, link papers/research/docs, see them in a project hub. No agent file tools yet.

**Key files to add/touch:**

| Area | Path (expected) |
|------|------------------|
| Graph type + index | `src/knowledge_graph.py` |
| Project service | `src/project_workspace.py` (new) |
| API | `routes/project_routes.py` (new) |
| UI shell | `static/js/projects/` (new), `static/index.html` nav |
| Styles | `static/style.css` (project layout tokens) |

---

## Phase B — Working directory file tree + Python editor

**Goal:** Real files under the user’s working dir; edit Python with existing editor patterns.

**Estimate:** 2–3 weeks.

| Item | Direction |
|------|-----------|
| **File tree API** | List/read/write/rename/delete **only** under project `working_dir` |
| **File tree UI** | Sidebar tree; create file/folder; open in editor pane |
| **Editor reuse** | Adapt `document.js` patterns: highlight.js, tabs, save — for project files (not SQLite docs) |
| **New vs linked docs** | Cwd files ≠ document nodes; optional “Link as document” promotes/copy metadata to graph |
| **Agent tools (read/write)** | Scoped tools; system prompt states cwd boundary |

**Deliverable:** User opens project, browses/edits/saves `.py` files in their chosen directory; agent can read/write those paths only.

**Reuse:**

- `static/js/document.js` — editor, language map, save UX
- `src/document_processor.py` — language detection by extension
- Path validation pattern — similar to owner gating in `routes/document_routes.py`

---

## Phase C — Python execution + run panel

**Goal:** Run scripts from the project workspace with captured output.

**Estimate:** 1–2 weeks.

| Item | Direction |
|------|-----------|
| **Run API** | Execute Python with cwd = project working dir; timeout; no shell unless explicit |
| **Run panel UI** | stdout/stderr stream or poll; re-run button |
| **Agent tool** | `run_project_script` — relative path, args allowlist, timeout |
| **Safety** | Confirm before run if file changed since last save; cap output size |

**Deliverable:** User clicks Run on a project file; sees output in-panel; agent can run scoped scripts.

**Reuse:**

- `document.js` / code runner — `runServer(code, …, 'python')`
- Cookbook task output patterns — `static/js/cookbookRunning.js` (UX reference for run status)

---

## Phase D — Project-scoped chat (session type)

**Goal:** Chats live inside the project workspace, VS Code–style.

**Estimate:** 2–3 weeks.

| Item | Direction |
|------|-----------|
| **Session type** | Extend session model: `session_kind = 'project'` + `project_id` |
| **Chat sidebar** | List chats for this project; new chat; rename |
| **Layout** | Split: chat + editor + run panel (resizable regions) |
| **Context injection** | System context: project title, working dir, linked node summaries |
| **Tool routing** | Project sessions get file/run tools + existing graph/search tools |

**Deliverable:** Multiple chats per project; opening project restores layout; agent respects cwd + links.

**Touch:**

- `core/session_manager` / DB session schema
- `routes/chat_routes.py`, `static/js/chat*.js`
- `src/agent_loop.py` — tool availability by session kind

---

## Phase E — Hybrid suggestions + research integration

**Goal:** Connect Projects to existing Deep Research and Zotero flows.

**Estimate:** 1–2 weeks.

| Item | Direction |
|------|-----------|
| **Research → project** | Optional project picker when starting compare/gap modes; suggest after complete |
| **Zotero collection import** | Opt-in: create edges from collection members |
| **Library filter** | Research tab filter by project (optional) |
| **Links hub** | Project node opens workspace; same as Projects section |

**Deliverable:** Research sessions and paper sets flow into projects without auto-spam.

**Reuse:** `src/research_graph.py`, Library research preview, Save-to-Zotero patterns for “confirm before attach”.

---

## Phase F — Notebook & multi-language (future)

**Goal:** Extend beyond single `.py` files.

| Item | Direction |
|------|-----------|
| **Jupyter `.ipynb`** | View/edit cells; run cell-wise; optional export to `.py` |
| **Other languages** | JS/bash reuse from document runner where safe |
| **LSP / IntelliSense** | Out of scope until core workspace is stable |

**Deliverable:** TBD — spec when Phase C is done.

---

## IDE trajectory (beyond Projects)

Projects are **phase 1** of a longer IDE direction on `feature/projects`:

| Later capability | Depends on |
|------------------|------------|
| Multi-pane editor (diff, split) | Phase B |
| Integrated terminal (still cwd-scoped) | Phase C |
| Git status in file tree | Phase B + git read-only |
| Debug / breakpoints | Far future |
| Extension or plugin model | Far future |

Keep IDE ambitions in this doc; implement only through phased deliverables above.

---

## Security & sandboxing notes

- **Working dir is a trust boundary** for file R/W and run — not for graph read tools.
- Canonicalize paths; reject symlinks that escape root (or document symlink policy).
- Python run: subprocess, no network by default (setting?), CPU/time limits.
- User must explicitly set working dir; warn if dir is home or system path.
- Audit log optional: file writes and runs per project.

---

## Open questions (iterate here)

| # | Question | Default lean |
|---|----------|--------------|
| 1 | Project id: uuid vs slug? | **uuid** in id; slug optional in meta for display |
| 2 | Move/rename working dir after create? | Allow with re-validation + warning |
| 3 | Copy vs link when importing a document into cwd? | **Link** by default; copy explicit |
| 4 | Max projects per user / disk quota? | Defer |
| 5 | Share projects across users? | Out of scope v1 |
| 6 | Network during `run_project_script`? | Off by default; admin setting |

Update this table as decisions land.

---

## Testing strategy

| Phase | Tests |
|-------|--------|
| A | Graph CRUD; API auth/owner; link/unlink edges |
| B | Path traversal rejection; read/write round-trip under cwd |
| C | Run timeout; output capture; cwd verification |
| D | Session type persistence; list chats by project_id |
| E | Suggest UI does not auto-link without confirm |

Fixtures: temp directories as fake project roots.

---

## Related docs

| Doc | Relationship |
|-----|--------------|
| `docs/deep-research-roadmap.md` | Research → project linking (Phase E) |
| `ROADMAP.md` | High-level product roadmap — link Projects when section ships |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-01 | Initial roadmap: locked decisions 1–4, Phases A–F, graph schema, IDE trajectory |
