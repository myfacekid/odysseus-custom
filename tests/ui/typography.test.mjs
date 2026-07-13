// Structural smoke test for U7 (typography + chrome cleanup).
//
// Run with:  node --test tests/ui/typography.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const css = readFileSync(join(repoRoot, 'static', 'style.css'), 'utf8');

test('tool-subgroup-label is a readable section header, not a 9px uppercase micro-label', () => {
  const m = css.match(/\.tool-subgroup-label \{([\s\S]*?)\}/);
  assert.ok(m, 'rule exists');
  const body = m[1];
  assert.ok(!/text-transform:\s*uppercase/.test(body), 'no longer uppercase');
  assert.ok(!/font-size:\s*9px/.test(body), 'no longer 9px');
  assert.match(body, /font-size:\s*11px/);
});
