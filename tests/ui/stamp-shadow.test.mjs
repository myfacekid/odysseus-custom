// Hard-offset drop uses translucent black, not an opaque panel shade.
//
// Run with:  node --test tests/ui/stamp-shadow.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { stampShadowInks } from '../../static/js/color/hex.js';

test('Operandi Tinted paper is an 18% black drop (same as the original stamp)', () => {
  const { ink, press } = stampShadowInks('#fbf7f0');
  assert.equal(ink, 'rgba(0, 0, 0, 0.18)');
  assert.equal(press, 'rgba(0, 0, 0, 0.14)');
});

test('cream panel also stays at the light-surface 18% drop', () => {
  const { ink } = stampShadowInks('#efe9dd');
  assert.equal(ink, 'rgba(0, 0, 0, 0.18)');
});

test('dark pages raise alpha but stay translucent black (not a light glow)', () => {
  const { ink, press } = stampShadowInks('#000000');
  assert.match(ink, /^rgba\(0, 0, 0, 0\.5\)$/);
  assert.match(press, /^rgba\(0, 0, 0, /);
  assert.notEqual(ink, press);
});

test('invalid surface yields null inks', () => {
  assert.deepEqual(stampShadowInks('nope'), { ink: null, press: null });
});
