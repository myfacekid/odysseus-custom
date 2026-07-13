# Projects as Context Layer — Roadmap

Living plan for **repositioning Projects** from an IDE-style workspace shell into an **optional harness-level context layer**: agent + cwd + linked concepts, without replacing the main app chrome.

Use this doc when starting future chats: *"Follow docs/projects-context-layer-roadmap.md Phase L1"*.

**Last updated:** 2026-07-13

**Status:** Product direction agreed. Workspace UI **hidden** behind `PROJECTS_UI_ENABLED` (`static/js/projects/featureFlag.js`). Backend APIs kept. Implementation of the layer model not started.

**Supersedes (for product direction):** the “Projects is a workspace mode” guiding rule in `docs/projects-suite-roadmap.md`. That suite work (P1–P9) remains useful chrome reference if a thin file viewer returns later; it is **not** the target product shape.

**Related:** `docs/projects-ui-roadmap.md` (G1–G8 workspace interior — historical), `docs/projects-suite-roadmap.md` (suite cohesion — paused).

---

## Product thesis

Projects’ real promise is not a file tree + editor + Run panel. It is:

1. **Scoped agent context** — chats, research, and tools inherit an active project.
2. **A user-chosen cwd** — computational depth (read/write/run under that folder).
3. **Linked concepts** — curated graph links to papers, research, documents (breadth).

The harness stays the product. A project is a **layer above** it: turn it on, and those surfaces inherit scope. Turn it off, and Odysseus behaves as today.

### Boundaries (keep separate)

| Domain | Owns | Does not |
|--------|------|----------|
| **cwd (project folder)** | Code, scripts, run outputs, agent file tools | Become Library folders; auto-mirror into Library |
| **Library** | App-owned corpus (docs, notes, ingested knowledge) | Mirror the project tree |
| **Graph links** | Explicit relationships between project ↔ papers/research/docs | Imply file copies |

**Promote is explicit:** user (or agent with confirmation) copies/imports a cwd file into Library. Never silent sync.

---

## Interim: hide Projects UI

**Done (2026-07-13):**

- Flag: `PROJECTS_UI_ENABLED = false` in `static/js/projects/featureFlag.js`.
- `initProjects()` hides chrome and skips restore; `openProjectWorkspace` no-ops.
- Hidden: New Project, sidebar Projects section, workspace panel, overflow/mode pill, Appearance toggle, research “Add to project” / link picker, Knowledge “Open workspace”.
- Backend `/api/projects*` left intact for the rebuild.

**Re-enable for local work:** set `PROJECTS_UI_ENABLED = true` and reload.

---

## Target UX (sketch)

```
┌─ Top / chrome ─────────────────────────────────────────┐
│  [ Project: Atlas ▾ ]  or  [ No project ]               │  ← global chip
└────────────────────────────────────────────────────────┘
  When active:
  • Chats created in this scope (or filterable by project)
  • Research can inherit / suggest link to active project
  • Agent tool policy: no free bash; cwd-bound tools only
  • Optional: slim “Project files” picker (not full IDE)
  • Links hub / Knowledge: project node + linked neighbors
```

No dedicated main-area workspace that replaces Chats/Documents. Optional later: a **lightweight** file browser / promote sheet, not a tabbed IDE shell.

---

## Phases

### L0 — Pause & park (done)

- Hide user-facing Projects UI; clear last-open restore.
- Document direction (this file).
- Stop investing in workspace chrome unless L5 explicitly revives a thin viewer.

### L1 — Active project chip (harness chrome)

**Goal:** Pick / clear / create a project without opening a workspace.

- Global control in top bar (or sidebar header): active project title + switcher.
- Create project = title + working directory (reuse existing create API).
- Persist `active_project_id` (session or user preference).
- Empty state: “No project — chats and tools are unscoped.”

**Out of scope for L1:** file tree, editor, Run panel.

### L2 — Scope inheritance

**Goal:** Active project flows into the surfaces that matter.

- **Chat:** new sessions tagged with `project_id`; list filter “This project” / “All”.
- **Research:** inherit active project for compare/gap link prompts (replace old workspace-centric CTAs).
- **Knowledge / Links:** project node remains; “open workspace” becomes “set active” or “view links”.
- **Activity strip:** optional “Project: …” when scoped.

### L3 — Tool policy & cwd execution

**Goal:** When a project is active, the agent stays inside the computational boundary.

Already largely present: `project_tool_policy`, `read_project_file` / `write_project_file` / `run_project_script`.

Ship / tighten:

- No free `bash` while project active (or only via allowlisted `run_project_command` with path jail).
- Clear UX copy: “Tools run in project folder.”
- Off-project = existing harness tool policy.

### L4 — Promote cwd → Library

**Goal:** Explicit bridge from computational depth to app corpus.

User stories:

1. From a project file picker (or agent suggestion): **Add to Library**.
2. Choose Library destination (document / note / ingest path — match existing Library APIs).
3. Optional: create a graph link `project ↔ document` after promote.
4. Never auto-promote run outputs or entire trees.

API sketch:

- `POST /api/projects/{id}/promote`  
  body: `{ path, library_type?, title?, link?: true }`  
  reads file under cwd jail → creates Library artifact → optional link edge.

UI:

- Action on file row / overflow: “Add to Library…”
- Confirm dialog with destination + “also link to this project”.
- Toast with “Open in Library”.

### L5 — Retire or demote the workspace shell

**Goal:** Remove the IDE framing from the default product.

Options (pick one in implementation):

- **A (preferred):** Delete or archive `#project-workspace-panel` entry points; keep modules only as needed for a **modal/sheet** file browser used by promote + rare “peek file”.
- **B:** Keep a power-user “Open folder view” behind an advanced flag.

Chat|Run companion, tab host, layout presets become non-goals unless they serve L4’s thin picker.

### L6 — Polish & migration

- Migrate users who had “last open project” → active chip only.
- Appearance toggle for Projects section → remove or replace with “Show project chip”.
- Update onboarding copy; archive suite/UI roadmaps as historical.
- Tests: flag off by default; L1–L4 coverage for chip, scope, promote.

---

## Non-goals

- Mirroring project directory trees into Library folders.
- Making Library the project file browser.
- Free-form shell as the primary project execution path.
- Rebuilding VS Code inside Odysseus.

---

## Suggested implementation order

| Order | Phase | Why |
|-------|-------|-----|
| 1 | L0 | Already done — users don’t see stale IDE UI |
| 2 | L1 | Smallest visible “projects exist again” surface |
| 3 | L3 | Safety before encouraging agent use of cwd |
| 4 | L2 | Makes the chip meaningful across chats/research |
| 5 | L4 | Promote cwd → Library (requested bridge) |
| 6 | L5–L6 | Remove dead shell; migrate prefs |

---

## Open decisions (resolve in L1 kickoff)

1. **Chat model:** Always create under active project vs opt-in “Attach to project”?
2. **Promote targets:** Documents only, or also Notes / raw Library ingest?
3. **Agent promote:** Tool `promote_project_file` with confirm, or UI-only first?
4. **Multi-project:** One active project only (recommended) vs pinned set?

---

## File map (expected)

| Area | Likely touch |
|------|----------------|
| Flag / hide | `static/js/projects/featureFlag.js` |
| Chip UI | `static/index.html`, top-bar JS, new `static/js/projects/activeChip.js` |
| Scope | session create APIs, research `projectLink.js`, chat list filters |
| Tools | `src/project_tool_policy.py`, `src/project_files.py` |
| Promote | new API + Library create path + thin file picker |
| Cleanup | `#project-workspace-panel` and `static/js/projects/{editor,tabHost,workspace*}` |

---

## Success criteria

- User can run Odysseus with **no project** and never see Projects chrome.
- User can set an active project and have chat/research/tools inherit it without opening an IDE shell.
- User can **promote** a cwd file into Library in one explicit action, optionally linked.
- cwd and Library remain clearly separate in UI copy and data model.
