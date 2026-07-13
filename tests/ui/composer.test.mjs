// Structural smoke test for U2 (chat composer simplification).
//
// Run with:  node --test tests/ui/composer.test.mjs
//
// No browser is available, so these assertions guard the *structure* of the
// change (source invariants) rather than rendered layout. Visual behaviour is
// verified manually in the browser.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

const appJs = read('static/app.js');
const indexHtml = read('static/index.html');
const styleCss = read('static/style.css');

test('Web + Shell are permanently collapsed into the + menu (no width measurement)', () => {
  // The always-collapse branch is present.
  assert.match(
    appJs,
    /collapsibleBtns\.forEach\(btn => btn\.classList\.add\('toolbar-collapsed'\)\)/,
  );
  // The old width-based measurement is gone from the overflow checker.
  assert.ok(
    !appJs.includes('const available = inputBottom.clientWidth'),
    'legacy width measurement should be removed',
  );
});

test('Web + Shell underlying toggle buttons remain in the DOM as source of truth', () => {
  assert.ok(indexHtml.includes('id="web-toggle-btn"'));
  assert.ok(indexHtml.includes('id="bash-toggle-btn"'));
  // The collapsible set is still exactly those two.
  assert.match(appJs, /collapsibleIds = \['bash-toggle-btn', 'web-toggle-btn'\]/);
});

test('active-tools summary pill is no longer gated to mobile only', () => {
  assert.ok(
    !appJs.includes('const collapse = mq.matches && n > COLLAPSE_AT'),
    'mobile-only gate should be removed',
  );
  assert.match(appJs, /const collapse = n > COLLAPSE_AT;/);
});

test('summary-pill CSS applies at every viewport (rules moved out of the mobile query)', () => {
  // Both collapse rules exist.
  assert.match(
    styleCss,
    /\.chat-input-left\.tools-collapsed > \.tool-indicator \{ display: none !important; \}/,
  );
  assert.match(
    styleCss,
    /\.chat-input-left\.tools-collapsed \.tools-active-summary \{ display: inline-flex !important; \}/,
  );
  // The rules must not be the mobile-only variant anymore: the comment records
  // the every-viewport intent.
  assert.match(styleCss, /As of U2 this applies on every viewport/);
});
