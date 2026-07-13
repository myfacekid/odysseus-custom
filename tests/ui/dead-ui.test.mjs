// Structural smoke test for U8 (dead / hidden UI cleanup).
//
// Run with:  node --test tests/ui/dead-ui.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

const indexHtml = read('static/index.html');

test('the dead #pinned-tools-bar element was removed', () => {
  assert.ok(!indexHtml.includes('id="pinned-tools-bar"'));
});

test('the #research-toggle state checkbox is preserved (referenced across modules)', () => {
  // Removing it would break research state everywhere — it must stay.
  assert.ok(indexHtml.includes('id="research-toggle"'));
});
