# Projects as Context Layer — Roadmap

Living plan for **repositioning Projects** from an IDE-style workspace shell into an **optional harness-level context layer**: agent + cwd + linked concepts, without replacing the main app chrome.

Use this doc when starting future chats: *"Follow docs/projects-context-layer-roadmap.md Phase L1"*.

**Last updated:** 2026-07-22

**Status:** L0–L6 shipped. **F1–F5 project files pop-out** replaces the broken flat picker with a tree | reader sheet (read-only + promote).

**Supersedes (for product direction):** the “Projects is a workspace mode” guiding rule in `docs/projects-suite-roadmap.md`. That suite work (P1–P9) remains useful chrome reference if a thin file viewer returns later; it is **not** the target product shape.

**Related:** `docs/projects-ui-roadmap.md` (G1–G8 workspace interior — historical), `docs/projects-suite-roadmap.md` (suite cohesion — paused).

---

## Product thesis

Projects’ real promise is not a file tree + editor + Run panel. It is:

1. **Scoped agent context** — chats, research, and tools inherit an active project.
2. **A user-chosen cwd** — computational depth (read/write/run under that folder).
3. **Linked concepts** — curated graph links to papers, research, documents (breadth).

The harness stays the product. A project is a **layer above** it: turn it on, and those surfaces inherit scope. Turn it off, and Nobody behaves as today.

### Boundaries (keep separate)

| Domain | Owns | Does not |
|--------|------|----------|
| **cwd (project folder)** | Code, scripts, run outputs, agent file tools | Become Library folders; auto-mirror into Library |
| **Library** | App-owned corpus (docs, notes, ingested knowledge) | Mirror the project tree |
| **Graph links** | Explicit relationships between project ↔ papers/research/docs | Imply file copies |

**Promote is explicit:** user (or agent with confirmation) copies/imports a cwd file into Library. Never silent sync.

---

## Flags

- `PROJECTS_UI_ENABLED = false` — IDE workspace shell stays hidden.
- `PROJECTS_CONTEXT_LAYER_ENABLED = true` — chip, scope, promote.

File: `static/js/projects/featureFlag.js`

---

## Target UX (shipped)

```
┌─ Top / chrome ─────────────────────────────────────────┐
│  [ Project: Atlas ▾ ]  or  [ No project ]               │  ← global chip
└────────────────────────────────────────────────────────┘
  When active:
  • New chats tagged with project_id (tool policy + preamble)
  • Research inherits active project for link prompts
  • Agent: no free bash; cwd tools + promote_project_file
  • Browse project files → tree | reader pop-out → Add to Library
  • Knowledge: “Set active” on project nodes
```

---

## Phases

| Phase | Status | Notes |
|-------|--------|-------|
| L0 Pause & park | **done** | Workspace UI hidden |
| L1 Active project chip | **done** | `activeChip.js` / `activeState.js` |
| L2 Scope inheritance | **done** | Session `project_id`, chat filter, research/knowledge |
| L3 Tool policy | **done** | Pre-existing + `promote_project_file` |
| L4 Promote cwd → Library | **done** | API + agent tool |
| L5 Demote shell | **done** | Shell behind flag |
| L6 Polish & tests | **done** | Migration, animations, pytest + UI smokes |
| F1–F5 Files pop-out | **done** | Tree + read-only reader + promote ([`filePicker.js`](../static/js/projects/filePicker.js)) |

### Project files browser (F1–F5)

Dedicated modal (not Documents pane, not IDE workspace):

- **Left:** lazy read-only folder tree (depth accent)
- **Right:** `contentViewer` preview + **Project file** badge; **Add to Library…**
- Edit only after promote (Library Documents / Notes)
- Shell uses `.modal-content` so pointer-events work (fixes dead picker)

---

## Decisions (resolved)

1. **Chat model:** Always create under active project.
2. **Promote targets:** Documents, Notes, and raw Library ingest.
3. **Agent promote:** Tool + UI.
4. **Multi-project:** One active project at a time.
5. **Files browser:** Pop-out tree | reader; read-only peek + promote (not Documents pane edit).

---

## File map

| Area | Files |
|------|-------|
| Flags | `static/js/projects/featureFlag.js` |
| Chip | `static/js/projects/activeChip.js`, `activeState.js` |
| Files sheet | `static/js/projects/filePicker.js` |
| Promote API | `src/project_promote.py`, `routes/project_routes.py` |
| Sessions | `routes/session_routes.py`, `static/js/sessions.js` |
| Tools | `src/project_tool_policy.py`, `src/tool_schemas.py`, `src/tool_execution.py` |
| Tests | `tests/test_project_promote.py`, `tests/ui/projects-context-layer.test.mjs`, `tests/ui/project-files-sheet.test.mjs` |

---

## Success criteria

- User can run Nobody with **no project** and never see the IDE workspace shell.
- User can set an active project and have chat/research/tools inherit it without opening an IDE shell.
- User can browse cwd files in a working pop-out, preview them, and **promote** into Library.
- cwd and Library remain clearly separate in UI copy and data model (depth badge vs Library docs).
