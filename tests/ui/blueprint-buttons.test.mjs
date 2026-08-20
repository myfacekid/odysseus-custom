// Structural smoke test for raised Blueprint button primitives.
//
// Run with:  node --test tests/ui/blueprint-buttons.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const css = readFileSync(join(repoRoot, 'static', 'style.css'), 'utf8');
const indexHtml = readFileSync(join(repoRoot, 'static', 'index.html'), 'utf8');

function firstRule(selector) {
  const re = new RegExp(`${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\{([\\s\\S]*?)\\}`);
  const m = css.match(re);
  assert.ok(m, `rule exists: ${selector}`);
  return m[1];
}

test('raised stamp tokens exist', () => {
  assert.match(css, /--shadow-ink:\s*color-mix\(in srgb, black 18%, transparent\)/);
  assert.match(css, /--shadow-press-ink:\s*color-mix\(in srgb, black 12%, transparent\)/);
  assert.match(css, /--shadow-hard:\s*2px 2px 0 var\(--shadow-ink\)/);
  assert.match(css, /--shadow-press:\s*1px 1px 0 var\(--shadow-press-ink\)/);
  assert.match(css, /--radius-tech:\s*2px/);
});

test('labeled button primitive uses hard stamp, not a flat fill', () => {
  const prim = css.slice(css.indexOf('/* ── Blueprint primitives'));
  const btnBlock = prim.match(/\.btn,\n\.admin-btn-sm,[\s\S]*?\{([\s\S]*?)\}/);
  assert.ok(btnBlock, 'shared primitive selector exists');
  const body = btnBlock[1];
  assert.match(body, /box-shadow:\s*var\(--shadow-hard/);
  assert.match(body, /border-radius:\s*var\(--radius-tech/);
  assert.match(body, /border:\s*1px solid transparent/);
  assert.doesNotMatch(body, /box-shadow:\s*none/);
  assert.doesNotMatch(body, /border-radius:\s*var\(--radius-tech, 2px\) 0 0/);
});

test('labeled buttons have an understated 1px press', () => {
  const m = css.match(/\.btn:active:not\(:disabled\),[\s\S]*?\{([\s\S]*?)\}/);
  assert.ok(m, ':active press rule exists');
  assert.match(m[1], /translate\(1px, 1px\)/);
  assert.match(m[1], /var\(--shadow-press/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
});

test('project slate items are explicitly raised, not via the -menu wildcard', () => {
  const idx = css.indexOf('.project-chip-menu-item {');
  assert.ok(idx >= 0, '.project-chip-menu-item rule exists');
  const body = css.slice(idx, idx + 1200);
  assert.match(body, /box-shadow:\s*var\(--shadow-hard/);
  assert.match(body, /border:\s*1px solid transparent/);
  assert.match(css, /\[class\*="-menu"\]:not\(\[class\*="-menu-"\]\)/);
  const wildcard = css.match(/\[class\*="-menu"\]:not\(\[class\*="-menu-"\]\):not\(button\):not\(\[class\*="-btn"\]\),[\s\S]*?\{([\s\S]*?)\}/);
  assert.ok(wildcard, 'narrowed floating-surface selector exists');
  assert.match(wildcard[1], /var\(--shadow-hard/);
});

test('isolated labeled buttons keep symmetric tech corners', () => {
  assert.match(css, /\.btn-flush-end \{/);
  assert.match(css, /\.btn-flush-start \{/);
  const cascade = css.slice(css.indexOf('/* Blueprint full-app cascade'));
  assert.doesNotMatch(
    cascade.slice(0, 2500),
    /Asymmetric — open side is square so it meets the slate/,
  );
});

test('choice dialogs stack as 4px plates', () => {
  const body = firstRule('.styled-choice-footer');
  assert.match(body, /flex-direction:\s*column/);
  assert.match(body, /gap:\s*4px/);
});

test('composer and doc toolbars use the raised stamp', () => {
  const inputIdx = css.indexOf('.input-icon-btn {\n      background:');
  assert.ok(inputIdx >= 0, '.input-icon-btn stamp rule exists');
  const inputBody = css.slice(inputIdx, inputIdx + 900);
  assert.match(inputBody, /box-shadow:\s*var\(--shadow-hard/);
  assert.match(inputBody, /border:\s*1px solid transparent/);

  const mdIdx = css.indexOf('.doc-md-toolbar button {');
  assert.ok(mdIdx >= 0, '.doc-md-toolbar button rule exists');
  const mdBody = css.slice(mdIdx, mdIdx + 900);
  assert.match(mdBody, /box-shadow:\s*var\(--shadow-hard/);

  assert.match(css, /\.input-icon-btn:active:not\(:disabled\)/);
  assert.match(css, /\.doc-md-toolbar button:active:not\(:disabled\)/);
  assert.match(css, /\.project-workspace-icon-btn:active:not\(:disabled\)/);
});

test('raised plates keep a transparent stroke so the drop is the only edge', () => {
  const idx = css.indexOf('/* Raised plates: fill + bottom-right drop only.');
  assert.ok(idx >= 0, 'late transparent-stroke cascade exists');
  const block = css.slice(idx, idx + 2800);
  assert.match(block, /border-color:\s*transparent/);
  assert.match(block, /\.project-chip-menu-item,/);
  assert.match(block, /\.input-icon-btn,/);
  assert.match(block, /\.input-icon-btn:hover,/);
  assert.doesNotMatch(block, /border-color:\s*var\(--(border|accent)/);
});

test('composer mode and permission toggles are a joined stamped segment bar', () => {
  const modeIdx = css.indexOf('/* Mode toggle — joined Agent / Plan / Chat bar, stamped as one plate */');
  assert.ok(modeIdx >= 0, 'mode toggle stamp block exists');
  const modeBlock = css.slice(modeIdx, modeIdx + 4200);
  assert.match(modeBlock, /\.mode-toggle \{[\s\S]*?box-shadow:\s*var\(--shadow-hard/);
  assert.match(modeBlock, /\.mode-toggle \{[\s\S]*?border:\s*1px solid transparent/);
  assert.match(modeBlock, /\.perm-toggle \{[\s\S]*?box-shadow:\s*var\(--shadow-hard/);
  assert.match(modeBlock, /\.perm-toggle \{[\s\S]*?border:\s*1px solid transparent/);
  assert.match(modeBlock, /\.mode-toggle::before \{/);
  assert.match(modeBlock, /--mode-pill-x/);
  assert.match(modeBlock, /\.perm-toggle\[data-perm="auto"\]::before/);
  assert.match(modeBlock, /\.mode-toggle-btn \{[\s\S]*?box-shadow:\s*none/);
  assert.match(modeBlock, /\.perm-toggle-btn \{[\s\S]*?box-shadow:\s*none/);
  assert.doesNotMatch(modeBlock, /\.mode-toggle::before \{ display: none; \}/);
});

test('icon rail uses stamped plates and a hard right seam', () => {
  const railIdx = css.indexOf('.icon-rail {\n      width: 48px;');
  assert.ok(railIdx >= 0, '.icon-rail rule exists');
  const railBody = css.slice(railIdx, railIdx + 900);
  assert.match(railBody, /box-shadow:\s*2px 0 0 var\(--shadow-ink/);
  assert.doesNotMatch(railBody, /border-right:\s*1px solid var\(--border\)/);

  const btnIdx = css.indexOf('.icon-rail-btn {\n      position: relative;');
  assert.ok(btnIdx >= 0, '.icon-rail-btn rule exists');
  const btnBody = css.slice(btnIdx, btnIdx + 900);
  assert.match(btnBody, /box-shadow:\s*var\(--shadow-hard/);
  assert.match(btnBody, /border:\s*1px solid transparent/);

  const sepIdx = css.indexOf('.icon-rail-divider,\n    .rail-separator {');
  assert.ok(sepIdx >= 0, 'rail separator stamp rule exists');
  const sepBody = css.slice(sepIdx, sepIdx + 500);
  assert.match(sepBody, /box-shadow:\s*var\(--shadow-hard/);
  assert.match(css, /\.icon-rail-btn:active:not\(:disabled\)/);
});

test('expanded sidebar stamps icons only and matches rail order', () => {
  const sideIdx = css.indexOf('.sidebar {\n      width: 240px;');
  assert.ok(sideIdx >= 0, '.sidebar rule exists');
  const sideBody = css.slice(sideIdx, sideIdx + 900);
  assert.match(sideBody, /box-shadow:\s*2px 0 0 var\(--shadow-ink/);
  assert.doesNotMatch(sideBody, /border-right:\s*1px solid var\(--border\)/);
  assert.doesNotMatch(sideBody, /border:\s*1px solid color-mix\(in srgb, var\(--fg\) 11%/);

  const plateIdx = css.indexOf('/* Sidebar chrome rows — stamp lives on the icon well only');
  assert.ok(plateIdx >= 0, 'icon-well sidebar chrome block exists');
  const plateBody = css.slice(plateIdx, plateIdx + 4500);
  assert.match(plateBody, /height:\s*34px/);
  assert.match(plateBody, /min-height:\s*34px/);
  assert.match(plateBody, /background:\s*transparent/);
  assert.match(plateBody, /box-shadow:\s*none/);
  assert.match(plateBody, /color-mix\(in srgb, var\(--panel\) 92%, var\(--fg\)\)/);
  assert.match(plateBody, /#tools-section \.list-item > svg:first-of-type/);
  assert.match(plateBody, /\.section-header-flex \.section-icon/);
  assert.match(plateBody, /#session-list \.session-item \.session-icon/);
  assert.match(plateBody, /#sidebar-search-btn::after/);
  assert.match(plateBody, /content:\s*'Ctrl\+K'/);
  assert.match(plateBody, /content:\s*'›'/);

  // Expanded top actions mirror the rail: Search, then New Chat.
  const searchPos = indexHtml.indexOf('id="sidebar-search-btn"');
  const newChatPos = indexHtml.indexOf('id="sidebar-new-chat-btn"');
  assert.ok(searchPos > 0 && newChatPos > searchPos, 'sidebar order is Search then New Chat');
});
