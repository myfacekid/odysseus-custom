# Odysseus UX Roadmap

Living plan for **whole-app pleasantness**: fewer surfaces, clearer names, honest feedback, and one primary action per screen.

**Status:** **U0 shipped** (2026-07-07). **U1 shipped** (2026-07-07). **U2 shipped** (2026-07-07). **U3 shipped** (2026-07-08). **U4** ready to implement.

**Last updated:** 2026-07-07 (v1.0)

**Use this doc when starting work:** *"Follow docs/ux-roadmap_v1.md Phase U1"*.

**Related docs (do not duplicate their implementation detail here):**

| Doc | Relationship |
|-----|----------------|
| [`learned-graph-connections-roadmap_v1.md`](learned-graph-connections-roadmap_v1.md) | **Connections inbox** mechanics, producers, L-phases — this UX doc owns **names & copy** only |
| [`projects-ui-roadmap.md`](projects-ui-roadmap.md) | Project workspace tabs — **G-phases** own layout; **U5/U8** own cross-app Library/navigation |
| [`deep-research-roadmap.md`](deep-research-roadmap.md) | Research backend & report quality |
| [`projects-roadmap.md`](projects-roadmap.md) | Project feature scope |

---

## Problem (today)

Odysseus is feature-rich but **chrome-heavy**. Users manage many coexisting modals (Library, Brain, Links, Research, Cookbook, Settings, Compare, Email, Tasks…), learn dual navigation (sidebar + icon rail), and encounter **the same concept under different names**.

| Symptom | Impact |
|---------|--------|
| **Modal overload** | Context lost between dock chips; hard to tell what is running vs finished |
| **Naming sprawl** | Links, Brain, Connections, Library, and Research overlap in user mental models |
| **Buried setup** | Zotero, search providers, endpoints live in Settings; empty states feel like failures |
| **Inconsistent feedback** | Loading vs empty vs misconfigured is ambiguous across panels |
| **Mobile silence** | Compare and other flows hidden with `display: none` — feels broken, not unsupported |
| **Power-user defaults** | Chat mode pills, session Tidy/bulk, research synapse viz on by default |

This roadmap **does not add features**. It converges surfaces, vocabulary, and patterns already in the codebase.

---

## Design principles

1. **One noun per concept** — user-facing copy uses the locked vocabulary below; compound paths (`Brain → Connections → Links`) are for dev docs only.
2. **One primary action per screen** — Research wizard pattern: Continue *or* Start, not both; collapse advanced fields.
3. **Setup before power** — first-run checklist surfaces endpoint + search + Zotero; Settings splits mentally into Setup / Power / Admin.
4. **Honest states** — every list distinguishes **loading**, **empty**, and **needs configuration** with an actionable next step.
5. **Surfaces are views** — align with learned-graph anti-sprawl: one queue, many views; no second “review app.”
6. **Mobile truth** — unavailable features say so; never silent removal.

---

## Locked vocabulary (anti-sprawl)

**Rule:** Every PR that touches user-visible strings must use these terms. Aliases in parentheses are **migrate-then-remove**, not permanent dual labels.

### Canonical map

| User sees | Meaning | Where it lives (UI) | Retire / never say |
|-----------|---------|---------------------|-------------------|
| **Chat** | Conversation with the agent | Main canvas + composer | — |
| **Brain** | Agent memory: **Memories** and **Skills** | `#memory-modal` | “Memory modal”, “memory bank” |
| **Connections** | **Pending** graph proposals awaiting your approval | Brain → **Connections** tab | “Brain → Connections”, “link inbox”, “pending links”, “learned links queue” |
| **Links** | **Confirmed** knowledge graph — browse, search, rebuild | `#knowledge-modal` | “Knowledge graph”, “KG”, “graph browser” as primary labels |
| **Library** | Saved **artifacts**: chats, documents, research **reports** | `#doclib-modal` tabs | Using “Library” for the graph or for Connections |
| **Research** | Run composer + **active job queue** | `#research-overlay` | “Academic Research” duplicate title + body “Research” |
| **Projects** | Code workspace with linked breadth/depth | `#project-workspace-panel` | — |

### Scoped uses of “Links” (allowed, must be qualified in UI)

| Context | Label | Clarifier (subtitle or hint) |
|---------|-------|------------------------------|
| Global graph modal | **Links** | “Your confirmed knowledge graph” |
| Project left tab | **Links** | “Papers & documents linked to this project” (◆ breadth hint already in projects UI) |
| Settings → Zotero blurb | — | “Sync builds your catalog for **Links** and search” (not “Links and Brain”) |

**Connections** and **Links** are opposites in copy: *pending* vs *confirmed*. Never use “Links” for the approval inbox.

### Toast & empty-state templates (copy lock)

| Situation | Say | Don't say |
|-----------|-----|-----------|
| Proposal deferred | “Saved to **Connections**” (+ optional “Open Brain” action) | “Saved to Brain → Connections” |
| Proposal accepted | “Added to **Links**” | “Saved to knowledge graph” |
| No graph nodes | “No **Links** yet — add todos, documents, or memories, then **Rebuild**.” | “Open Brain” as the fix for an empty graph |
| No pending proposals | “No **Connections** waiting for review.” | “Empty inbox” without the word Connections |
| No Zotero catalog | “Sync your library in **Settings → Search → Zotero**.” | Scatter different Settings paths per panel |
| Research archive | “Past reports are in **Library → Research**.” | Duplicate full past-research UI in the compose panel |
| Misconfiguration | “**Setup needed:** …” with one deep link | Generic “Nothing here” |

### Navigation icons (sidebar + rail)

| Icon label | Opens | Tooltip one-liner |
|------------|-------|-------------------|
| **Brain** | Memories · Skills · **Connections** | “Agent memory and connection review” |
| **Links** | Graph explorer | “Browse your confirmed links” |
| **Library** | Chats · Documents · Research · Archive | “Saved chats, files, and reports” |
| **Research** | Compose + job queue | “Run deep research” |

**Do not** add a fifth graph entry point. Connections badge count lives on the Brain icon/tab only.

**Knowledge grouping (2026-07):** Brain and Links are visually clustered as one **"Knowledge"** area — a `.rail-group` pill around `#rail-memory` + `#rail-knowledge` in the icon rail, and a quiet "Knowledge" sub-label + left bracket over `#tool-memory-btn` + `#tool-knowledge-btn` in the sidebar Tools list. This is presentation only: they remain **two separate entry points and two separate panes** (no merge), the Connections badge stays on Brain, and no new entry point is added. Rationale: they read as "one knowledge thing" conceptually while respecting the locked pending-vs-confirmed (Connections vs Links) separation and the "Connections tab stays in Brain" decision. A full merge was considered and rejected (category mismatch — the graph is mostly artifacts, not agent memory — plus mega-modal cost and locked-vocabulary conflicts).

### Code ownership for copy changes

| Area | Files |
|------|-------|
| Graph / Connections / toasts | `static/js/knowledge.js`, `static/js/learned_connections.js` |
| Brain modal chrome | `static/index.html` (`#memory-modal`), `static/js/memory.js` |
| Links modal chrome | `static/index.html` (`#knowledge-modal`), `static/js/knowledge.js` |
| Library tabs | `static/js/documentLibrary.js` |
| Research panel | `static/js/research/panel.js` |
| Settings hints | `static/index.html` (settings panels), `static/js/settings.js` |
| Projects breadth copy | `static/index.html`, `static/js/projects/*` |

---

## Phase overview

| Phase | Theme | Effort | Depends on |
|-------|-------|--------|------------|
| **U0** | Vocabulary & copy convergence | Small | — |
| **U1** | Setup checklist & actionable empty states | Small | U0 |
| **U2** | Unified loading / empty / error patterns | Small | U0 |
| **U3** | Navigation clarity (one model per viewport) | Medium | U0 |
| **U4** | Chat composer simplification | Medium | U0 |
| **U5** | Library clarity & mobile card detail | Medium | U0, U2 |
| **U6** | Research background job tray | Medium | Research wizard (shipped) |
| **U7** | Mobile honesty | Small | U0 |
| **U8** | Workspace shell (modal reduction) | Large | `projects-ui-roadmap`, U3 |

---

## Phase U0 — Vocabulary & copy convergence

**Goal:** One pass over user-visible strings so **Links**, **Connections**, **Brain**, and **Library** never compete for the same job.

### Scope

- [x] Replace toast copy per table above (`knowledge.js`, `learned_connections.js`).
- [x] Brain → Connections tab description: lead with “**Connections**” in the H2; subtext explains they become **Links** when accepted (one sentence).
- [x] Links modal empty state: only mention **Rebuild** + prerequisites (Zotero sync path from template).
- [x] Research panel: single title “Research” (drop duplicate “Academic Research” in body if header carries context).
- [x] Library → Research tab subtitle: “Saved research reports” (not a second graph).
- [x] Grep guardrail: **Appendix D** — reviewers reject new strings containing `Brain →` or `knowledge graph` as primary UX label.
- [x] Settings **Integrations** panel H2 renamed (was “Connections”, collided with graph inbox).
- [x] Renamed user-facing “Deep Research” / “Academic Research” → **Research** in nav, panel, tours, and agent link text.

### Acceptance

- [x] Zero user-visible `Brain → Connections` strings (action may be “Open Connections”).
- [x] `Connections` appears only for **pending**; `Links` only for **confirmed** graph.
- [x] Sidebar, rail, and modal titles match the navigation table.

### Anti-sprawl gate

- [ ] No new modals or tabs for graph review (defers to L-phases in learned-graph doc).
- [ ] No rename of `#knowledge-modal` / `#memory-modal` IDs in U0 — **labels only**.

---

## Phase U1 — Setup checklist & actionable empty states

**Goal:** Users never wonder whether the app is broken, empty, or unconfigured.

### Scope

- [x] **Settings → Getting started** panel (new first tab or pinned card): three status rows — **Endpoint**, **Web search**, **Zotero catalog** — each with ✅ / ⚠️ and one “Fix” link to the exact sub-panel.
- [x] Shared empty-state helper `uiEmptyState({ kind: 'loading' | 'empty' | 'setup', title, action })` — stub in U1, full styling in U2.
- [x] Wire setup kind to: Links empty (no graph), Research seed picker (no Zotero), Connections (no pending — use `empty` not `setup`).
- [x] Deep links: `/settings?tab=search` (or existing `settings.js` `open('search')`) from every setup empty state.

### Acceptance

- [x] Fresh install: Links + Research show **Setup needed** with the same Zotero path string.
- [x] Getting started reflects live status after Zotero sync / endpoint save without reload.

---

## Phase U2 — Unified loading / empty / error patterns

**Goal:** Same visual language as `tasks.js` (no false “empty” before fetch) everywhere.

### Scope

- [x] `static/js/ui/feedback.js` (or extend `ui.js`): `showLoadingRow(parent)`, `showEmptyState(parent, opts)`, `showError(parent, { message, retry })`.
- [x] Migrate: `documentLibrary.js`, `memory.js`, `research/panel.js` job list, Brain Connections tab, Links graph load.
- [x] Boot loader: tie removal to `loadSessions().finally()` **and** drop hard 5s race — show “Still loading…” message after 8s instead of blank remove (`static/index.html` loader).
- [x] Errors: optional **Retry** button on failed fetches; toast for global failures only.

### Acceptance

- [x] No panel shows “No items” until `fetch` settles.
- [x] Spinner + copy consistent across Library, Brain, Links, Research jobs.

---

## Phase U3 — Navigation clarity

**Goal:** Users learn **one** navigation model per viewport.

### Scope

- [x] **Desktop:** Icon rail and expanded sidebar are two states of one nav (mutually exclusive — the rail only shows when the sidebar is collapsed). Made the rail a complete mirror by adding the missing **Links** launcher; both surfaces expose the same tools.
- [x] **Mobile:** Single entry — hamburger sidebar; rail hidden unless `mobile-mini` state is explicitly taught (one hint in `tourHints.js`).
- [x] Badge: Connections pending count on **Brain** icon only (not Links); rides whichever of rail/sidebar is visible.

### Acceptance

- [x] New user can open Brain, Links, Library, Research from one obvious strip per viewport.
- [x] `tourHints.js` covers: snap/minimize, Connections vs Links, Library vs Research archive.

**Shipped choice (desktop):** the rail and the expanded sidebar are the *same* nav in mini vs full form and never show together, so there are no simultaneous duplicate rows to remove. We instead made the two states consistent: added **Links** to the rail (it was the one tool missing) so either state reaches every tool, and put the Connections badge on Brain only. An earlier attempt to hide sidebar tool rows in favor of the rail was reverted — it made every tool unreachable in the default (sidebar-open) desktop state.

---

## Phase U3b — Sidebar section-header consistency (shipped)

**Goal:** The action control in **every** sidebar section header follows one grammar, so the same top-right corner never means three different things.

**Problem (observed):** expanded section headers put different verbs with unlabeled ~12px icons in the *same* slot — **Chats** = book (open Library) + sort-lines, **Projects** = `+` (create), **Models** = sort-lines, **Tools** = nothing (chevron). "Create" also lived in three unrelated spots (New Chat top row, Projects `+`, Library-row `+`), and the Chats book icon opened the **same** modal as Tools → Library.

**Locked grammar:**

- **Create lives at the top, not in headers.** Chats and Projects each get a dedicated top-level sidebar button (**New Chat**, **New Project**) — a matched create pair, same ecosystem. Section headers never carry a create `+`.
- `⋯` (kebab) = "more / sort / manage" for that list (Chats, Models).
- Tools/Projects have no header action → chevron only.
- Secondary/duplicate entry points move **into** the `⋯` menu (Chats → "Open in Library") rather than a separate icon.

### Scope

- [x] Chats header: drop the standalone Library (book) button; fold it into the `⋯` menu as **"Open in Library"**. Sort trigger uses the kebab (`⋯`) icon.
- [x] Models header: sort trigger uses the kebab (`⋯`) icon (options grammar).
- [x] Projects: **New Project** promoted to a top-level sidebar button next to **New Chat**; removed the header `+` (create no longer lives in a section header).
- [x] No new create/duplicate-nav icon introduced in a section header.

### Acceptance

- [x] Chats and Projects have symmetric top-level create buttons; no create action hides in a section header.
- [x] Every section-header action slot is either `⋯` (more) or empty (chevron) — never an ad-hoc icon.
- [x] Only one obvious way to reach the Library from the Chats area (`⋯` → Open in Library and Tools → Library land on the same modal).

---

## Phase U4 — Chat composer simplification (shipped)

**Goal:** Chat bar shows **what is on**, not every possible mode.

### Scope

- [x] ~~Hide indicators for inactive modes~~ — **already done**: every `.tool-indicator` is `display:none` until its mode is active; tools are enabled from the "+" overflow menu (which already carries `overflow-active-dot` markers and a `plus-active-dot` summary).
- [x] Collapse active indicators on mobile: when more than 3 are active, the per-tool chips hide and a single **"{n} on"** summary chip appears; tapping it opens the "+" tools menu (labelled toggles) to manage/deactivate. Avoided the word "Modes" — it collides with the Agent/Chat *mode* toggle (cross-phase no-new-synonym rule).
- [x] Agent vs Chat mode remains always visible (primary) — unchanged `mode-toggle`.

### Acceptance

- [x] Mobile composer shows ≤3 persistent chips, then a summary chip when more are active (`COLLAPSE_AT = 3`).
- [x] No icon-only pills without a label/tooltip on mobile: the persona chip hides only its name but keeps its `title`; the new summary chip has a visible count + `title`/`aria-label`.

**Shipped note:** the "hide inactive" half was already the app's behavior; the net-new work was the mobile overflow-collapse summary chip (`#tools-active-summary`, driven by a `MutationObserver` on the indicators so it stays decoupled from each owning module).

---

## Phase U5 — Library clarity & mobile detail (shipped)

**Goal:** Library tabs are distinguishable; expanded cards don’t feel like nested windows.

### Scope

- [x] Persist last Library tab in `localStorage` (`doclib.lastTab`). Plain opens (Tools → Library, `/library`) restore the last tab; explicit callers still win (Manage → Chats, Research panel → Research, import flows → Documents). Each panel already carries a heading + one-line description ("All active chat sessions…", "Saved research reports…", "Archived sessions…"), so the "subtitle" need was already met.
- [x] "Manage Chats" opens **Library → Chats** (via U3b's `⋯` → "Open in Library" → `openLibrary('chats')`) — same modal, highlighted tab, no separate list implementation.
- [x] ~~Mobile detail sheet (`doclib-detail-sheet`)~~ — the rename was aspirational. `doclib-card-expanded` on mobile **already** fills the panel (min-height 82dvh), strips the inner border/background/box-shadow so it no longer reads as a nested window, and hands the scroll to a single inner surface (`style.css` ~4290–4460). Behavior target already met.
- [x] Cross-link: Research job archive uses **Library → Research** (verified in U6).

### Acceptance

- [x] User can state which tab they’re in without reading the grid (per-panel heading + description).
- [x] Mobile expanded card scrolls one surface only (preview clips; inner `<pre>`/iframe owns scroll).

**Shipped note:** as with U4–U7, most of U5 was already in place from prior work. The one net-new change was tab persistence (with import/explicit callers pinned so they aren't hijacked by the remembered tab).

---

## Phase U6 — Research background job tray (shipped)

**Goal:** Running research feels like a **background job**, not a busy modal.

### Scope (builds on shipped wizard)

- [x] Default synapse visualization **minimized** for new users (`research.synapseMinimized` now defaults to `1` when unset; an explicit `0` is respected).
- [x] **Active** section: one-line status (phase, round, sources) — already provided by `jobs.formatPhase()` in the `.research-job-phase` line (e.g. "Round 2: Reading 15 sources"); synapse is collapsed by default now, so the status line is what shows.
- [x] Minimized research panel → rail/dock chip shows pulse + "R{n}" — already provided by `_syncResearchRail()` (`.research-sb-running` dot + `R${round}` on the Research tool button, rail-notify on the icon rail).
- [x] Completed jobs: primary actions hidden until expand (shipped); "Library → Research" archive link already present in the panel's empty-state and "Past research" header.

### Acceptance

- [x] New run: user sees question + status line without opening synapse (default-minimized).
- [x] Copy uses **Research** (queue) vs **Library → Research** (archive) per vocabulary — the panel already labels the archive cross-link exactly "Library → Research".

**Shipped note:** the wizard/rail/vocabulary work from prior phases already covered most of U6. The only behavior change needed was flipping the synapse default to minimized; the one-line status, rail `R{n}` chip, and archive cross-link were verified already in place.

---

## Phase U7 — Mobile honesty (shipped)

**Goal:** Unsupported flows explain themselves.

### Scope

- [x] ~~Compare hidden on mobile~~ — **premise stale.** Compare is *not* hidden on mobile; it has dedicated mobile handling (keyboard dismiss, popup repositioning). The only mobile-hide was a dead `#compare-toggle-btn` rule for an element that no longer exists — **removed**.
- [x] ~~Email `from-sender`~~ — **premise obsolete.** Email is no longer a tool. Removed the dead `body [data-act="from-sender"] { display:none }` guard rule (the "silent removal" this item worried about). Remaining `.from-sender-*` / `.email-*` styles are inert dead CSS — safe to leave; a bulk email-CSS purge is out of scope.
- [x] Documented desktop-only interactions in **Settings → Shortcuts** ("Desktop-only features" card): window snap/dock, drag-to-reorder, Rearrange, side-by-side Compare.

### Acceptance

- [x] No `display: none` on primary nav tools without a user-visible explanation. Audit confirmed: no `#tool-*-btn` is hidden on mobile; desktop-only *interactions* (not nav) are now explained in Settings.

**Shipped note:** like U4/U5, most of U7 was written against an earlier app state. The real deliverable was the desktop-only documentation + removing the dead compare rule; the compare/email "silent removal" concerns no longer apply.

---

## Phase U8 — Workspace shell (modal reduction) — shipped (U8a/U8b/U8c)

**Goal:** Long-term: **work in one place** instead of stacking modals.

**Defer implementation detail to** [`projects-ui-roadmap.md`](projects-ui-roadmap.md) **and** learned-graph **L3** (inbox views, not new apps).

**Reality check (2026-07):** much of U8's target already landed via the completed **Projects UI roadmap (G1–G8)** — the project workspace is already a tabbed shell (left `Links|Files`, center content well, bottom `Chat|Run`) whose center pane opens link/node detail **inline** (`projects/linkViewer.js`, `tabHost.js`), not in a modal. So U8 is less "build the shell" and more "unify how content is rendered" + "confirm nothing stacks."

### Direction

| Today | Target |
|-------|--------|
| Link detail in graph modal | Center tab in Projects; shared viewer component with Library |
| 14+ dockable modals | Chat + optional side panel; tools as tabs or sheets |
| Compare, Research, Cookbook full-screen | Sheet or bottom tray on desktop; full-screen sheet on mobile |

### U8 milestones (high level)

- [x] **U8a** — Shared content viewer module. New `static/js/ui/contentViewer.js` centralises body rendering (PDF / markdown / code / plain text) with size caps for hljs + `mdToHtml`. **Adopted by:**
  - **Library** (`documentLibrary.js` → `libraryExpandCard`) — replaced the three bespoke `<pre>`/hljs/iframe blocks (paper, PDF, document). Markdown documents now render as **formatted HTML** in the read-only preview instead of raw source; code/PDF/plaintext behaviour preserved.
  - **Projects center** (`projects/linkViewer.js` → `_highlightSnippet`) — breadth-tab snippet now goes through the same viewer.
  - Research report preview (`research/panel.js`) already routes through the shared `markdown.js` `mdToHtml`; it keeps its citation-aware wrapper (`[N]` → source sidebar links) rather than the generic path, so it is a *specialised consumer of the same renderer*, not a rewrite. Migrating its plain sections onto `contentViewer` is a low-value follow-up.
  - Reuses the existing `.doc-md-preview` markdown styles; app is monospace-first so no font override needed.
- [x] **U8b** — Graph node detail already opens **inline in a viewer pane, never a new modal stack**. Verified: standalone Links modal renders detail in the inline `#kg-detail` right pane (one modal, not nested); Projects renders it in `#project-link-viewer-pane` via `linkViewer.show()`. `openKnowledgeAtNode` opens the single Links modal + inline detail and has **no external callers**. No code change required beyond the audit; the shared viewer (U8a) is now available should the `#kg-detail` snippet want it later.
- [x] **U8c** — Single **Activity** strip (`static/js/activityStrip.js`). An auto-hiding floating pill (bottom-right) that appears only when something is running and expands to a list. Aggregates, with no new source of truth:
  - **Research** jobs via `research/jobs.getJobs()` (running/queued), with phase + elapsed from `formatPhase`/`formatElapsed`.
  - **Cookbook** tasks by reading the `cookbook-tasks` localStorage key directly (running/queued/ready). *Deliberately does not import the cookbook module* — the strip loads early in `app.js` and importing the cookbook graph there risks a circular top-level-init ordering bug; a plain localStorage read avoids that edge. (This was caught by the smoke test.)
  - **Task** runs via `GET /api/tasks/runs/recent` (running/queued), polled on a slow throttle (30s) since it needs the network; research + cookbook recompute on a 4s tick. This also gives Tasks the running indicator it never had.
  - Clicking a row opens the owning tool through its existing toolbar button (`#tool-research-btn` / `#tool-cookbook-btn` / `#tool-tasks-btn`). Low z-index so it never covers an open modal; top-right toasts are unaffected.
  - **Smoke-tested** (jsdom-free Node harness): content viewer factories + Activity aggregation — 18/18 assertions, incl. correct exclusion of completed items and the 4-item running/queued roll-up.

### Anti-sprawl gate

- [x] U8 introduced **no** new graph review surface. U8a/U8b only change *how* existing panes render content/detail; U8c's Activity strip is a status **indicator**, not a review surface — clicking always routes into the existing tool. Node review stays Brain tab + Links pop-up + Projects filter per learned-graph locked decisions.

---

## Cross-phase checklist

Before marking any U-phase done:

- [ ] Copy reviewed against **Locked vocabulary** table.
- [ ] Empty states use **loading / empty / setup** distinction.
- [ ] No new user-facing synonym for Links, Connections, Brain, or Library.
- [ ] Mobile changes include honesty or parity — not silent removal.
- [ ] Primary CTA count ≤1 per wizard step / compose screen.

---

## Appendix A — Sprawl audit (current → target)

| Current string / pattern | Target | Phase |
|--------------------------|--------|-------|
| “Academic Research” + “Research” | “Research” once | U0 |
| “Saved to Brain → Connections” | “Saved to Connections” | U0 |
| “Agent evidence tools” | “Sources” | Shipped (research) |
| Past research buttons always visible | Hidden until card expand | Shipped (research) |
| Compare `display:none` mobile | Disabled + explanation | U7 |
| Loader 5s timeout race | Readiness-aware loader | U2 |
| Chats in sidebar + Library + Manage Chats | One list, Library entry | U5 |
| Three graph review UIs | Pop-up + Connections + Advanced JSON only | L3 + U0 copy |

---

## Appendix B — Research UI (already shipped)

Reference for U6; no re-work unless regressions found.

- Two-step stepper with dot indicator; **Continue** (step 1) / **Start** (step 2) mutual exclusivity + `[hidden]` CSS fix.
- Sources as inline pills; Report length inline with Sources.
- Plan grid collapsed to Keywords + Scope; “Refine plan (optional)” disclosure.
- Run settings under “Advanced run settings”.
- Required fields: question or seeds → keywords before start.
- Orbiting pane animation removed.
- Job action buttons: icon + label consistency; Connections CTA as primary accent on done cards.

---

## Appendix C — Suggested implementation order

1. **U0** — cheap, unblocks all copy work; do alongside L1 learned-graph touch-ups.
2. **U1 + U2** — highest pain reduction for new users.
3. **U7** — small, builds trust on mobile.
4. **U4 + U5 + U6** — parallelizable by area owner.
5. **U3** — navigation breaking change; ship with tour update.
6. **U8** — strategic; align with `feature/projects` workspace merges.

---

## Appendix D — Copy review (contributing)

When adding or changing **user-visible** strings in UI, toasts, tours, notifications, or agent messages surfaced in chat:

1. Use the **Locked vocabulary** table — one noun per concept.
2. **Reject** new copy that uses:
   - `Brain → …` path notation (say **Connections** or **Open Connections** instead)
   - `knowledge graph` as the primary label (say **Links** for confirmed edges)
   - **Connections** for pending API integrations (say **Integrations** in Settings)
3. **Pending** proposals → **Connections**. **Confirmed** edges → **Links**. **Saved reports** → **Library → Research**.
4. Dev comments and internal module names may keep legacy terms; user-facing text may not.

`rg 'Brain →|knowledge graph' static/ src/` should return **comments and docs only** after U0.
