// static/js/color/hex.js
//
// Parse a CSS hex color into {r, g, b}. Pure — no DOM — so it can be reused
// across modules and unit-tested under node.

// Accepts "#rgb", "#rrggbb" (with or without the leading '#'). Returns null
// for anything that isn't a valid 3- or 6-digit hex color.
export function hexToRgb(hex) {
  let h = String(hex || '').trim().replace(/^#/, '');
  if (h.length === 3) h = h.split('').map((c) => c + c).join('');
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return null;
  const n = parseInt(h, 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function _srgbChannelToLin(c) {
  const x = c / 255;
  return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
}

/** Relative luminance (WCAG) of a parsed {r,g,b} sRGB triple. */
export function relativeLuminance(rgb) {
  if (!rgb) return 0;
  return 0.2126 * _srgbChannelToLin(rgb.r)
    + 0.7152 * _srgbChannelToLin(rgb.g)
    + 0.0722 * _srgbChannelToLin(rgb.b);
}

/**
 * Translucent black drop-shadow inks for raised buttons.
 *
 * Operandi Tinted's look is 18% black over the paper — a hard offset
 * drop, not an opaque second plate. Mixing --fg made neon/dark themes
 * glow; mixing --panel made a solid shade. Always black + alpha.
 *
 * `surfaceHex` is the page/panel the shadow falls on. Light surfaces
 * keep 0.18; darker ones raise alpha so the drop still reads.
 *
 * Returns { ink, press } CSS colors, or nulls if `surfaceHex` is invalid.
 */
export function stampShadowInks(surfaceHex) {
  const rgb = hexToRgb(surfaceHex);
  if (!rgb) return { ink: null, press: null };
  const L = relativeLuminance(rgb);
  const alpha = L >= 0.5 ? 0.18 : L >= 0.25 ? 0.28 : L >= 0.12 ? 0.40 : 0.50;
  const press = Math.round(alpha * (14 / 18) * 1000) / 1000;
  return {
    ink: `rgba(0, 0, 0, ${alpha})`,
    press: `rgba(0, 0, 0, ${press})`,
  };
}
