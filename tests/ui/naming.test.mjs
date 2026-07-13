// Structural smoke test for U5 (consistent language: Brain -> Memory, Notes -> Todos).
//
// Run with:  node --test tests/ui/naming.test.mjs
//
// Checks user-facing labels only; internal identifiers (memory ids,
// resetBrainChromeBrightness, openBrainConnectionsTab, /notes route) are
// intentionally left unchanged.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

const indexHtml = read('static/index.html');
const registry = read('static/js/nav/toolRegistry.js');
const modalManager = read('static/js/modalManager.js');

test('sidebar + appearance labels say Memory, not Brain', () => {
  assert.ok(indexHtml.includes('<span class="grow">Memory</span>'));
  assert.ok(indexHtml.includes('<span class="vis-label">Memory</span>'));
  assert.ok(!indexHtml.includes('<span class="grow">Brain</span>'));
  assert.ok(!indexHtml.includes('<span class="vis-label">Brain</span>'));
});

test('memory modal title + aria-label say Memory', () => {
  assert.ok(indexHtml.includes('aria-label="Memory"'));
  assert.ok(!indexHtml.includes('aria-label="Brain"'));
  assert.ok(/svg>Memory<\/h4>/.test(indexHtml));
});

test('rail registry + dock label say Memory', () => {
  assert.match(registry, /title: 'Memory — memories, skills, and connection review'/);
  assert.match(registry, /Knowledge — Memory and Links/);
  assert.match(modalManager, /'memory-modal':\s*\{ label: 'Memory'/);
});

test('the Todos label is used (Notes route preserved internally)', () => {
  assert.ok(indexHtml.includes('<span class="grow">Todos</span>'));
  // The tool still routes through the notes handler / id.
  assert.ok(indexHtml.includes('id="tool-notes-btn"'));
});
