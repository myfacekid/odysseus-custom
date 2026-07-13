# UI Simplification Roadmap — Clearer buttons, toolbars, and layout

A living plan for **making the whole app easier to use** by simplifying buttons, toolbars, and layout. The goal is a calmer, more predictable interface that the *majority* of users can navigate without a tour — not fewer features, just fewer things competing for attention at once.

Use this doc when starting future chats: *"Follow docs/ui-simplification-roadmap.md Phase U2"*.

**Branch:** `feature/ldr-deep-research` (current)

**Last updated:** 2026-07-10

**Status:** U1–U8 shipped (with noted deferrals). Awaiting your visual QA.

**Guiding rule:** *One job per surface.* Every toolbar should first answer "what is the user most likely to do here right now?" Everything else moves to overflow, a popover, or settings.

---

## Problem (today)

The app is a chat-centric shell that has grown to ~12 major tools. The features are strong, but the **interface asks the user to hold too much in their head at once**. Concretely:

| Problem | Where | Impact |
|---------|-------|--------|
| **Navigation is duplicated 3+ ways** | Sidebar Tools list, icon rail (`static/index.html` 765–793), URL routes, and the composer overflow menu | Users see the same tool in several places and can't tell which is "the" way in |
| **Icon rail is hand-maintained** | `static/index.html` 765–793 (static `<button>` per tool) | Rail and sidebar drift out of sync; adding/removing a tool means editing two lists |
| **Chat composer is dense** | `static/index.html` 1208–1370 | ~12–15 controls at peak (overflow, web, shell, tool indicators, mode toggle, model picker, send) |
| **Document editor stacks 3 toolbars** | `static/js/document.js` (~2512–2619) | ~35–40 controls across header + tab bar + markdown format row |
| **Settings → Appearance is a toggle wall** | `static/index.html` 1979–2172 | ~34 flat switches with no grouping |
| **Inconsistent names for one concept** | throughout | "Notes"/"Todos", "Brain"/"Memory", "Agent"/"Chat" — silent cognitive tax |
| **Icon-only controls lean on `title`** | rail, sidebar, toolbars | Weak discoverability, especially on touch devices |
| **Micro-labels and dashed chrome** | `.tool-subgroup-label` (uppercase 9px, opacity 0.4); dashed drag placeholders | Hard to read; placeholder-ish feel |
| **Dead / hidden UI** | `#pinned-tools-bar` (no populate logic), inert Deep Research checkbox, stubbed Email tab still referenced in tours | Confuses users and makes the surface harder to keep consistent |

We already have the right **primitives** — CSS design tokens, `modalManager.js`, overflow menus, a density setting, keyboard shortcuts, and tab hosts. Most of this work is **consolidation and reuse**, not new machinery.

---

## Design goals

1. **One way in per tool.** A single source of truth for navigation; other surfaces are derived from it, never hand-maintained copies.
2. **Progressive disclosure everywhere.** Show the 2–4 most-used actions; push the rest to a single overflow or popover.
3. **Frequency-based placement.** Daily actions inline, weekly actions in overflow, rare actions in settings.
4. **Consistent language.** One name per concept, one shared tooltip pattern, icons paired with labels in primary nav.
5. **Reuse proven primitives.** Extend existing overflow menus, tab hosts, tokens, and `modalManager` — do not fork new versions.
6. **Mobile is the honesty check.** If a surface only fits on mobile by hiding half its controls, it is too dense on desktop too.
7. **No backend scope creep.** Work lives in `static/index.html`, `static/style.css`, `static/app.js`, and `static/js/*`. APIs unchanged.

---

## Decisions locked in

| Decision | Choice |
|----------|--------|
| Canonical name: Notes vs Todos | **Todos** |
| Canonical name: Brain vs Memory | **Memory** |
| Navigation model | **Icon rail becomes an auto-generated projection of the sidebar** (single source of truth) |
| Scope | **All 8 strategies** (U1–U8) |
| Location | This doc: `docs/ui-simplification-roadmap.md` |

*(Agent vs Chat naming is still open — see Open Questions.)*

---

## Phased delivery

Eight phases, ordered by impact and dependency. Each phase is independently shippable. Rough estimate: **3–4 weeks** of focused UI work.

### U1 — Single navigation source (highest impact)

Make the sidebar the one source of truth for tool navigation; generate the icon rail from it.

| Task | Notes |
|------|-------|
| Define a **tool registry** (id, label, icon, route, group, order) | New `static/js/nav/toolRegistry.js`; one entry per tool |
| Render sidebar Tools list from the registry | Replace hand-written `list-item` rows |
| Render icon rail from the same registry | Rail becomes a **projection** — no per-tool `<button>` in HTML (`static/index.html` 765–793 shrinks to a mount point) |
| Group tools into **3–4 clear buckets** | e.g. *Knowledge* (Memory, Links, Library) · *Create* (Documents, Todos, Tasks) · *Explore* (Research, Compare, Cookbook) · *Life* (Calendar, Email) |
| Keep URL routes working | Routes resolve through the registry, not separate wiring |

**Deliverable:** Adding or removing a tool means editing one list. Sidebar and rail can never drift apart. Fewer top-level choices to scan.

**Shipped (2026-07-10):**

- New `static/js/nav/toolRegistry.js` — single source of truth (id, sidebar owner, rail id, title, icon, group, route) for all 11 tool launchers.
- Icon rail is now generated from the registry via `static/js/nav/railProjection.js` into a `#rail-tools-mount` placeholder; the per-tool `<button>`s were removed from `static/index.html`.
- The hand-maintained `_railToolMap` in `static/app.js` is now derived from the registry (`railToSidebarMap()`), so rail→sidebar delegation cannot drift.
- Dev-time drift guard (`checkNavParity`) warns if a registry tool loses its sidebar owner.
- Smoke test `tests/ui/nav-registry.test.mjs` proves the generated rail markup is byte-for-byte identical to the pre-refactor markup and that no stale rail buttons remain. Run: `node --test tests/ui/nav-registry.test.mjs`.

**Deferred (scoping decision):** The sidebar Tools list is still hand-written HTML (it owns the real click handlers and carries per-item chrome — cookbook status, notif dots, Library "new" button, Memory badge). Regenerating it from the registry is a larger, higher-risk change with no browser available to verify it visually, so the registry + generated rail + drift guard deliver the "can't drift" guarantee without that risk. Full sidebar generation remains available as a follow-up.

### U2 — Chat composer simplification

The composer is the most-used surface, so calming it pays off constantly.

| Task | Notes |
|------|-------|
| Reduce the peak to **model picker · `+` · send** | Everything else folds inward |
| Move Web / Shell / RAG / Zotero into the `+` menu as toggle chips | `static/index.html` 1208–1370; reuse existing overflow menu |
| Show *active* tools as one compact summary pill on desktop too | Reuse `#tools-active-summary` (already built for mobile) |
| Resolve Agent/Chat into a **single labeled mode switch** | Pending naming decision (see Open Questions) |
| Verify auto-overflow still works | `static/app.js` ~2001–2093 |

**Deliverable:** A composer that reads as "type, pick model, send" with power tools one click away.

**Shipped (2026-07-10):**

- Web and Shell now live permanently inside the `+` tools menu (via the existing overflow-mirror mechanism), so the composer's resting peak is `model · + · send`. The underlying `#web-toggle-btn` / `#bash-toggle-btn` stay in the DOM (hidden) as the source of truth for toggle state; mirrors proxy their clicks and reflect active state. Replaced the width-measurement collapse logic in `initToolbarOverflow` (`static/app.js`) with a permanent collapse.
- The active-tools summary pill (`#tools-active-summary`, "{n} on") now appears on every viewport, not just mobile: removed the `mq.matches` gate in `initToolsActiveSummary` and moved the `.tools-collapsed` CSS rules out of the `max-width: 768px` query (`static/style.css`).
- Smoke test `tests/ui/composer.test.mjs` guards these source invariants. Run: `node --test tests/ui/composer.test.mjs`.

**Deferred:** Folding Agent/Chat into a single labeled mode switch is still an open question (naming), so the two-button `.mode-toggle` is unchanged for now — handled in U5.

**Needs your visual QA:** open the `+` menu (Web/Shell present with correct on/off dots), toggle them, and confirm the composer no longer shows Web/Shell inline; activate 4+ tools and confirm the "{n} on" pill replaces the chips on desktop.

### U3 — Document editor: one contextual toolbar

Collapse the header + markdown format rows into a single calm bar.

| Task | Notes |
|------|-------|
| Keep primary actions always visible | Save, Preview, Export |
| Move the ~20 markdown format buttons behind a **"Format" popover** | Or show them only when text is selected (contextual formatting) |
| Keep tab bar and find bar as-is functionally | Just de-densify visually |
| Extend the existing overflow pattern | `static/js/document.js` ~2512–2619 |

**Deliverable:** The writing surface stays calm; formatting is available but not always shouting.

**Shipped (2026-07-10):**

- All markdown formatting controls (bold, italic, strikethrough, Heading 1/2/3, bullet/numbered lists, inline code, code block, link, horizontal rule) are now grouped behind a single **"Format"** popover in the markdown toolbar, replacing the old row of loose buttons plus separate Heading/List/Code dropdowns.
- Reuses the existing `_showMdDropdown()` + `applyMdFormat()` machinery — added a `format` group; no new event wiring. Bold/italic/link keep their `Ctrl+B` / `Ctrl+I` / `Ctrl+K` shortcuts.
- Attach files stays inline. The now-unused `md-toolbar-email-hide` class was removed (no remaining references).
- Smoke test `tests/ui/doc-editor.test.mjs` guards the structure. Run: `node --test tests/ui/doc-editor.test.mjs`.

**Deferred:** Selection-contextual formatting (show inline controls only while text is selected) and header/status-line parity remain follow-ups; the single Format popover is the primary calm-surface win.

**Needs your visual QA:** switch a document to Markdown, open the "Format" popover, and apply each action (headings, bold/italic/strike, lists, code, link, rule); confirm `Ctrl+B/I/K` still work inline.

### U4 — Settings → Appearance: grouped, collapsible

Turn the 34-toggle wall into scannable, mostly-collapsed groups.

| Task | Notes |
|------|-------|
| Group the toggles into collapsible cards | Sidebar / Chat area / Composer (`static/index.html` 1979–2172) |
| Default the cards **collapsed** | Casual users never have to face the wall |
| Add "Reset to defaults" per group | |
| Add a **Simple / Advanced** preset | Ties to the existing `density-compact` / `density-spacious` setting |

**Deliverable:** Appearance settings feel like a short menu, not an audit.

**Shipped (2026-07-10):**

- The three Appearance groups (Sidebar / Chat Area / Chat Bar) are now collapsible headers, default **collapsed**, so the panel opens as a short scannable list instead of ~34 toggles at once. Expansion state is remembered per group (`localStorage: nobody-appearance-open-groups`).
- Implemented in `initAppearance()` (`static/js/settings.js`, new `initAppearanceCollapse()`) — no HTML restructure, so low regression risk. Headers are keyboard accessible (`role=button`, `aria-expanded`, Enter/Space). CSS in `static/style.css` hides `.vis-toggles` when a group is collapsed.
- The global **Reset All** button is unchanged.
- Smoke test `tests/ui/settings-appearance.test.mjs`. Run: `node --test tests/ui/settings-appearance.test.mjs`.

**Deferred:** Per-group reset buttons and the **Simple / Advanced** density preset — both need product definition (what "Simple" hides) and more wiring; captured as follow-ups so U4's core "toggle wall → scannable groups" win ships cleanly.

**Needs your visual QA:** open Settings → Appearance; confirm the three groups start collapsed, expand/collapse on click, and remember their state after closing/reopening Settings.

### U5 — Consistent language

Standardize names so the same concept is never called two things.

| Task | Notes |
|------|-------|
| Rename "Notes" surfaces to **Todos** | Route `/notes` stays; labels/titles/tours say "Todos" (`static/index.html` 787, 1005, 1229; `static/js/notes.js`; `slashCommands.js` tours) |
| Rename "Brain" surfaces to **Memory** | Modal title, rail `title`, sidebar, settings, slash commands (`static/index.html` 784; `static/js/memory.js`) |
| Decide + apply Agent/Chat wording | See Open Questions |
| Sweep tour + slash-command copy | `static/js/slashCommands.js` |

**Deliverable:** One name per concept across nav, tooltips, settings, and onboarding copy.

**Shipped (2026-07-10):**

- All user-facing **"Brain" → "Memory"**: sidebar tool label, Appearance toggle, modal title + `aria-label`, rail tooltip (registry), minimized-dock label (`modalManager.js`), and the tour/slash-command copy (`slashCommands.js`, `tourHints.js`). Internal identifiers (`tool-memory-btn`, `rail-memory`, `resetBrainChromeBrightness`, `openBrainConnectionsTab`) were intentionally left unchanged.
- **Notes → Todos** finished for the remaining copy: tour text and the `Could not open…` slash reply. Added `/memory`, `/todos`, `/todo` slash aliases (old `/brain`, `/notes` still work; `/notes` route unchanged).
- U1 parity snapshot updated to the new "Memory" tooltip. Smoke test `tests/ui/naming.test.mjs`. Run: `node --test tests/ui/naming.test.mjs`.

**Deferred:** Agent/Chat wording is still an open question (see Open Questions); the `.mode-toggle` labels are unchanged pending your decision.

### U6 — Shared tooltip + labeled icons

Replace bare `title=` reliance with a consistent, touch-friendly pattern.

| Task | Notes |
|------|-------|
| Build one lightweight tooltip component | New `static/js/ui/tooltip.js`; reuse across rail, toolbars, chips |
| Pair icons with text labels in primary nav | Icon-only allowed **only** in the collapsed rail |
| Ensure tooltips are reachable on touch | Long-press or first-tap reveal, not hover-only |
| Audit `aria-label` coverage | Complements `static/js/a11y.js` |

**Deliverable:** Every control says what it does — on hover, on touch, and to a screen reader.

**Shipped (2026-07-10):**

- New reusable, touch-friendly tooltip component `static/js/ui/tooltip.js` (`initTooltips(root)` / `enhanceTooltip(el)`). It consumes an element's existing `title` at runtime (removing the native `title` so it doesn't double up), reveals on hover / focus / long-press, hides on leave / blur / Escape / scroll, auto-flips right→left→below to stay on-screen, and fills a missing `aria-label` from the tooltip text for icon-only controls.
- Wired to the **icon rail** in `railProjection.js` — icon-only surface, biggest discoverability win. Rail markup keeps its `title` (so the U1 parity test is untouched); the component upgrades it at runtime.
- Styling: `.app-tooltip` in `static/style.css`.
- Smoke test `tests/ui/tooltip.test.mjs` (module loads under Node + rail integration + CSS present).

**Deferred:** Rolling the shared tooltip out to the composer toolbar and chips (those surfaces have focus/keyboard-refocus quirks that need live QA), and pairing icons with visible labels beyond the rail. Primary nav (sidebar) already shows text labels.

**Needs your visual QA:** hover/focus each icon-rail button and confirm a single styled tooltip appears (no native duplicate), stays on-screen near screen edges, and works via long-press on touch.

### U7 — Typography + chrome cleanup

Remove placeholder-ish styling from steady-state UI.

| Task | Notes |
|------|-------|
| Retire uppercase 9px micro-labels | `.tool-subgroup-label` → normal-case ~11–12px section headers (`static/style.css` ~1206–1212) |
| Reserve dashed borders for **active drag only** | Not for steady-state placeholders (`static/style.css` drag placeholder rules) |
| Normalize toolbar button sizing + spacing | Consistent hit targets across toolbars |
| Consolidate obvious inline `style="..."` into classes | Where it reduces drift; not a full rewrite |

**Deliverable:** The interface reads as finished product chrome, not a wireframe.

**Shipped (2026-07-10):**

- Retired the uppercase 9px micro-label: `.tool-subgroup-label` is now a normal-case ~11px / 600-weight section header at higher opacity (`static/style.css`), so the sidebar "Knowledge" grouping reads as finished chrome.
- Smoke test `tests/ui/typography.test.mjs`.

**Audit finding:** the dashed-border concern is already satisfied in the sidebar — every dashed style there is scoped to an *active* drag state (`.drag-over`, `.drag-placeholder`, `.unfiled-drop-zone.drag-over`), and the other dashed borders in the app are intentional affordances (drop zones, upload tiles, unbound-shortcut placeholders). No steady-state wireframe dashes to remove.

**Deferred:** Cross-toolbar button-sizing normalization and inline-`style` → class consolidation — both are broad, visually sensitive, high-churn passes that need live QA to avoid regressions; they add little without a browser to check against.

**Needs your visual QA:** confirm the sidebar "Knowledge" label reads clearly (not tiny/uppercase).

### U8 — Dead / hidden UI cleanup

Remove or finish the loose ends that add confusion.

| Task | Notes |
|------|-------|
| Remove or implement `#pinned-tools-bar` | `static/index.html` ~1226 — no populate logic found |
| Remove the inert Deep Research checkbox | `static/index.html` ~1269–1272 |
| Remove Email references from tours if Email stays stubbed | `static/js/settings.js` ~2753; `slashCommands.js` |
| Sweep for other `hidden` legacy controls | Vault, TTS overflow items (`static/index.html` ~1262–1278) |

**Deliverable:** A smaller, honest surface — nothing shown that doesn't work.

**Shipped (2026-07-10):**

- Removed the dead `#pinned-tools-bar` element (no populate logic, no CSS, no JS references anywhere).
- Smoke test `tests/ui/dead-ui.test.mjs`.

**Findings / decisions:**

- The inert **Deep Research menu entry** was already removed in an earlier pass (see the comment in `static/index.html`). The remaining `#research-toggle` is *not* dead — it's the hidden state checkbox read/written by ~10 modules (`app.js`, `chat.js`, `compare/*`, `sessions.js`, `slashCommands.js`, …), so it must stay. Kept.
- **Hidden Vault / TTS overflow items** are already `display:none` and are still referenced (with null-guards) by several modules; removing them is low-benefit, non-trivial-risk churn. Left in place.
- **Email tour references:** left as-is — there was no clear signal Email is fully stubbed, and its slash command / settings still exist. Removing onboarding copy blindly could misrepresent a working feature. Revisit once Email's status is confirmed.

---

## Cross-cutting principles (apply in every phase)

- **One job per surface** — lead with the single most likely action.
- **Consistency over cleverness** — same overflow, same tab host, same tooltip everywhere.
- **Reuse, don't fork** — `tabHost`, `modalManager`, overflow menus, tokens already exist.
- **Test on mobile first for density** — the small screen tells the truth about clutter.

---

## File map

| Area | Primary files |
|------|---------------|
| App shell / nav | `static/index.html` (sidebar 795+, icon rail 765–793), new `static/js/nav/toolRegistry.js` |
| Sidebar behavior | `static/js/sidebar-layout.js` |
| Chat composer | `static/index.html` 1208–1370, `static/app.js` ~2001–2093 |
| Document editor | `static/js/document.js` (~2512–2619) |
| Settings appearance | `static/index.html` 1979–2172, `static/js/settings.js` |
| Todos (was Notes) | `static/js/notes.js` |
| Memory (was Brain) | `static/js/memory.js` |
| Tooltip / a11y | new `static/js/ui/tooltip.js`, `static/js/a11y.js`, `static/js/ui/ui.js` |
| Onboarding copy | `static/js/slashCommands.js`, `static/js/tourHints.js` |
| Styles / tokens | `static/style.css` (tokens ~6–74, density ~159–166, micro-labels ~1206) |
| Modals / overflow primitives | `static/js/modalManager.js` |

---

## Behavior preserved (must not regress)

- All existing tools remain reachable (nav is reorganized, not removed).
- Existing URL routes (`/notes`, `/calendar`, `/cookbook`, `/memory`, `/links`, `/gallery`, `/tasks`, `/library`) keep working.
- Keyboard shortcuts (Ctrl+K search, Ctrl+B sidebar, etc.) unchanged unless explicitly noted.
- Theme tokens, density setting, and light/dark modes keep working.
- Chat send, model picker, agent tool toggles keep working.

---

## Open questions

| # | Question | Default lean |
|---|----------|--------------|
| 1 | Agent vs Chat wording — one labeled mode switch, or keep two buttons? | **One labeled mode switch** (single control, clear current mode) |
| 2 | Tool grouping buckets — are the 4 groups (Knowledge / Create / Explore / Life) the right split? | Start with 4; adjust after U1 dogfood |
| 3 | Should the icon rail survive at all, or fully defer to the sidebar on desktop? | **Keep rail** as a projection (collapsed nav is useful especially for mobile) |
| 4 | Is Email being finished or fully removed? Affects U8 cleanup. | **Remove references** Email is not longer shipping |
| 5 | Markdown formatting — popover vs selection-contextual toolbar? | **Selection-contextual**, popover as fallback |
| 6 | Simple/Advanced preset — one global switch or per-area? | **One global** Simple/Advanced, tied to density |

---

## Testing checklist

| Check | Phase |
|-------|-------|
| Add a tool to the registry → appears in both sidebar and rail | U1 |
| Remove a tool from the registry → disappears from both | U1 |
| Composer at rest shows only model · `+` · send | U2 |
| Active tools collapse into one summary pill (desktop + mobile) | U2 |
| Document editor shows one primary toolbar; formatting in popover | U3 |
| Appearance opens with collapsed groups; reset works | U4 |
| No "Notes" or "Brain" labels remain in UI or tours | U5 |
| Every rail/toolbar icon has a tooltip reachable on touch | U6 |
| No uppercase 9px labels or steady-state dashed borders remain | U7 |
| No visible control does nothing when clicked | U8 |
| Full pass on a narrow (<768px) viewport per phase | all |

---

## Related docs

| Doc | Relationship |
|-----|--------------|
| `docs/projects-ui-roadmap.md` | Tabbed project workspace layout (G1–G8); historical — direction moved to context layer |
| `docs/projects-suite-roadmap.md` | Projects suite cohesion (P1–P9); **paused** |
| `docs/projects-context-layer-roadmap.md` | **Current:** Projects as harness context layer + promote cwd → Library |
| `README.md` | Feature overview and architecture (`static/` front-end map) |

---

## Changelog

| Date | Change |
|------|--------|
| 2026-07-10 | Initial draft: phases U1–U8 (nav source, composer, doc editor, settings, naming, tooltips, typography, dead-UI cleanup) |
| 2026-07-10 | U1 shipped: tool registry (`static/js/nav/toolRegistry.js`), icon rail generated as a projection, registry-derived rail delegation, drift guard, and parity smoke test. Sidebar generation deferred. |
| 2026-07-10 | U2 shipped: Web + Shell moved permanently into the `+` menu; active-tools summary pill enabled on desktop. Agent/Chat toggle deferred to U5. |
| 2026-07-10 | U3 shipped: markdown formatting consolidated into a single "Format" popover (reuses `_showMdDropdown`); keyboard shortcuts preserved. |
| 2026-07-10 | U4 shipped: Appearance groups are collapsible (default collapsed, state remembered). Per-group reset + Simple/Advanced preset deferred. |
| 2026-07-10 | U5 shipped: user-facing Brain→Memory everywhere; Notes→Todos copy finished; `/memory` `/todos` aliases added. Agent/Chat wording still open. |
| 2026-07-10 | U6 shipped: reusable tooltip component (`static/js/ui/tooltip.js`) wired to the icon rail; aria-label backfill. Broader rollout deferred. |
| 2026-07-10 | U7 shipped: retired the 9px uppercase `.tool-subgroup-label` micro-label. Dashed-border audit found sidebar already correct. Button-sizing/inline-style sweeps deferred. |
| 2026-07-10 | U8 shipped: removed dead `#pinned-tools-bar`. `#research-toggle` kept (live state). Vault/TTS + Email tour cleanup left with rationale. |
| 2026-07-10 | U9 follow-up: Agent/Chat toggle kept as-is (confirmed it's a real execution-mode switch — agentic loop vs single reply — not redundant with the Web/Shell toggles). Tool categories extended from Knowledge-only to labeled groups in both sidebar and rail. Grouping driven by `toolRegistry.js`; sidebar bracket CSS generalized (`.tool-group-item-first`). Snapshot test updated. |
| 2026-07-10 | U9 revision: re-bucketed into four groups per request — **Knowledge** (Memory, Links) · **Explore** (Research, Compare, Gallery, Library) · **Plan** (Calendar, Todos, Tasks) · **Customize** (Cookbook, Theme). Cookbook + Theme now their own category; Gallery + Library grouped with Research + Compare (not exclusive). |
