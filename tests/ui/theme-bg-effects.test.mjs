// Structural smoke test for theme background effects.
//
// Covers: canvas effect lifecycle (orphan rAF leak fix), Perlin trail fade,
// dots CSS fallback, and the expanded canvas effect set.
//
// Run with:  node --test tests/ui/theme-bg-effects.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

const themeJs = read('static/js/theme.js');
const styleCss = read('static/style.css');
const loginHtml = read('static/login.html');
const indexHtml = read('static/index.html');

const NEW_EFFECTS = [
  'fireflies', 'aurora', 'paper-grain', 'ripple',
  'drift-grid', 'orbit-rings', 'fog',
];

test('canvas effects share a lifecycle helper that stops detached canvases', () => {
  assert.match(themeJs, /function _startCanvasLoop\(canvas, patternClass, onResize, paint\)/);
  assert.match(themeJs, /!document\.body\.contains\(canvas\)/);
  assert.match(themeJs, /cancelAnimationFrame\(raf\)/);
  assert.match(themeJs, /if \(document\.hidden\) return/);
  // 7 original + 7 new inits call the helper (exclude the function definition).
  const calls = themeJs.match(/^\s+_startCanvasLoop\(canvas,/gm) || [];
  assert.equal(calls.length, 14);
});

test('class-only rAF stop is gone (would orphan loops on re-apply)', () => {
  assert.doesNotMatch(
    themeJs,
    /if \(!document\.body\.classList\.contains\('bg-pattern-/,
  );
});

test('canvas cleanup uses data-bg-effect so new effects are removed', () => {
  assert.match(themeJs, /querySelectorAll\('canvas\[data-bg-effect\]'\)/);
  assert.match(themeJs, /function _mountBgCanvas\(id\)/);
  assert.match(themeJs, /dataset\.bgEffect = '1'/);
});

test('Perlin uses finite trails + clearRect (no canvas ink accumulation)', () => {
  const perlinStart = themeJs.indexOf('function _initPerlinFlow');
  const perlinEnd = themeJs.indexOf('function _initPetals');
  assert.ok(perlinStart >= 0 && perlinEnd > perlinStart);
  const perlin = themeJs.slice(perlinStart, perlinEnd);
  assert.match(perlin, /clearRect\(0, 0, W, H\)/);
  assert.match(perlin, /TRAIL_LEN/);
  assert.match(perlin, /Float32Array\(TRAIL_LEN\)/);
  assert.match(perlin, /MAX_PARTICLES \* _getEffectIntensity\(\)/);
  assert.doesNotMatch(perlin, /destination-out/);
});

test('applyBgEffectColor removes the property when empty so CSS can fall back', () => {
  assert.match(themeJs, /removeProperty\('--bg-effect-color'\)/);
  assert.doesNotMatch(
    themeJs,
    /setProperty\('--bg-effect-color', color \|\| ''\)/,
  );
});

test('dots CSS uses intensity + size and a stronger base mix', () => {
  assert.match(
    styleCss,
    /body\.bg-pattern-dots \{[\s\S]*?calc\(10% \* var\(--bg-effect-intensity/,
  );
  assert.match(
    styleCss,
    /body\.bg-pattern-dots \{[\s\S]*?--bg-effect-size/,
  );
  assert.match(styleCss, /:root \{ --bg-effect-intensity: 1; --bg-effect-size: 1; \}/);
});

test('login.html mirrors dots CSS', () => {
  assert.match(
    loginHtml,
    /body\.bg-pattern-dots \{[\s\S]*?calc\(10% \* var\(--bg-effect-intensity/,
  );
  assert.match(
    loginHtml,
    /body\.bg-pattern-dots \{[\s\S]*?--bg-effect-size/,
  );
});

test('intensity/size sliders are shown for dots (not treated as static)', () => {
  assert.match(themeJs, /const _STATIC_PATTERNS = new Set\(\['none'\]\)/);
  assert.doesNotMatch(themeJs, /new Set\(\['none', 'dots'\]\)/);
});

test('new background effects are registered, selectable, and RAM-bounded', () => {
  for (const id of NEW_EFFECTS) {
    const fn = '_init' + id.split('-').map((s) => s[0].toUpperCase() + s.slice(1)).join('');
    // fog → _initFog, paper-grain → _initPaperGrain, etc.
    assert.match(themeJs, new RegExp(`function ${fn}\\(`));
    assert.match(themeJs, new RegExp(`'bg-pattern-${id}'`));
    assert.match(themeJs, new RegExp(`bg-pattern-${id}`));
    assert.match(indexHtml, new RegExp(`<option value="${id}">`));
  }
  // Hard caps / fixed buffers — no unbounded growth
  assert.match(themeJs, /const MAX = 28/);           // fireflies
  assert.match(themeJs, /const BANDS = 4/);          // aurora
  assert.match(themeJs, /const GW = 128, GH = 128/); // paper-grain fixed buffer
  assert.match(themeJs, /const MAX = 6/);            // ripple + fog
  assert.match(themeJs, /const RINGS = 5/);          // orbit-rings
});

test('CSS intensity applies to all data-bg-effect canvases', () => {
  assert.match(styleCss, /canvas\[data-bg-effect\] \{\s*opacity: var\(--bg-effect-intensity/);
});
