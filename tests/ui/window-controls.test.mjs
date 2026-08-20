// Structural smoke test for tool-window minimize/close chrome.
//
// Run with:  node --test tests/ui/window-controls.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const css = readFileSync(join(repoRoot, 'static', 'style.css'), 'utf8');
const notesJs = readFileSync(join(repoRoot, 'static', 'js', 'notes.js'), 'utf8');

test('window top controls share a locked 24×24 square rule', () => {
  const idx = css.indexOf('/* Window top controls — perfect 24×24 squares');
  assert.ok(idx >= 0, 'shared window-control square block exists');
  const body = css.slice(idx, idx + 900);
  assert.match(body, /\.close-btn,/);
  assert.match(body, /\.modal-close,/);
  assert.match(body, /\.modal-minimize-btn,/);
  assert.match(body, /\.minimize-btn \{/);
  assert.match(body, /aspect-ratio:\s*1/);
  assert.match(body, /padding:\s*0/);
  assert.match(body, /flex:\s*0 0 24px/);
  assert.match(body, /width:\s*24px/);
  assert.match(body, /height:\s*24px/);
});

test('legacy minimize underscore nudge padding is gone', () => {
  assert.doesNotMatch(
    css,
    /\.minimize-btn \{[\s\S]*?padding:\s*0 0 6px 0/,
  );
});

test('GE popup glyph nudge does not hit global modal close buttons', () => {
  const idx = css.indexOf('/* GE popup head glyphs sit visually low');
  assert.ok(idx >= 0, 'scoped GE glyph nudge exists');
  const body = css.slice(idx, idx + 500);
  assert.match(body, /\.ge-adj-close,/);
  assert.match(body, /\.ge-adj-min \{/);
  assert.doesNotMatch(body, /\.modal-close,/);
  assert.doesNotMatch(body, /\.close-btn,/);
  assert.doesNotMatch(body, /padding-bottom:\s*8px/);
});

test('title icon gap and min↔close gap are tightened', () => {
  assert.match(
    css,
    /\.modal-header h4 svg,[\s\S]*?margin-right:\s*4px !important/,
  );
  assert.match(css, /\.modal-minimize-btn \{[\s\S]*?margin-right:\s*2px/);
  assert.match(css, /\.minimize-btn \{[\s\S]*?margin-right:\s*2px/);
  assert.doesNotMatch(
    css,
    /#email-lib-modal \.email-lib-header-actions \.minimize-btn \{[\s\S]*?left:\s*6px/,
  );
});

test('notes minimize button has no inline left nudge', () => {
  assert.match(notesJs, /id="notes-minimize-btn"/);
  assert.doesNotMatch(notesJs, /id="notes-minimize-btn"[^>]*left:\s*2px/);
});
