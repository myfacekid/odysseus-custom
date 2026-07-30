# Projects Suite Roadmap — Cohesion, motion, and intuitive layout

Living plan for **bringing the Projects section in line with the rest of the AI Harness** — sidebar chrome, shared primitives, spatial model, and motion. The tabbed workspace interior (G1–G8 in `docs/projects-ui-roadmap.md`) is done; this doc covers everything *around* and *between* those panes that still feels out of sync with Todos, Documents, Research, and the U1–U8 simplification pass.

Use this doc when starting future chats: *"Follow docs/projects-suite-roadmap.md Phase P1"*.

**Branch:** `feature/ldr-deep-research` (current)

**Last updated:** 2026-07-13

**Status:** P1–P9 shipped historically. **Paused.** Product direction moved to **Projects as a harness context layer** — see `docs/projects-context-layer-roadmap.md`. Workspace UI is hidden (`PROJECTS_UI_ENABLED = false`). Do not start new suite/workspace chrome work from this doc unless that roadmap explicitly revives a thin file viewer.

**Shipped (2026-07-11) — P9 layout + style:**

- **Right companion:** Chat \| Run moved from bottom band to a **right column** (`grid-area: companion`) so the center editor gets full vertical height. Composer docks inside the companion under chat/run.
- **Resize:** Companion width drag (legacy `footerHeight` storage remapped to right width). Minimize collapses companion to a slim vertical tab strip.
- **Harness chrome:** Forced project glass removed — opaque `var(--panel)` / `var(--bg)` / `var(--border)` like Notes/Documents. Underline tabs (Memory/Library pattern). Depth/breadth accents kept on underlines only. Uppercase micro-labels retired on project chrome.
- **Mobile:** Companion slides in from the right; edge grabber replaces bottom-sheet grabber.

**Needs your visual QA:** open a project → Chat/Run on the right; resize companion; Layout: Focus minimizes companion; compare opacity/borders to Notes/Documents.

**Prerequisite:** G1–G8 shipped (`docs/projects-ui-roadmap.md`). Backend/API changes should be minimal — work lives in `static/js/projects/*`, `static/style.css`, `static/index.html`.

**Guiding rule (superseded):** ~~*Projects is a workspace mode, not a tool modal.*~~  
**Current rule:** *Projects is an optional context layer above the harness* (active project → scoped tools, chats, links). See `docs/projects-context-layer-roadmap.md`.

---

## Problem (today)

The workspace *inside* a project is modern (tabbed left/center/bottom, depth/breadth accents, quick open). The *integration* with the rest of the app is not. Users feel a context switch — not into a focused workspace, but into a different product.

| Problem | Where | Impact |
|---------|-------|--------|
| **Sidebar section is bare** | `#projects-section` — no overflow, sort, or context menus | Chats has sort/bulk/select; Projects is a flat list with folder icons |
| **Duplicate chrome layers** | `#project-workspace-header` + `#chat-top-bar` + `#project-mode-pill` | Three places say "you're in a project"; none feels authoritative |
| **Instant swap, no transition** | `.project-workspace-panel.hidden` toggles `display:none` | Chat → project is a hard cut; modals elsewhere use `modal-enter` / bottom-sheet slide |
| **Custom empty/loading UI** | `.project-pane-placeholder`, `.project-center-empty` | Research/Todos use `ui/feedback.js`; Projects reinvents the same patterns |
| **No shared tooltips** | Workspace header icon buttons | U6 shipped `ui/tooltip.js` for the rail; Projects still relies on native `title` |
| **Run work is invisible** | `runPanel.js` / `runBadge.js` isolated in footer | Research/Cookbook/Tasks surface background jobs via `activityStrip.js` |
| **Editor is a fork** | `projects/editor.js` vs `document.js` | Missing U3 Format popover parity; separate toolbar maintenance |
| **~479 bespoke CSS rules** | `.project-*` in `static/style.css` | Drifts from `.modal`, `.notes-pane`, `.doclib-*` families |
| **Mobile is an afterthought** | Fixed 220px left column; no grabber/drawer | Todos has full `notes-mobile-mode` (backdrop, swipe, bottom sheet) |
| **Spatial model is unclear** | Three tab bars + resize handles + split toggle at once | Power-user density without a clear "hero" zone or focus path for newcomers |
| **No motion system** | Zero `transition`/`animation` on project surfaces | Rest of suite uses `modal-enter`, domino cascades, dock-chip spring, bottom-sheet slide |

We already have the **primitives** — `modalManager` lifecycle patterns, `ui/feedback.js`, `ui/tooltip.js`, `activityStrip.js`, `contentViewer.js`, design tokens, and the U1–U8 overflow/composer conventions. Most of this work is **reuse and choreography**, not new machinery.

---

## Design goals

1. **Same chrome vocabulary.** Projects uses the same top bar, overflow menus, list-item patterns, and button sizes as Chats and the tool modals — not a parallel design language.
2. **One job per surface.** Sidebar lists projects; top bar shows context + rare actions; center pane is the hero for reading/writing; footer is for conversation and execution.
3. **Motion with purpose.** Transitions communicate *where you went* (chat → workspace), *what changed* (tab switch, panel resize), and *what finished* (run complete) — never decoration for its own sake.
4. **Progressive disclosure.** Default layout is calm: Links list + center empty state + Chat footer. Split view, resize handles, and overflow menus are opt-in power features.
5. **Respect `prefers-reduced-motion`.** All P7 animations collapse to instant state changes or opacity-only fades.
6. **Projects stays a workspace mode.** Do not move it into `toolRegistry.js` or `modalManager` — unify chrome, not shell architecture.
7. **No backend scope creep.** Layout, motion, and chrome only; APIs unchanged unless a small meta endpoint helps sidebar richness (e.g. link/file counts).

---

## Decisions locked in

| Decision | Choice |
|----------|--------|
| Shell model | **Keep main-area replacement** — projects *are* the primary surface when open |
| Navigation registry | **Do not add to `toolRegistry.js`** — sidebar section alongside Chats, not a tool |
| Top bar | **Merge into `#chat-top-bar`** — retire duplicate workspace header title row (P3) |
| Motion baseline | **Reuse suite easing** — `cubic-bezier(0.22, 1, 0.36, 1)` enter, `0.18s ease-in` exit (same as `modal-enter` / `modal-exit`) |
| Mobile left column | **Bottom sheet or swipe drawer** below 768px — not a permanent 220px column |
| Editor sharing | **Extract `editorChrome.js`** from `document.js` — both Documents and Projects import it (P4) |
| Default layout preset | **Links-first** for new projects (already G2 default); persist last layout per project |

---

## Suite motion system (P7 foundation)

Define one motion vocabulary so Projects animates like the rest of the harness, not in isolation.

### Timing tokens (add to `:root` or reuse existing)

| Token | Value | Used for |
|-------|-------|----------|
| `--motion-fast` | `120ms` | Tab underline, button hover, badge pulse |
| `--motion-medium` | `220ms` | Panel crossfade, footer expand, left drawer |
| `--motion-slow` | `320ms` | Workspace enter/exit, mobile bottom sheet |
| `--ease-spring` | `cubic-bezier(0.22, 1, 0.36, 1)` | Enter transitions (matches `modal-enter`, cookbook) |
| `--ease-out` | `cubic-bezier(0.22, 0.61, 0.36, 1)` | Sidebar width, resize handle release |

### What animates

| Event | Animation | Reference in codebase |
|-------|-----------|----------------------|
| Open project | Chat history fades out; workspace panel enters with `project-workspace-enter` (scale 0.98→1 + opacity) | Like `modal-enter` at `static/style.css` ~21856 |
| Close project | Reverse: workspace exits, chat history fades in | Like `modal-exit` |
| Left/center/bottom tab switch | Active indicator slides (`transform` on underline); pane content crossfades 80ms | Notes horizon chips |
| Center tab open/close | Tab strip: `dock-chip-in` spring; closed tab width collapses | `static/style.css` ~1126 `dock-chip-in` |
| Footer expand/collapse | Height animates via CSS `grid-template-rows` transition; expand btn rotates 180° | New |
| Left column collapse (P8) | Width → icon rail; labels fade out | Sidebar collapse at ~397 |
| Run starts / completes | Footer Run tab badge pulse (exists); activity strip pill slides in | `runBadge.js` + `activityStrip.js` |
| Empty state first paint | Hero icon + CTAs domino cascade (40ms stagger) | Sidebar list cascade ~1376 |
| Resize drag | No animation during drag; snap easing on release | Existing `workspaceResize.js` |
| Mobile drawer open | Bottom sheet `translateY(100%→0)` | `cookbook-modal-enter-mobile` ~21907 |

### Reduced motion

```css
@media (prefers-reduced-motion: reduce) {
  .project-workspace-panel,
  .project-left-pane,
  .project-bottom-pane,
  .project-center-well > * {
    animation: none !important;
    transition-duration: 0.01ms !important;
  }
}
```

---

## Intuitive layout model (P8 foundation)

The G1–G8 grid is functionally correct but cognitively dense. P8 reframes *hierarchy* without removing features.

### Spatial zones (user mental model)

```
┌─────────────────────────────────────────────────────────────┐
│  CONTEXT BAR — where am I? (unified chat-top-bar)           │
├──────────┬──────────────────────────────────────────────────┤
│  PICKER  │  FOCUS — read, write, preview (center well)      │
│  ~200px  │  This is the hero. Everything else supports it.  │
│  Links / │                                                  │
│  Files   │                                                  │
├──────────┴──────────────────────────────────────────────────┤
│  COMPANION — chat with the agent / run output (~35%)        │
│  Collapsible to a slim bar; expandable to majority height   │
├─────────────────────────────────────────────────────────────┤
│  COMPOSER — docked input (U2 simplified: model · + · send)  │
└─────────────────────────────────────────────────────────────┘
```

### Layout presets (per project, stored in `workspaceState.js`)

| Preset | Left tab | Footer height | Center | Best for |
|--------|----------|---------------|--------|----------|
| **Research** (default new) | Links | 35% Chat | Single well | Literature → notes → chat workflow |
| **Code** | Files | 40% Run | Single well | Editing + execution |
| **Focus** | Collapsed to icons | Minimized bar | Full height | Deep reading or writing |
| **Split** | Links | 35% Chat | Link + file side-by-side | Cross-referencing paper and code |

Preset is chosen automatically on first open (Links-first = Research). User can switch via header overflow → "Layout preset". Last preset persists.

### Progressive disclosure rules

| Control | Default visibility | Reveal when |
|---------|-------------------|-------------|
| Resize handles | Subtle 1px separator | Hover on edge, or after first manual resize |
| Split toggle | In center chrome | Always (low visual weight) |
| Footer expand | Slim bar with tab labels | Click expand, or Run starts |
| Left column | Full width | Collapse toggle in left tab bar |
| Quick open hint | Empty state only | Hidden after first `Ctrl+P` use |

---

## Phased delivery

Eight phases, ordered by impact and dependency. Rough estimate: **2–3 weeks** focused UI work. Each phase is independently shippable.

### P1 — Sidebar parity with Chats (highest impact, ~2 days)

Bring `#projects-section` up to the same affordance level as `#sessions-section`.

| Task | Notes |
|------|-------|
| Add `section-header-btn` overflow menu | Sort: last active / name; archive; select mode — mirror `#session-sort-btn` pattern |
| Right-click / long-press context menu | Rename, change folder, archive — reuse `#session-actions-dropdown` structure |
| List item meta line | "3 links · 12 files" or "Last active 2h ago" under title |
| Status badges | Keep ok/missing/warning; style with shared `.sidebar-notif-dot` / semantic tokens |
| Empty state CTA | "Create your first project" button, not plain text |
| Remove inline `style=` on list items | Consolidate into `.project-list-item` classes |

**Deliverable:** Projects sidebar feels like it belongs next to Chats, not an afterthought.

**Files:** `static/js/projects/index.js`, `static/index.html` (859–864), `static/style.css` (~39425)

---

### P2 — Shared UI primitives (~2 days)

Stop reinventing empty/loading/error/tooltip UI.

| Task | Notes |
|------|-------|
| Links list empty → `uiEmptyState()` | `static/js/ui/feedback.js` |
| File tree empty → same | |
| Link viewer loading → `showLoadingRow()` | |
| Link viewer error → `showError()` | |
| Workspace header icons → `initTooltips()` | `static/js/ui/tooltip.js` (U6) |
| Center empty hero | Keep hero layout; swap buttons to `.admin-btn-sm` / `.doc-action-icon-btn` |

**Deliverable:** Projects empty and loading states match Research and Todos.

**Depends on:** U6/U8 (shipped)

---

### P3 — Unified top bar (~1–2 days)

Kill the duplicate chrome layer.

| Task | Notes |
|------|-------|
| Promote project title into `#current-meta` | When workspace open, top bar shows project name + status |
| Move rename / change-folder / archive into overflow | Extend `#export-dropdown-wrap` pattern or project-specific `⋯` menu |
| Retire `#project-workspace-header` title row | Keep warning banner and meta path as a slim sub-row if needed |
| Remove or repurpose `#project-mode-pill` | Redundant once top bar owns context |
| Restore export overflow affordances hidden today | `#export-dropdown-wrap { display: none }` in project mode — project menu should offer equivalent actions |

**Deliverable:** One authoritative context bar; no "where am I?" confusion.

**Principle:** U-roadmap *one job per surface* — top bar = context + rare actions.

---

### P4 — Editor parity with Documents (~3–4 days)

Close the gap between `projects/editor.js` and `document.js`.

| Task | Notes |
|------|-------|
| Extract shared `static/js/ui/editorChrome.js` | Toolbar, status line, Format popover host — from `document.js` |
| Projects editor imports `editorChrome` | Save, Reload, Preview, Run stay; Format folds into popover (U3 pattern) |
| Consistent button sizing | `.doc-action-icon-btn` everywhere |
| "Open in Documents" overflow action | For files that need full doc-panel features |

**Deliverable:** Editing a `.py` or `.md` file feels identical to the Documents panel.

**Depends on:** U3 Format popover (shipped)

---

### P5 — Activity strip integration (~1 day)

Surface background run work the way Research does.

| Task | Notes |
|------|-------|
| Register project runs with `activityStrip.js` | Pill: "Running `analysis.py`…" → click focuses Run tab |
| Completion toast | Reuse `showToast` + existing `runBadge.js` error state |
| Strip entry clears when run panel focused | Same dismiss pattern as research jobs |

**Deliverable:** Users never miss a finished run because the footer was collapsed.

---

### P6 — Mobile and narrow viewport (~2–3 days)

Match Todos mobile patterns.

| Task | Notes |
|------|-------|
| Left column → bottom sheet below 768px | Swipe up to pick Links/Files; backdrop dismiss |
| Footer → swipe-up drawer | Grabber handle (like `notes-pane` mobile) |
| Composer dock QA | Verify U2 simplified composer in `#project-workspace-composer` |
| Project list long-press | Context menu (from P1) |
| Tap targets | Min 44px on list items and tab bars |

**Deliverable:** Projects is usable on a phone, not just tolerable.

**Reference:** `body.notes-view .notes-pane` rules ~29671; `cookbook-modal-enter-mobile`

---

### P7 — Motion and transitions (~2–3 days)

Wire the suite motion system (see above).

| Task | Notes |
|------|-------|
| `project-workspace-enter` / `project-workspace-exit` keyframes | Open/close project in `index.js` — add/remove class before `hidden` toggle |
| Tab indicator slide | Left/center/bottom active tab underline |
| Center pane crossfade | On tab switch in `tabHost.js` |
| Footer height transition | CSS `grid-template-rows` on `#project-workspace-grid` |
| Empty state domino cascade | `.project-center-empty` children stagger in |
| `prefers-reduced-motion` guard | Global project animation override |
| No JS during drag | Resize keeps instant feedback; easing on release only |

**Deliverable:** Opening a project feels like entering a workspace, not a page reload.

**Files:** `static/style.css` (new `@keyframes`), `static/js/projects/index.js`, `workspaceShell.js`, `tabHost.js`

---

### P8 — Intuitive spatial layout (~3–4 days)

Reframe hierarchy and presets (see layout model above).

| Task | Notes |
|------|-------|
| Layout presets in `workspaceState.js` | Research / Code / Focus / Split |
| Preset picker in top-bar overflow | |
| Left column collapse to icon-only | Toggle in left tab bar; width animates (P7) |
| Footer minimized mode | Slim bar showing active tab + expand chevron; click or Run auto-expands |
| Resize handle progressive disclosure | Hidden until hover or first resize |
| First-run layout coach | One-time tooltip: "Links are your papers; Files are your code" (reuse `tourHints.js`) |
| Focus preset | Hides left + minimizes footer; center goes full height |

**Deliverable:** New users understand the depth/breadth model without reading docs; power users get presets.

---

## Cross-cutting principles (apply in every phase)

- **One job per surface** — sidebar lists, top bar contextualizes, center reads/writes, footer converses/executes.
- **Consistency over cleverness** — same overflow, same tooltip, same motion tokens as the rest of the harness.
- **Reuse, don't fork** — `ui/feedback.js`, `ui/tooltip.js`, `activityStrip.js`, `editorChrome.js`, `modal-enter` easing.
- **Motion communicates state** — enter/exit, tab change, run complete; never animate for decoration.
- **Test on mobile first for density** — if the layout only works by hiding half its controls, it is too dense on desktop too.

---

## File map

| Area | Primary files |
|------|----------------|
| Sidebar list | `static/js/projects/index.js` (`_renderProjectList`), `static/index.html` (859–864) |
| Top bar merge | `static/js/projects/index.js`, `static/index.html` (1047–1054), `static/app.js` |
| Shared primitives | `static/js/ui/feedback.js`, `static/js/ui/tooltip.js` |
| Editor chrome | **new** `static/js/ui/editorChrome.js`, `static/js/projects/editor.js`, `static/js/document.js` |
| Activity strip | `static/js/activityStrip.js`, `static/js/projects/runPanel.js`, `runBadge.js` |
| Motion | `static/style.css` (new `@keyframes`, transition tokens), `workspaceShell.js`, `tabHost.js` |
| Layout presets | `static/js/projects/workspaceState.js`, `workspaceShell.js` |
| Mobile | `static/style.css` (new `@media` block), `workspaceShell.js` |
| Onboarding | `static/js/tourHints.js` |
| Styles | `static/style.css` (`.project-*` ~39425+, motion tokens in `:root` ~6–74) |
| Tests | **new** `tests/ui/projects-suite.test.mjs` (source invariants per phase) |

---

## Behavior preserved (must not regress)

- G1–G8 workspace: left/center/bottom tabs, depth/breadth accents, quick open, split, resize, pin, tab restore
- Project chat dock + `project-chat-docked` / model picker fixes
- Agent tool policy + preamble
- Save-before-run + disk conflict in editor
- Link picker, stale remove, research → project flows
- `active_project_file` injection on chat send
- Close project / dirty editor guards
- Theme-aware `--project-depth-accent` / `--project-breadth-accent` tokens

---

## Open questions

| # | Question | Default lean |
|---|----------|--------------|
| 1 | Top bar overflow: extend `#export-dropdown-wrap` or new `#project-overflow-menu`? | **New project menu** — export actions are chat-specific |
| 2 | Sidebar meta line: link/file counts live or extra API round-trip? | **Lazy fetch** on list render — cache 30s |
| 3 | Layout presets: explicit picker or infer from last left tab + footer height? | **Explicit presets** with auto-suggest on first open |
| 4 | Focus preset: hide left column entirely or icon-only? | **Icon-only** — keeps tab switching one click |
| 5 | Workspace enter animation: scale+fade or slide-up? | **Scale+fade** (matches `modal-enter`) — slide reserved for mobile drawers |
| 6 | Retire `#project-workspace-header` entirely or keep as slim warning/meta bar? | **Slim bar** for path + warning only; title moves to top bar |
| 7 | `editorChrome.js` extraction: one PR or incremental behind feature flag? | **Incremental** — toolbar first, Format popover second |

---

## Testing checklist

| Check | Phase |
|-------|-------|
| Projects overflow menu: sort, archive, select mode | P1 |
| Long-press project → rename / archive | P1 |
| Empty links list uses `uiEmptyState` markup | P2 |
| Header icon tooltips on hover, focus, long-press | P2 |
| Open project → title in `#current-meta`, no duplicate header title | P3 |
| Edit `.md` file → Format popover matches Documents | P4 |
| Run `.py` → activity strip pill → click focuses Run tab | P5 |
| Below 768px: left column is a drawer, not fixed column | P6 |
| Open/close project animates; reduced-motion disables it | P7 |
| Switch center tab crossfades content | P7 |
| Layout preset "Focus" → center full height, footer minimized | P8 |
| Full pass on narrow viewport per phase | all |
| `node --test tests/ui/projects-suite.test.mjs` passes | all |

---

## Related docs

| Doc | Relationship |
|-----|--------------|
| `docs/projects-ui-roadmap.md` | G1–G8 tabbed workspace interior (complete) — prerequisite |
| `docs/projects-roadmap.md` | Feature phases A–F; backend and agent tooling |
| `docs/ui-simplification-roadmap.md` | U1–U8 harness-wide simplification — shared primitives and principles |
| `README.md` / `docs/setup.md` | Feature overview; setup/architecture in the setup guide |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-11 | Initial draft: P1–P8 suite integration — sidebar parity, shared primitives, unified top bar, editor parity, activity strip, mobile, motion system, intuitive layout presets |
| 2026-07-11 | P1 + P3 + P5 + P7 shipped; P2 partial (sidebar empty + header tooltips). Smoke test added. P4, P6, P8 pending. |
| 2026-07-11 | P2–P8 completed: mdFormat/editorChrome, layout presets, mobile drawers, tab crossfade, loading feedback. 11 smoke tests. Documents mdFormat migration deferred. |
| 2026-07-11 | P9: Chat/Run moved to right companion column; forced glass removed for harness-matched opaque chrome; underline tabs; mobile right drawer. |
