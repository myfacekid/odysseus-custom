// ============================================
// Nobody UI — Tool Navigation Registry (U1)
// ============================================
// Single source of truth for the app's tool launchers.
//
// Before U1 the same tools were declared three times: the sidebar Tools list
// (which owns the real click handlers), the icon-rail buttons, and the
// `_railToolMap` delegation table in app.js. Those lists could silently drift.
//
// Now the sidebar list stays the owner of behavior, and the icon rail is a
// *projection* generated from this registry. The rail->sidebar delegation and
// the dev-time drift check are also derived from here, so adding or removing a
// tool means editing this one list (plus its sidebar handler).
//
// This module is intentionally free of top-level DOM access and side effects so
// it can be imported and unit-tested in plain Node.

/**
 * @typedef {Object} ToolEntry
 * @property {string} key        Stable identifier for the tool.
 * @property {string} railId     Element id of the generated icon-rail button.
 * @property {string} sidebarId  Element id of the sidebar list item that owns the click handler.
 * @property {string} title      Tooltip / accessible label for the rail button.
 * @property {string} icon       Inline SVG markup for the rail button.
 * @property {string} [railClass] Extra class(es) appended to the rail button.
 * @property {string} [badge]    Class name for an optional status badge span rendered before the icon.
 * @property {string} [group]    Visual group key; adjacent tools sharing a group render inside one wrapper.
 * @property {string} [route]    URL route that opens this tool (documentation / routing reference).
 */

// Declaration order is the render order for both the icon rail and the sidebar
// list. Tools are grouped into four labeled categories (Knowledge / Explore /
// Plan / Customize); adjacent tools sharing a `group` render as one cluster in
// the rail and under one label in the sidebar.
/** @type {ToolEntry[]} */
export const TOOLS = [
  // ── Knowledge: reference and memory ──
  {
    key: 'memory',
    railId: 'rail-memory',
    sidebarId: 'tool-memory-btn',
    title: 'Memory — memories, skills, and connection review',
    route: '/memory',
    group: 'knowledge',
    railClass: 'rail-group-btn',
    badge: 'brain-connections-badge',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/></svg>',
  },
  {
    key: 'knowledge',
    railId: 'rail-knowledge',
    sidebarId: 'tool-knowledge-btn',
    title: 'Links — browse confirmed links',
    route: '/links',
    group: 'knowledge',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="19" cy="18" r="2"/><line x1="7" y1="12" x2="17" y2="7"/><line x1="7" y1="12" x2="17" y2="17"/></svg>',
  },
  // ── Explore: research, analysis, generation, and saved output ──
  {
    key: 'research',
    railId: 'rail-research',
    sidebarId: 'tool-research-btn',
    title: 'Research — run deep research',
    group: 'explore',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>',
  },
  {
    key: 'compare',
    railId: 'rail-compare',
    sidebarId: 'tool-compare-btn',
    title: 'Compare',
    group: 'explore',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/></svg>',
  },
  {
    key: 'gallery',
    railId: 'rail-gallery',
    sidebarId: 'tool-gallery-btn',
    title: 'Gallery',
    route: '/gallery',
    group: 'explore',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>',
  },
  {
    key: 'library',
    railId: 'rail-archive',
    sidebarId: 'tool-library-btn',
    title: 'Library — saved chats, files, and reports',
    route: '/library',
    group: 'explore',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M9 7h6M9 11h4"/></svg>',
  },
  {
    key: 'project-files',
    railId: 'rail-project-files',
    sidebarId: 'tool-project-files-btn',
    title: 'Project files — browse the active project folder',
    group: 'explore',
    railClass: 'rail-group-btn',
    // Sidebar + rail are shown only while a project is active (app.js sync).
    requiresActiveProject: true,
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg>',
  },
  // ── Plan: time and task management ──
  {
    key: 'calendar',
    railId: 'rail-calendar',
    sidebarId: 'tool-calendar-btn',
    title: 'Calendar',
    route: '/calendar',
    group: 'plan',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>',
  },
  {
    key: 'notes',
    railId: 'rail-notes',
    sidebarId: 'tool-notes-btn',
    title: 'Todos',
    route: '/notes',
    group: 'plan',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3h10l4 4v14H5z"/><path d="M15 3v5h5"/><path d="M8 17.5 15.5 10l2.5 2.5L10.5 20H8z"/></svg>',
  },
  {
    key: 'tasks',
    railId: 'rail-tasks',
    sidebarId: 'tool-tasks-btn',
    title: 'Tasks',
    route: '/tasks',
    group: 'plan',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><path d="M9 16l2 2 4-4"/></svg>',
  },
  // ── Customize: prompt recipes and appearance ──
  {
    key: 'cookbook',
    railId: 'rail-cookbook',
    sidebarId: 'tool-cookbook-btn',
    title: 'Cookbook',
    route: '/cookbook',
    group: 'customize',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.7"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg>',
  },
  {
    key: 'theme',
    railId: 'rail-theme',
    sidebarId: 'tool-theme-btn',
    title: 'Theme',
    group: 'customize',
    railClass: 'rail-group-btn',
    icon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 0 0 20 5 5 0 0 0 5-5 3 3 0 0 0-3-3h-2a3 3 0 0 1-3-3 5 5 0 0 1 5-5"/></svg>',
  },
];

/** Group wrappers matched to the `group` key on adjacent tools. */
const GROUP_WRAPPERS = {
  knowledge: { className: 'rail-group', role: 'group', ariaLabel: 'Knowledge — Memory and Links' },
  explore: { className: 'rail-group', role: 'group', ariaLabel: 'Explore — Research, Compare, Gallery, Library, and Project files' },
  plan: { className: 'rail-group', role: 'group', ariaLabel: 'Plan — Calendar, Todos, and Tasks' },
  customize: { className: 'rail-group', role: 'group', ariaLabel: 'Customize — Cookbook and Theme' },
};

/** HTML for a single rail button (icon + optional badge). */
function railButtonHTML(tool) {
  const cls = 'icon-rail-btn' + (tool.railClass ? ' ' + tool.railClass : '');
  const badge = tool.badge
    ? `<span class="${tool.badge}" hidden aria-hidden="true"></span>`
    : '';
  // Project-scoped tools stay hidden until app.js syncs against active project.
  const hiddenAttr = tool.requiresActiveProject ? ' hidden' : '';
  const styleAttr = tool.requiresActiveProject ? ' style="display:none"' : '';
  return `<button class="${cls}" id="${tool.railId}" title="${tool.title}"${hiddenAttr}${styleAttr}>${badge}${tool.icon}</button>`;
}

/**
 * Build the icon-rail tool-launcher markup from the registry, wrapping adjacent
 * tools that share a `group` inside the matching group container.
 * @returns {string}
 */
export function buildRailToolsMarkup() {
  let html = '';
  let i = 0;
  while (i < TOOLS.length) {
    const tool = TOOLS[i];
    const group = tool.group && GROUP_WRAPPERS[tool.group] ? tool.group : null;
    if (group) {
      const buttons = [];
      while (i < TOOLS.length && TOOLS[i].group === group) {
        buttons.push(railButtonHTML(TOOLS[i]));
        i += 1;
      }
      const w = GROUP_WRAPPERS[group];
      html += `<div class="${w.className}" role="${w.role}" aria-label="${w.ariaLabel}">${buttons.join('')}</div>`;
    } else {
      html += railButtonHTML(tool);
      i += 1;
    }
  }
  return html;
}

/**
 * Delegation table mapping each generated rail button id to the sidebar list
 * item id that owns its click handler. Replaces the old hand-maintained
 * `_railToolMap` in app.js.
 * @returns {Record<string, string>}
 */
export function railToSidebarMap() {
  const map = {};
  for (const tool of TOOLS) map[tool.railId] = tool.sidebarId;
  return map;
}

/**
 * Render the rail projection into the icon rail. Idempotent: safe to call more
 * than once. Looks for the `#rail-tools-mount` placeholder inside `#icon-rail`.
 * @param {Document} [doc]
 */
export function mountRailTools(doc = (typeof document !== 'undefined' ? document : null)) {
  if (!doc) return;
  const mount = doc.getElementById('rail-tools-mount');
  if (!mount) return;
  mount.innerHTML = buildRailToolsMarkup();
}

/**
 * Dev-time drift guard: warns (once) if any registry tool is missing its
 * sidebar owner in the DOM, which would break rail delegation.
 * @param {Document} [doc]
 */
export function checkNavParity(doc = (typeof document !== 'undefined' ? document : null)) {
  if (!doc) return;
  const missing = TOOLS.filter((t) => !doc.getElementById(t.sidebarId)).map((t) => t.sidebarId);
  if (missing.length) {
    console.warn('[nav] tool registry references sidebar items missing from the DOM:', missing);
  }
}
