// Structural smoke for Project Files pop-out sheet (F1–F4).
//
// Run with:  node --test tests/ui/project-files-sheet.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

const pickerJs = read('static/js/projects/filePicker.js');
const styleCss = read('static/style.css');
const chipJs = read('static/js/projects/activeChip.js');

test('sheet shell uses modal-content (pointer-events fix)', () => {
  assert.ok(pickerJs.includes("className = 'modal project-files-sheet hidden'")
    || pickerJs.includes('modal project-files-sheet'));
  assert.ok(pickerJs.includes('modal-content project-files-sheet-content'));
  assert.ok(!pickerJs.includes('modal-box'));
});

test('tree and reader regions exist', () => {
  assert.ok(pickerJs.includes('id="project-files-tree"'));
  assert.ok(pickerJs.includes('id="project-files-reader-body"'));
  assert.ok(pickerJs.includes('project-files-tree-row'));
  assert.ok(pickerJs.includes('expandDir') || pickerJs.includes('async function expandDir'));
});

test('reader is read-only with Project file depth badge', () => {
  assert.ok(pickerJs.includes('project-files-cwd-badge'));
  assert.ok(pickerJs.includes('Project file'));
  assert.ok(pickerJs.includes('contentViewer'));
  assert.ok(!pickerJs.includes('write_project_file'));
  assert.ok(!pickerJs.includes('PUT'));
});

test('inline promote panel (not a second broken modal)', () => {
  assert.ok(pickerJs.includes('project-files-promote-panel'));
  assert.ok(pickerJs.includes('/promote'));
  assert.ok(pickerJs.includes('Open in Library') || pickerJs.includes('Open Notes'));
});

test('depth accent styling and motion', () => {
  assert.ok(styleCss.includes('.project-files-cwd-badge'));
  assert.ok(styleCss.includes('--project-depth-accent'));
  assert.ok(styleCss.includes('@keyframes project-files-sheet-in'));
  assert.ok(styleCss.includes('@keyframes project-files-reader-in'));
  assert.ok(styleCss.includes('.project-files-library-badge'));
});

test('Explore tool entry (sidebar + rail) opens the sheet', () => {
  const appJs = read('static/app.js');
  const registry = read('static/js/nav/toolRegistry.js');
  const indexHtml = read('static/index.html');
  assert.ok(registry.includes("key: 'project-files'"));
  assert.ok(indexHtml.includes('id="tool-project-files-btn"'));
  assert.ok(appJs.includes('syncProjectFilesToolVisibility'));
  assert.ok(appJs.includes("import('./js/projects/filePicker.js')"));
  assert.ok(appJs.includes('openProjectFilePicker'));
  // Chip no longer hosts Browse files
  assert.ok(!chipJs.includes('openProjectFilePicker'));
});
