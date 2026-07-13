// Structural smoke tests for Projects suite integration (P1–P3, P5, P7).
//
// Run with:  node --test tests/ui/projects-suite.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

const indexHtml = read('static/index.html');
const indexJs = read('static/js/projects/index.js');
const sidebarJs = read('static/js/projects/sidebar.js');
const styleCss = read('static/style.css');
const activityJs = read('static/js/activityStrip.js');

test('P1: projects section has sort overflow and bulk bar', () => {
  assert.ok(indexHtml.includes('id="project-sort-btn"'));
  assert.ok(indexHtml.includes('id="project-sort-dropdown"'));
  assert.ok(indexHtml.includes('id="project-bulk-bar"'));
  assert.ok(indexHtml.includes('id="project-select-from-dropdown"'));
});

test('P1: sidebar module renders list and supports meta cache', () => {
  assert.ok(sidebarJs.includes('renderProjectList'));
  assert.ok(sidebarJs.includes('recordProjectLinkCount'));
  assert.ok(sidebarJs.includes('scheduleMetaHydration'));
  assert.ok(sidebarJs.includes('mountEmptyState'));
});

test('P3: unified top bar uses project overflow instead of chat export', () => {
  assert.ok(indexHtml.includes('id="project-overflow-wrap"'));
  assert.ok(indexHtml.includes('id="project-overflow-rename"'));
  assert.ok(indexHtml.includes('id="project-overflow-archive"'));
  assert.ok(indexJs.includes('_initProjectOverflowMenu'));
  assert.ok(indexJs.includes('currentMetaEl.textContent = project.title'));
  assert.ok(styleCss.includes('.chat-container.project-active #project-overflow-wrap'));
});

test('P3: duplicate workspace title is hidden', () => {
  assert.ok(styleCss.includes('#project-workspace-title'));
  assert.match(styleCss, /#project-workspace-title\s*\{[^}]*display:\s*none/);
});

test('P5: activity strip accepts project runs', () => {
  assert.ok(activityJs.includes('setProjectRunActivity'));
  assert.ok(activityJs.includes("tool: 'project'"));
  assert.ok(indexJs.includes('setProjectRunActivity'));
});

test('P7: workspace enter/exit motion keyframes exist', () => {
  assert.ok(styleCss.includes('@keyframes project-workspace-enter'));
  assert.ok(styleCss.includes('@keyframes project-workspace-exit'));
  assert.ok(styleCss.includes('prefers-reduced-motion'));
  assert.ok(indexJs.includes('project-workspace-entering'));
  assert.ok(indexJs.includes('project-workspace-exiting'));
});

test('P2: workspace header tooltips wired', () => {
  assert.ok(indexJs.includes('initTooltips'));
  assert.ok(indexJs.includes('_initProjectHeaderTooltips'));
});

test('P2: links and file tree use shared loading feedback', () => {
  assert.ok(indexJs.includes('showLoadingRow'));
  const fileTree = read('static/js/projects/fileTree.js');
  assert.ok(fileTree.includes('showLoadingRow'));
});

test('P4: shared mdFormat and editor Format button', () => {
  assert.ok(read('static/js/ui/mdFormat.js').includes('applyMdFormat'));
  assert.ok(read('static/js/ui/editorChrome.js').includes('formatButtonHtml'));
  const editor = read('static/js/projects/editor.js');
  assert.ok(editor.includes('editorChrome'));
  assert.ok(editor.includes('project-editor-format-wrap'));
});

test('P6/P8: layout presets and mobile drawers', () => {
  assert.ok(read('static/js/projects/workspaceLayout.js').includes('LAYOUT_PRESETS'));
  assert.ok(indexHtml.includes('id="project-left-collapse-btn"'));
  assert.ok(indexHtml.includes('id="project-mobile-footer-grabber"'));
  assert.ok(indexHtml.includes('data-layout-preset="focus"'));
  assert.ok(styleCss.includes('project-mobile-left-open'));
});

test('P7: center tab crossfade and empty domino', () => {
  assert.ok(indexJs.includes('project-center-well--switching'));
  assert.ok(styleCss.includes('project-pane-crossfade'));
  assert.ok(styleCss.includes('project-empty-in'));
});

test('P9: Chat/Run companion is a right column', () => {
  assert.ok(indexHtml.includes('project-workspace-companion'));
  assert.ok(indexHtml.includes('project-companion-body'));
  // Composer lives inside the companion, not below the grid.
  const companionIdx = indexHtml.indexOf('project-workspace-companion');
  const composerIdx = indexHtml.indexOf('id="project-workspace-composer"');
  assert.ok(companionIdx > 0 && composerIdx > companionIdx);
  assert.ok(styleCss.includes('grid-template-areas: "left center companion"')
    || styleCss.includes('grid-template-areas: \"left center companion\"')
    || styleCss.includes('grid-area: companion'));
  const resize = read('static/js/projects/workspaceResize.js');
  assert.ok(resize.includes('RIGHT_DEFAULT') || resize.includes('_rightPx'));
  assert.ok(resize.includes('minmax(0, 1fr)'));
});

test('P9: projects use opaque harness chrome (no forced glass)', () => {
  assert.ok(!styleCss.includes('backdrop-filter: var(--project-glass-blur) !important'));
  assert.ok(styleCss.includes('.project-left-tab--links.active'));
  assert.match(styleCss, /\.project-workspace-left\s*\{[^}]*background:\s*var\(--panel/);
});
