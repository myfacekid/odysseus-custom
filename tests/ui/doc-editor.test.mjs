// Structural smoke test for U3 (document editor single Format popover).
//
// Run with:  node --test tests/ui/doc-editor.test.mjs
//
// document.js is ~8k lines and heavily browser-coupled, so these assertions
// guard the source-level structure of the change. Visual behaviour (opening the
// Format popover, applying each action) is verified manually in the browser.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const docJs = readFileSync(join(repoRoot, 'static', 'js', 'document.js'), 'utf8');

test('markdown toolbar exposes a single Format popover toggle', () => {
  assert.match(docJs, /data-dd="format"/);
});

test('loose markdown format buttons were removed from the toolbar template', () => {
  for (const attr of [
    'data-md="bold"',
    'data-md="italic"',
    'data-md="strike"',
    'data-md="link"',
    'data-md="hr"',
    'data-dd="heading"',
    'data-dd="list"',
    'data-dd="code"',
  ]) {
    assert.ok(!docJs.includes(attr), `expected toolbar template to no longer contain ${attr}`);
  }
});

test('dead Attach files button was removed from the toolbar', () => {
  assert.ok(!docJs.includes('id="md-toolbar-attach-btn"'));
  assert.ok(!docJs.includes("data-action=\"undock-format\""));
});

test('the Format dropdown group covers the full markdown action set', () => {
  // The `format` group is registered in _showMdDropdown.
  assert.match(docJs, /format: \[/);
  for (const action of [
    "'bold'", "'italic'", "'strike'",
    "'h1'", "'h2'", "'h3'",
    "'ul'", "'ol'",
    "'code'", "'codeblock'",
    "'link'", "'hr'",
  ]) {
    assert.ok(docJs.includes(action), `Format group should include action ${action}`);
  }
});

test('keyboard shortcuts for bold/italic/link remain wired', () => {
  assert.match(docJs, /applyMdFormat\('bold'\)/);
  assert.match(docJs, /applyMdFormat\('italic'\)/);
  assert.match(docJs, /applyMdFormat\('link'\)/);
});

test('right cluster is Undo | Redo | type | actions menu', () => {
  assert.ok(docJs.includes('id="doc-undo-btn"'));
  assert.ok(docJs.includes('id="doc-redo-btn"'));
  assert.ok(docJs.includes('id="doc-actions-menu-btn"'));
  assert.ok(!docJs.includes('doc-copy-export-split'));
  assert.ok(!docJs.includes('doc-header-preview-btn'));
  assert.ok(!docJs.includes('doc-footer-copy-btn'));
});

test('font size opens a stepped slider popover', () => {
  assert.ok(docJs.includes('doc-fontsize-popover'));
  assert.match(docJs, /function showDocActionsMenu/);
  assert.ok(docJs.includes('_pdfRedoStackByDoc'));
});
