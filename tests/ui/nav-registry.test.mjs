// Smoke test for the U1 tool-navigation registry.
//
// Run with:  node --test tests/ui/nav-registry.test.mjs
//
// Proves that generating the icon-rail from the single-source-of-truth registry
// reproduces the exact markup that used to live in index.html (so the refactor
// is behaviour-preserving), and that the sidebar owners it delegates to still
// exist in index.html (drift guard).

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import {
  TOOLS,
  buildRailToolsMarkup,
  railToSidebarMap,
} from '../../static/js/nav/toolRegistry.js';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const indexHtml = readFileSync(join(repoRoot, 'static', 'index.html'), 'utf8');

// Collapse insignificant whitespace so formatting differences don't matter —
// only structure and attributes are compared.
const norm = (s) => s.replace(/>\s+</g, '><').replace(/\s+/g, ' ').trim();

// Snapshot of the icon-rail tool launchers for the category layout: four
// labeled clusters (Knowledge / Explore / Plan / Customize). Guards the
// generated markup against accidental drift.
const EXPECTED_RAIL_MARKUP = `
<div class="rail-group" role="group" aria-label="Knowledge — Memory and Links">
  <button class="icon-rail-btn rail-group-btn" id="rail-memory" title="Memory — memories, skills, and connection review"><span class="brain-connections-badge" hidden aria-hidden="true"></span><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5a3 3 0 1 0-5.997.125 4 4 0 0 0-2.526 5.77 4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z"/><path d="M12 5a3 3 0 1 1 5.997.125 4 4 0 0 1 2.526 5.77 4 4 0 0 1-.556 6.588A4 4 0 1 1 12 18Z"/><path d="M15 13a4.5 4.5 0 0 1-3-4 4.5 4.5 0 0 1-3 4"/></svg></button>
  <button class="icon-rail-btn rail-group-btn" id="rail-knowledge" title="Links — browse confirmed links"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="5" cy="12" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="19" cy="18" r="2"/><line x1="7" y1="12" x2="17" y2="7"/><line x1="7" y1="12" x2="17" y2="17"/></svg></button>
</div>
<div class="rail-group" role="group" aria-label="Explore — Research, Compare, Gallery, Library, and Project files">
  <button class="icon-rail-btn rail-group-btn" id="rail-research" title="Research — run deep research"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg></button>
  <button class="icon-rail-btn rail-group-btn" id="rail-compare" title="Compare"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/></svg></button>
  <button class="icon-rail-btn rail-group-btn" id="rail-gallery" title="Gallery"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg></button>
  <button class="icon-rail-btn rail-group-btn" id="rail-archive" title="Library — saved chats, files, and reports"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M9 7h6M9 11h4"/></svg></button>
  <button class="icon-rail-btn rail-group-btn" id="rail-project-files" title="Project files — browse the active project folder" hidden style="display:none"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg></button>
</div>
<div class="rail-group" role="group" aria-label="Plan — Calendar, Todos, and Tasks">
  <button class="icon-rail-btn rail-group-btn" id="rail-calendar" title="Calendar"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg></button>
  <button class="icon-rail-btn rail-group-btn" id="rail-notes" title="Todos"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 3h10l4 4v14H5z"/><path d="M15 3v5h5"/><path d="M8 17.5 15.5 10l2.5 2.5L10.5 20H8z"/></svg></button>
  <button class="icon-rail-btn rail-group-btn" id="rail-tasks" title="Tasks"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/><path d="M9 16l2 2 4-4"/></svg></button>
</div>
<div class="rail-group" role="group" aria-label="Customize — Cookbook and Theme">
  <button class="icon-rail-btn rail-group-btn" id="rail-cookbook" title="Cookbook"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.7"><path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3 3 0 0 0-3 3 3 3 0 0 0-3-3z"/></svg></button>
  <button class="icon-rail-btn rail-group-btn" id="rail-theme" title="Theme"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a10 10 0 0 0 0 20 5 5 0 0 0 5-5 3 3 0 0 0-3-3h-2a3 3 0 0 1-3-3 5 5 0 0 1 5-5"/></svg></button>
</div>
`;

test('generated rail markup matches the expected category layout (normalized)', () => {
  assert.equal(norm(buildRailToolsMarkup()), norm(EXPECTED_RAIL_MARKUP));
});

test('every tool renders inside one of the four labeled clusters', () => {
  const markup = buildRailToolsMarkup();
  const groups = markup.match(/class="rail-group"/g) || [];
  assert.equal(groups.length, 4, 'expected exactly four rail-group clusters');
  for (const label of ['Knowledge', 'Explore', 'Plan', 'Customize']) {
    assert.ok(markup.includes(`aria-label="${label} —`), `missing ${label} group`);
  }
});

test('every tool has a unique rail id and sidebar id', () => {
  const railIds = TOOLS.map((t) => t.railId);
  const sidebarIds = TOOLS.map((t) => t.sidebarId);
  assert.equal(new Set(railIds).size, railIds.length, 'duplicate railId');
  assert.equal(new Set(sidebarIds).size, sidebarIds.length, 'duplicate sidebarId');
});

test('every tool has an icon and a title', () => {
  for (const t of TOOLS) {
    assert.ok(t.icon && t.icon.includes('<svg'), `missing icon for ${t.key}`);
    assert.ok(t.title && t.title.length > 0, `missing title for ${t.key}`);
  }
});

test('rail->sidebar delegation map covers every tool', () => {
  const map = railToSidebarMap();
  assert.equal(Object.keys(map).length, TOOLS.length);
  for (const t of TOOLS) assert.equal(map[t.railId], t.sidebarId);
});

test('index.html no longer hard-codes the generated rail buttons', () => {
  assert.ok(indexHtml.includes('id="rail-tools-mount"'), 'rail mount point missing');
  for (const t of TOOLS) {
    assert.ok(
      !indexHtml.includes(`id="${t.railId}"`),
      `stale static rail button ${t.railId} still present in index.html`,
    );
  }
});

test('sidebar still owns a handler element for every tool (drift guard)', () => {
  for (const t of TOOLS) {
    assert.ok(
      indexHtml.includes(`id="${t.sidebarId}"`),
      `sidebar owner ${t.sidebarId} missing from index.html`,
    );
  }
});
