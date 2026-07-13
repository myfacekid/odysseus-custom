// Structural smoke test for U4 (collapsible Appearance groups).
//
// Run with:  node --test tests/ui/settings-appearance.test.mjs
//
// Visual behaviour (click a group header to expand/collapse, state persists)
// is verified manually in the browser.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

const settingsJs = read('static/js/settings.js');
const styleCss = read('static/style.css');
const indexHtml = read('static/index.html');

test('initAppearance wires up the collapse behaviour', () => {
  assert.match(settingsJs, /function initAppearanceCollapse\(\)/);
  assert.match(settingsJs, /initAppearanceCollapse\(\);/);
  assert.match(settingsJs, /settings-collapsed/);
  assert.match(settingsJs, /nobody-appearance-open-groups/);
});

test('collapse state is keyboard accessible', () => {
  assert.match(settingsJs, /h2\.setAttribute\('role', 'button'\)/);
  assert.match(settingsJs, /aria-expanded/);
});

test('CSS hides the toggle body when a group is collapsed', () => {
  assert.match(
    styleCss,
    /\.settings-appearance-panel \.admin-card\.settings-collapsed \.vis-toggles \{\s*display: none;\s*\}/,
  );
  assert.match(styleCss, /\.settings-collapse-chevron/);
});

test('the three Appearance groups are still present in the panel', () => {
  const panelStart = indexHtml.indexOf('data-settings-panel="appearance"');
  assert.ok(panelStart > 0, 'appearance panel exists');
  const panel = indexHtml.slice(panelStart, panelStart + 30000);
  assert.ok(panel.includes('>Sidebar</h2>') || /Sidebar<\/h2>/.test(panel), 'Sidebar group');
  assert.ok(/Chat Area<\/h2>/.test(panel), 'Chat Area group');
  assert.ok(/Chat Bar<\/h2>/.test(panel), 'Chat Bar group');
});
