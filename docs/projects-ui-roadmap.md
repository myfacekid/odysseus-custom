# Projects UI Roadmap — Tabbed workspace layout

Living plan for **redesigning the project workspace shell** on `feature/projects`. Functionality from Phases A–E stays; this doc covers **layout, tabs, visual hierarchy, and editor richness** only.

Use this doc when starting future chats: *"Follow docs/projects-ui-roadmap.md Phase G1"*.

**Branch:** `feature/projects`

**Last updated:** 2026-06-01

**Status:** G1–G8 implemented. Optional future: center split ratio drag, tab reorder polish, footer maximize.

**Prerequisite:** Phases A–E feature-complete (file tree, editor, run, chat, links rail, tool policy). Backend/API changes should be minimal.

---

## Problem (today)

The current workspace uses a **5-cell CSS grid** with dashed region borders and fixed roles:

```
┌ tree ────┬── editor (tall) ──┬ links ─┐
│          │                   │       │
├ run ─────┤                   │       │
│          │                   │       │
├ chat ────┴───────────────────┴───────┤
│  (chat spans 2 cols)     links rail │
└──────────────────────────────────────┘
```

(`static/style.css` → `.project-workspace-grid`; `static/index.html` → `#project-workspace-panel`)

| Issue | Impact |
|-------|--------|
| **Links rail steals ~240px** right column while editor is already narrow | Linked papers + file editing both feel cramped |
| **Run panel is a separate small row** under the file tree | stdout/stderr gets ~14% row height; hard to read tracebacks |
| **Chat and run never share focus** | User splits attention between three bottom/side zones |
| **Link detail opens in modal** (`openKnowledgeAtNode`) | Breaks “work in one place” flow; rail is list-only |
| **Visual language is placeholder-ish** | Dashed `.project-region` boxes, uppercase micro-labels, weak depth/breadth distinction |
| **Project editor is v1** | Line numbers + highlight overlay; missing document-panel affordances (toolbar density, preview, status chrome) |

We have the **tools** (tree, editor, run, chat, links, agent policy). We do not yet have a **workspace** that gives them room or a clear mental model.

---

## Design goals

1. **More usable pixels** — collapse redundant regions; one primary column for reading/writing.
2. **Tabs over tiles** — three tab systems (left list, center content, bottom workspace) instead of five simultaneous panes.
3. **Never confuse depth vs breadth** — color, iconography, and tab chrome must distinguish **cwd files** from **graph links**. Colors must stay **visually distinct in every theme** (built-in and custom), not just in the default palette.
4. **Links-first** — opening a project shows linked knowledge before the file tree (literature → code workflow).
5. **Reuse proven patterns** — document panel UX (`document.js`, `.doc-editor-*` CSS) for the center pane where possible; do not fork business logic into a second document app.
6. **No backend scope creep** — layout is `static/js/projects/*`, `static/style.css`, `static/index.html`; APIs unchanged unless a small read endpoint helps link preview.

---

## Target layout (v1)

Two columns + one full-width footer band. **Three tab bars.**

```
┌─ LEFT (~220px) ────────┬─ CENTER (flex) ─────────────────────────────┐
│ [ Links | Files ]      │ [ ● paper:ABC | ○ analysis.py | + ]           │  ← center tabs
│ ─────────────────      │ ┌ breadth accent bar ─────────────────────┐ │
│  (list for active      │ │  Rich viewer OR project file editor      │ │
│   left tab)            │ │  (single shared content well)            │ │
│                        │ └──────────────────────────────────────────┘ │
├────────────────────────┴──────────────────────────────────────────────┤
│ [ Chat | Run ]                                                          │  ← bottom tabs
│  (project chat sidebar + history  OR  run output panel)                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### Tab system 1 — Left: **Links | Files**

| Tab | Default? | Content |
|-----|----------|---------|
| **Links** | ✅ Yes | Today’s `#project-links-mount` list + link picker + stale cleanup (no separate right rail) |
| **Files** | | Today’s `#project-file-tree` + tree toolbar |

- Switching tabs **does not close** center tabs; it only changes the list on the left.
- Persist last left tab per project in `workspaceState.js` (default `links` for new projects).

### Tab system 2 — Center: **open link | open file** (multi-tab)

One shared **content well** (today’s `#project-editor-region` footprint, full height).

| Tab type | Source | Tab chrome |
|----------|--------|------------|
| **Breadth / link** | Click row in Links list | Warm palette — reuse `.kg-type-*` hues; left accent bar; “link” icon; show `paper:`, `research:`, etc. |
| **Depth / file** | Click file in Files tree | Cool palette — `--hl-function` / blue accent; “file” icon; show relative path |

Rules:

- Clicking a link **opens or focuses** a breadth tab in the center (does not open Links modal by default).
- Clicking a file **opens or focuses** a depth tab (existing `editor.js` open/save/disk logic).
- **Color coding is mandatory** at tab strip, content header, and optional left border — user must never wonder “is this Zotero or my repo?”
- Colors **must track the active theme** (`theme.js` → CSS variables). No fixed hex in project workspace chrome except `var(..., fallback)` last resorts.
- **Depth and breadth use different hue families** (cool vs warm), not just different opacity on the same accent — so they remain distinguishable on monochromatic and complementary themes alike.
- Center empty state: “Select a link or file” with short copy on depth vs breadth.

**Feature-rich center (parity targets with Documents panel):**

| Capability | Depth (file) | Breadth (link) |
|------------|--------------|----------------|
| Syntax highlight + line numbers | Done — keep as-is | Read-only markdown/code render where applicable |
| Toolbar (save, reload, run) | Save, Reload, **Run** (`.py`) | Open in Links hub, Open report/PDF, Remove link |
| Save / dirty / disk conflict | Done | N/A (read-only) |
| Autosave | Done | N/A |
| Scroll sync / wrap | Match `.doc-editor-wrap` | Same scroll container |
| Preview mode | Defer HTML/MD preview to G5 | Research excerpt + paper snippet from graph |
| Tab close + unsaved guard | Yes | Yes (close tab only) |

Implementation note: extract shared **tab strip + pane host** component (`static/js/projects/tabHost.js`) rather than three copy-paste tab implementations.

### Tab system 3 — Bottom: **Chat | Run**

| Tab | Content |
|-----|---------|
| **Chat** | Today’s `chatSidebar.js` dock (`#project-chat-pane`) — sidebar list + main history |
| **Run** | Today’s `runPanel.js` — stdout/stderr, exit code, re-run, copy |

- **Run tab auto-focus** when user clicks Run in editor (optional toast if already on Chat).
- Run panel gets **full footer height** (~40–45% of workspace), not a 72px sliver.
- Chat input bar stays **below** the workspace panel (existing `#chat-input-bar` dock behavior unchanged).

---

## Visual design direction

Move from “labeled wireframe regions” to **product chrome**:

| Element | Today | Target |
|---------|-------|--------|
| Region borders | Dashed `.project-region` | Subtle solid border or inset shadow; no dashed lines in steady state |
| Region labels | `File tree · depth` uppercase | Remove; tabs + icons carry meaning |
| Depth accent | `--hl-function` on run btn only | Tab strip, header bar, run tab badge — via `--project-depth-accent` |
| Breadth accent | `.kg-type-paper`, `.kg-type-research` | Link tabs + viewer header — via `--project-breadth-accent` |
| Spacing | 8px grid gap, tight | 8–12px; center pane gets priority width (no 240px links column) |
| Typography | 10–11px meta everywhere | 12px body in center; meta one step smaller |

Responsive: below ~900px, collapse left column to icon tabs or drawer (defer to G7 polish).

---

## Theme-aware color system (required)

Project workspace colors **must respect theme choice** the same way syntax highlighting and Links badges do today. Hardcoded blues/greens in `.project-*` rules are not acceptable for accent chrome.

### Two boundary tokens (always distinct)

| Token | Boundary | Source (theme-relative) | Used on |
|-------|----------|-------------------------|---------|
| `--project-depth-accent` | **Depth** (cwd files, run, Python) | Cool lane: `--hl-function` | Files left tab (active), file center tabs, file viewer header bar, Run bottom tab, run output top border |
| `--project-breadth-accent` | **Breadth** (graph links) | Warm lane: `--accent-warm`, else `--accent-primary` | Links left tab (active), link center tabs, link viewer header bar |

**Rule:** depth and breadth must never resolve to the same computed color. Implementation in `theme.js` → `applyColors()`:

1. Set `--project-depth-accent` from `--hl-function` (already derived per theme via `deriveSyntaxColors`).
2. Set `--project-breadth-accent` from `--accent-warm` (falls back through syntax string/number, then accent primary).
3. **Contrast guard:** if computed depth and breadth hex values are equal (or Δhue &lt; 45° on custom themes), nudge breadth hue toward `--accent-primary` / `--red` so the pair stays separable. Log once in dev builds if guard fires.

Sub-types within breadth (paper vs research vs document) may still use existing `.kg-type-*` tints on badges, but **tab chrome** uses `--project-breadth-accent` as the primary “this is a link” signal so file tabs never share that hue family.

### Where color appears (minimum)

| Surface | Depth | Breadth |
|---------|-------|---------|
| Left tab (active) | Files tab underline + faint bg tint | Links tab underline + faint bg tint |
| Center tab (inactive/active) | Left border + icon | Left border + icon |
| Center content header | Accent bar + “Depth · path” label tint | Accent bar + “Breadth · node id” label tint |
| Bottom tab (active) | Run | Chat neutral (theme panel fg/bg only) |

Use `color-mix(in srgb, var(--project-*-accent) N%, transparent)` for backgrounds so light and dark themes both read clearly. Text on tinted headers stays `var(--fg)` — accents are bars/borders, not colored body text (keeps contrast).

### CSS (add to `static/style.css`)

```css
/* Set in theme.js on apply; fallbacks for first paint only */
:root {
  --project-depth-accent: var(--hl-function, #61afef);
  --project-breadth-accent: var(--accent-warm, var(--accent-primary, #e5a040));
  --project-depth-surface: color-mix(in srgb, var(--project-depth-accent) 12%, var(--panel));
  --project-breadth-surface: color-mix(in srgb, var(--project-breadth-accent) 12%, var(--panel));
}

.project-tab--depth { border-left: 3px solid var(--project-depth-accent); }
.project-tab--breadth { border-left: 3px solid var(--project-breadth-accent); }
.project-left-tab--files.active { box-shadow: inset 0 -2px 0 var(--project-depth-accent); }
.project-left-tab--links.active { box-shadow: inset 0 -2px 0 var(--project-breadth-accent); }
```

### Theme testing (G3 + G6 gate)

Before sign-off, spot-check **every built-in theme** plus one custom harmony theme:

- [ ] Files tab active vs Links tab active — clearly different hues
- [ ] Open file tab vs open link tab side-by-side — distinct at a glance
- [ ] Run tab vs Chat tab — Run reads as depth (cool), not breadth
- [ ] Light + dark variants — neither accent washes out on `--panel`

Document failures in a short checklist in `tests/` or manual QA notes; do not ship G3 without passing this matrix.

---

## Grid CSS (target)

Replace `.project-workspace-grid` template:

```css
grid-template-columns: minmax(200px, 240px) minmax(0, 1fr);
grid-template-rows: minmax(0, 1fr) minmax(180px, 42%);
grid-template-areas:
  "left center"
  "workspace workspace";
```

Remove grid areas: `tree`, `run`, `links` as separate cells. `#project-workspace-panel` children restructured in HTML (G1).

---

## Phased delivery

Estimate **3–4 weeks** focused UI work after E sign-off. Each phase is shippable.

### G1 — Shell refactor (2–3 days)

| Task | Notes |
|------|-------|
| Restructure `static/index.html` workspace DOM | `#project-left-tabs`, `#project-center-tabs`, `#project-workspace-tabs` |
| New grid CSS | Remove 5-cell template |
| `static/js/projects/workspaceShell.js` (new) | Mount tab hosts; wire empty states |
| No behavior change yet | Old modules mount into new slots |

**Deliverable:** Same features, new geometry; may regress polish temporarily.

### G2 — Left tabs: Links \| Files (2 days)

| Task | Notes |
|------|-------|
| Default tab = **Links** | |
| Move links rail into left pane | Drop right `#project-links-rail` column |
| File tree mounts only when Files tab active | Lazy mount OK |
| Persist `leftTab` in `workspaceState.js` | |

**Deliverable:** Links-first sidebar; file tree one click away.

### G3 — Center tabs + color system (4–5 days)

| Task | Notes |
|------|-------|
| `tabHost.js` — generic tab strip | close, focus, max tabs optional |
| Breadth tab: inline link viewer | New `static/js/projects/linkViewer.js` — fetch neighbors / read API; render title, meta, snippet, actions |
| Depth tab: wrap existing `editor.js` | One editor instance or one instance per open file (start with single editor + tab switch) |
| **Theme-aware accent tokens** | Wire `--project-depth-accent` / `--project-breadth-accent` in `theme.js` `applyColors()`; contrast guard; CSS uses tokens only |
| Color rules enforced in CSS | `.project-tab--depth`, `.project-tab--breadth`, left/bottom tab active states |
| Replace modal-first navigation | Row click → center tab; “Browse in Links” remains overflow |
| **Theme matrix QA** | All built-in themes + one custom — depth/breadth never collide |

**Deliverable:** Link paper and `analysis.py` open as tabs in same well; visually distinct.

### G4 — Center richness (4–5 days)

| Task | Notes |
|------|-------|
| Depth editor toolbar parity | Match document panel: status line, keyboard hints, consistent btn sizes |
| Breadth viewer layouts by type | paper / research / document / task templates |
| Read-only highlight for link bodies | Reuse highlight.js language map |
| Stale link rows | Open stale tab shows warning banner + remove action |

**Deliverable:** Center pane feels like Documents, not a placeholder textarea.

### G5 — Bottom tabs: Chat \| Run (2–3 days)

| Task | Notes |
|------|-------|
| Merge chat + run into `#project-workspace-footer` | |
| Remove standalone `#project-run-pane` grid cell | Run button in editor switches to Run tab |
| Increase run output min-height | |
| Persist `bottomTab` per project | |

**Deliverable:** Chat and execution share one large band; run output readable.

### G6 — Polish & persistence (2–3 days)

| Task | Notes |
|------|-------|
| Remove dashed borders / legacy labels | |
| Open center tabs restore on project open | paths + link ids in `workspaceState` |
| Keyboard shortcuts | `Ctrl+1/2` left tabs; `Ctrl+W` close center tab (optional) |
| Mobile / narrow fallback | Stack or hide left column |

**Deliverable:** Stylish, cohesive workspace; state survives refresh.

### G7 — Optional follow-ups (not v1)

- Drag-resize left column and footer height (Phase D v2 from main roadmap) — **done** (`workspaceResize.js`)
- Split center (side-by-side link + file) — **done** (`workspaceSplit.js`, Split toggle)
- Markdown/HTML preview for cwd files — **done** (editor Preview button)
- Pin tab / tab reorder — **done** (pin control + drag reorder on center tabs)

### G8 — Discoverability & polish (done)

| Task | Notes |
|------|-------|
| Hero empty states + left CTAs | Center, Links, Files empty heroes with action buttons |
| Tab overflow menu + dirty dots + run badge | `⋯` menu, unsaved dot on depth tabs, Run tab pulse/error badge |
| Quick open (`Ctrl+P`) | `workspaceQuickOpen.js` — fuzzy picker for files + links |
| Editor status line + toolbar parity | Line/char count, icon save/reload/preview/run in header |

**Deliverable:** Workspace feels guided on first open; power-user navigation without leaving the shell.

---

## File map

| Area | Primary files |
|------|----------------|
| HTML shell | `static/index.html` (`#project-workspace-panel`) |
| Layout / orchestration | `static/js/projects/index.js`, new `workspaceShell.js`, `tabHost.js` |
| Left Links | `static/js/projects/index.js` (`_renderLinksRail`), `knowledge.js` (picker) |
| Left Files | `static/js/projects/fileTree.js` |
| Center file | `static/js/projects/editor.js` |
| Center link | **new** `static/js/projects/linkViewer.js` |
| Bottom chat | `static/js/projects/chatSidebar.js` |
| Bottom run | `static/js/projects/runPanel.js` |
| State | `static/js/projects/workspaceState.js` |
| Quick open | **new** `static/js/projects/workspaceQuickOpen.js` |
| Run badge | **new** `static/js/projects/runBadge.js` |
| Styles | `static/style.css` (`.project-workspace-*`, tab tokens) |
| Themes | `static/js/theme.js` (`applyColors` — project depth/breadth tokens + hue guard) |
| Docs | This file; cross-link from `docs/projects-roadmap.md` |

---

## Behavior preserved (must not regress)

- Project chat dock + `project-chat-docked` / model picker fixes
- Agent tool policy + preamble (unchanged)
- Save-before-run + disk conflict in editor
- Link picker, stale remove, research → project flows
- `active_project_file` injection on chat send
- Close project / dirty editor guards

---

## Open questions

| # | Question | Default lean |
|---|----------|--------------|
| 1 | Single editor instance vs tab-per-file? | **Single instance** v1 (lower risk); tab switch swaps path + buffer section should have tabs, but only one can be edited at a time |
| 2 | Link viewer: full research report inline or excerpt + “Open full report”? | **Excerpt + actions** v1 — avoid multi-MB DOM excerpt only|
| 3 | Max open center tabs? | **10** with LRU close or “close others” menu |
| 4 | Bottom default tab on project open? | **Chat** (agent workflow); remember last |
| 5 | Left default tab for returning users? | **Links** first visit; persist last thereafter |
| 6 | Keep “Browse in Links” modal? | **Yes** as overflow; inline tab is primary |
| 7 | Same accent on monochromatic custom themes? | **No** — `applyColors` hue guard forces breadth ≠ depth |

---

## Testing checklist

| Check | Phase |
|-------|-------|
| Open project → Links tab active, list visible | G2 |
| Switch to Files → tree CRUD works | G2 |
| Open link + file → two center tabs, distinct colors | G3 |
| Depth/breadth accents distinct in light + dark built-in themes | G3 |
| Custom harmony theme — guard prevents identical depth/breadth | G3 |
| Edit file, switch tab, return → dirty state preserved | G3 |
| Run `.py` → switches to Run tab, output visible | G5 |
| Project chat send + model picker still work | G5 |
| Refresh page → restores open tabs (if G6 done) | G6 |
| Stale link → warning in center tab | G4 |

---

## Related docs

| Doc | Relationship |
|-----|--------------|
| `docs/projects-roadmap.md` | Feature phases A–F; IDE trajectory |
| `docs/deep-research-roadmap.md` | Research content in link viewer |
| Phase D “Layout v2” row | Superseded in detail by this doc |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-06-01 | Initial draft: tabbed left/center/bottom layout, color system, phases G1–G7 |
| 2026-06-01 | G1–G3 + G5: tabbed shell, inline link viewer, center tabs, theme accent tokens |
| 2026-06-01 | G4 + G6: viewer/editor chrome, stale link tabs, center tab restore, shortcuts, legacy CSS cleanup |
| 2026-06-01 | G7: panel resize, split view, md/html preview, pin + tab reorder |
| 2026-06-01 | G8: empty-state heroes, tab overflow, Ctrl+P quick open, editor status parity, run badge |
| 2026-06-01 | Theme-aware color system: `--project-depth-accent` / `--project-breadth-accent`, hue guard, theme matrix QA |
