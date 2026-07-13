// Structural smoke test for U6 (shared tooltip component).
//
// Run with:  node --test tests/ui/tooltip.test.mjs
//
// Interactive behaviour (hover/focus/long-press reveal, positioning) is
// verified manually in the browser. Here we confirm the module loads cleanly
// under Node and is wired into the rail projection.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { initTooltips, enhanceTooltip } from '../../static/js/ui/tooltip.js';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

test('tooltip module exports a reusable API and loads under Node', () => {
  assert.equal(typeof initTooltips, 'function');
  assert.equal(typeof enhanceTooltip, 'function');
});

test('the icon rail opts into the shared tooltip', () => {
  const rail = read('static/js/nav/railProjection.js');
  assert.match(rail, /import \{ initTooltips \} from '\.\.\/ui\/tooltip\.js'/);
  assert.match(rail, /initTooltips\(rail\)/);
});

test('tooltip CSS is present', () => {
  const css = read('static/style.css');
  assert.match(css, /\.app-tooltip \{/);
  assert.match(css, /\.app-tooltip\.visible \{/);
});
