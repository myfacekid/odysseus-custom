// Theme system — preset themes + custom color editing, stored in localStorage
// ES6 module

import Storage from './storage.js';
import uiModule from './ui.js';
import { initColorPickers, attachColorPicker } from './colorPicker.js';
import { hexToRgb } from './color/hex.js';
import { makeWindowDraggable } from './windowDrag.js';
import { snapModalToZone } from './tileManager.js';

// Protesilaos Modus themes — https://protesilaos.com/emacs/modus-themes-colors (CC0)
// App `red` is the UI accent/brand token; true palette red lives in accentError.
const _MODUS_OPERANDI_TINTED = {
  bg: '#fbf7f0', fg: '#000000', panel: '#efe9dd', border: '#9f9690', red: '#0031a9',
  advanced: {
    accentPrimary: '#0031a9', accentWarm: '#6d5000', accentError: '#a60000',
    brandColor: '#0031a9', sendBtnBg: '#0031a9', sendBtnHover: '#3546c2',
    toggleActive: '#0031a9', inputBg: '#fbf7f0', codeBg: '#efe9dd', codeFg: '#000000',
  },
};

export const THEMES = {
  'modus-operandi': {
    bg: '#ffffff', fg: '#000000', panel: '#f2f2f2', border: '#9f9f9f', red: '#0031a9',
    advanced: {
      accentPrimary: '#0031a9', accentWarm: '#6f5500', accentError: '#a60000',
      brandColor: '#0031a9', sendBtnBg: '#0031a9', sendBtnHover: '#3548cf',
      toggleActive: '#0031a9', inputBg: '#ffffff', codeBg: '#f2f2f2', codeFg: '#000000',
    },
  },
  'modus-operandi-tinted': _MODUS_OPERANDI_TINTED,
  // Legacy alias — same object as tinted; hidden from the picker swatch grid.
  modus: _MODUS_OPERANDI_TINTED,
  'modus-vivendi': {
    bg: '#000000', fg: '#ffffff', panel: '#1e1e1e', border: '#646464', red: '#2fafff',
    advanced: {
      accentPrimary: '#2fafff', accentWarm: '#d0bc00', accentError: '#ff5f59',
      brandColor: '#2fafff', sendBtnBg: '#2fafff', sendBtnHover: '#79a8ff',
      toggleActive: '#2fafff', inputBg: '#000000', codeBg: '#1e1e1e', codeFg: '#ffffff',
    },
  },
  'modus-vivendi-tinted': {
    bg: '#0d0e1c', fg: '#ffffff', panel: '#1d2235', border: '#61647a', red: '#2fafff',
    advanced: {
      accentPrimary: '#2fafff', accentWarm: '#d0bc00', accentError: '#ff5f59',
      brandColor: '#2fafff', sendBtnBg: '#2fafff', sendBtnHover: '#79a8ff',
      toggleActive: '#2fafff', inputBg: '#0d0e1c', codeBg: '#1d2235', codeFg: '#ffffff',
    },
  },
  'doom-one': {
    bg: '#282c34', fg: '#bbc2cf', panel: '#21242b', border: '#3f444a', red: '#51afef',
    advanced: {
      accentPrimary: '#51afef', accentWarm: '#ECBE7B', accentError: '#ff6c6b',
      brandColor: '#51afef', sendBtnBg: '#51afef', sendBtnHover: '#2257A0',
      toggleActive: '#51afef', inputBg: '#21242b', codeBg: '#21242b', codeFg: '#bbc2cf',
    },
  },
  dark:       { bg:'#282c34', fg:'#9cdef2', panel:'#111111', border:'#355a66', red:'#e06c75' },
  light:      { bg:'#f0ebe3', fg:'#5a5248', panel:'#faf6f0', border:'#d4cdc2', red:'#c47d5a' },
  midnight:   { bg:'#0d1117', fg:'#c9d1d9', panel:'#161b22', border:'#30363d', red:'#f85149' },
  paper:      { bg:'#faf8f5', fg:'#3b3836', panel:'#ffffff', border:'#d5d0c8', red:'#c5ac4a' },
  // Spicy / fun themes
  cyberpunk:  { bg:'#0a0a0f', fg:'#0ff0fc', panel:'#12101a', border:'#9b30ff', red:'#e040fb' },
  retrowave:  { bg:'#1a1a2e', fg:'#e94560', panel:'#16213e', border:'#533483', red:'#e94560' },
  forest:     { bg:'#1b2a1b', fg:'#a8d5a2', panel:'#142414', border:'#3d6b3d', red:'#7cb871' },
  ocean:      { bg:'#0b1a2c', fg:'#64d2ff', panel:'#091422', border:'#1e5074', red:'#4facfe' },
  ume:        { bg:'#2b1b2e', fg:'#f5c2e7', panel:'#1e1420', border:'#6c4675', red:'#f5a0c0' },
  copper:     { bg:'#1c1410', fg:'#e8c39e', panel:'#140f0a', border:'#7a5533', red:'#d4764e' },
  terminal:   { bg:'#000000', fg:'#00ff41', panel:'#0a0a0a', border:'#003b00', red:'#00ff41' },
  organs:     { bg:'#0a0406', fg:'#efe1c8', panel:'#15080a', border:'#3a1519', red:'#c83240' },
  lavender:   { bg:'#f3eef8', fg:'#3d3551', panel:'#faf7ff', border:'#cec3de', red:'#9b6dcc' },
  gpt:        { bg:'#212121', fg:'#ececec', panel:'#171717', border:'#424242', red:'#949494',
                advanced: { sendBtnBg: '#949494', sendBtnHover: '#7f7f7f',
                            userBubbleBg: '#2f2f2f', aiBubbleBg: '#171717',
                            inputBg: '#2f2f2f' } },
  claude:     { bg:'#262624', fg:'#f5f4f0', panel:'#30302e', border:'#4a4a47', red:'#c6613f' },
  cute:       { bg:'#fff0f5', fg:'#d4608a', panel:'#fff8fa', border:'#f0c0d0', red:'#ff6b9d' },
};

export const DEFAULT_THEME = 'modus-operandi-tinted';
// Canonical key is Storage.KEYS.THEME ('nobody-theme'); legacy oculus-
// theme keys are migrated on read and cleared on write/remove.
// Dark swatch label stays 'odysseus' (THEME_LABELS.dark) by design.
const LS_KEY = Storage.KEYS.THEME;
const CUSTOM_THEMES_KEY = 'nobody-custom-themes';
// Alias keys that resolve in THEMES but are omitted from the swatch grid.
const THEME_ALIAS_KEYS = new Set(['modus']);

const THEME_LABELS = {
  dark: 'odysseus',
  gpt: 'GPT',
  'modus-operandi': 'Operandi',
  'modus-operandi-tinted': 'Operandi Tinted',
  'modus-vivendi': 'Vivendi',
  'modus-vivendi-tinted': 'Vivendi Tinted',
};

const FONT_MAP = {
  // Monospace
  mono: "'Iosevka', monospace",
  fira: "'Fira Code', monospace",
  jetbrains: "'JetBrains Mono', monospace",
  'roboto-mono': "'Roboto Mono', monospace",
  // Sans-serif
  'ibm-plex': "'IBM Plex Sans', system-ui, sans-serif",
  'source-sans': "'Source Sans 3', system-ui, sans-serif",
  atkinson: "'Atkinson Hyperlegible', system-ui, sans-serif",
  manrope: "'Manrope', system-ui, sans-serif",
  'space-grotesk': "'Space Grotesk', system-ui, sans-serif",
  outfit: "'Outfit', system-ui, sans-serif",
  sans: "system-ui, -apple-system, 'Segoe UI', sans-serif",
  // Serif
  literata: "'Literata', Georgia, serif",
  'source-serif': "'Source Serif 4', Georgia, serif",
  lora: "'Lora', Georgia, serif",
  newsreader: "'Newsreader', Georgia, serif",
  fraunces: "'Fraunces', Georgia, serif",
  // Legacy alias (pre-expansion Georgia option)
  serif: "'Literata', Georgia, serif",
};
const DEFAULT_FONT = 'mono';
const DEFAULT_DENSITY = 'comfortable';
const MAX_CUSTOM_THEMES = 8;

// Default background patterns for built-in themes
const THEME_DEFAULT_PATTERN = {
  modus:                   'dots',
  'modus-operandi':        'dots',
  'modus-operandi-tinted': 'dots',
  'modus-vivendi':         'none',
  'modus-vivendi-tinted':  'none',
  'doom-one':              'none',
  dark:                    'none',
  light:                   'dots',
  midnight:                'rain',
  paper:                   'dots',
  cyberpunk:               'synapse',
  retrowave:               'embers',
  forest:                  'petals',
  ocean:                   'constellations',
  terminal:                'perlin-flow',
  organs:                  'rain',
  ume:                     'petals',
  cute:                    'sparkles',
};

// Default effect colors for specific themes (overrides --fg)
const THEME_DEFAULT_EFFECT_COLOR = {
  midnight:   '#ffffff',
  organs:     '#451616',
  cute:       '#ff8cb8',
  ume:        '#f5a0c0',
};

// Default effect intensity (0..1) per theme. Any theme not listed defaults to 1.
const THEME_DEFAULT_INTENSITY = {
  midnight:   0.5,
  terminal:   0.8,
  organs:     0.65,
};

// Default frosted-glass state per theme. Themes not listed default to false.
const THEME_DEFAULT_FROSTED = {
  lavender:   true,
};

// ── Custom theme persistence ──
function _loadCustomThemes() {
  return Storage.getJSON(CUSTOM_THEMES_KEY, {});
}
function _saveCustomThemes(obj) {
  Storage.setJSON(CUSTOM_THEMES_KEY, obj);
}
export function saveCustomTheme(name, colors, opts) {
  const ct = _loadCustomThemes();
  // Enforce limit — allow overwriting existing, block new past max
  if (!ct[name] && Object.keys(ct).length >= MAX_CUSTOM_THEMES) {
    return 'limit';
  }
  const entry = { ...colors };
  if (opts) {
    if (opts.font) entry.font = opts.font;
    if (opts.density) entry.density = opts.density;
    if (opts.bgPattern) entry.bgPattern = opts.bgPattern;
    if (opts.bgEffectColor) entry.bgEffectColor = opts.bgEffectColor;
    if (opts.bgEffectIntensity !== undefined) entry.bgEffectIntensity = opts.bgEffectIntensity;
    if (opts.bgEffectSize !== undefined) entry.bgEffectSize = opts.bgEffectSize;
    if (opts.frosted !== undefined) entry.frosted = !!opts.frosted;
    if (opts.glass !== undefined) entry.glass = !!opts.glass;
  }
  ct[name] = entry;
  _saveCustomThemes(ct);
  _syncCustomThemesToServer(ct);
  initThemeUI();
  return 'ok';
}
export function deleteCustomTheme(name) {
  const ct = _loadCustomThemes();
  delete ct[name];
  _saveCustomThemes(ct);
  _syncCustomThemesToServer(ct);
  initThemeUI();
}
function _syncCustomThemesToServer(ct) {
  try {
    fetch('/api/prefs/custom-themes', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ value: ct }),
    }).catch(e => console.warn('Theme sync (custom) failed:', e));
  } catch (e) { console.warn('Theme sync (custom) error:', e); }
}

// --- Syntax color derivation from theme base colors ---
function hexToHSL(hex) {
  const rgb = hexToRgb(hex) || { r: 0, g: 0, b: 0 };
  const r = rgb.r / 255;
  const g = rgb.g / 255;
  const b = rgb.b / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  let h, s, l = (max + min) / 2;
  if (max === min) { h = s = 0; }
  else {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
    else if (max === g) h = ((b - r) / d + 2) / 6;
    else h = ((r - g) / d + 4) / 6;
  }
  return [h * 360, s * 100, l * 100];
}

function hslToHex(h, s, l) {
  h = ((h % 360) + 360) % 360;
  s = Math.max(0, Math.min(100, s)) / 100;
  l = Math.max(0, Math.min(100, l)) / 100;
  const a = s * Math.min(l, 1 - l);
  const f = n => { const k = (n + h / 30) % 12; return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
  const toHex = v => Math.round(v * 255).toString(16).padStart(2, '0');
  return '#' + toHex(f(0)) + toHex(f(8)) + toHex(f(4));
}

let _projectAccentGuardLogged = false;

function _hueDelta(h1, h2) {
  const d = Math.abs(h1 - h2);
  return Math.min(d, 360 - d);
}

function _applyProjectAccentTokens(s, depthHex, breadthHex, accentPrimary) {
  let breadth = breadthHex;
  const depth = depthHex;
  const [dH] = hexToHSL(depth);
  const [bH, bS, bL] = hexToHSL(breadth);
  const [pH, pS] = hexToHSL(accentPrimary);
  const sameHex = depth.toLowerCase() === breadth.toLowerCase();
  if (sameHex || _hueDelta(dH, bH) < 45) {
    breadth = hslToHex(pH, Math.max(bS, pS, 35), bL);
    const [nH] = hexToHSL(breadth);
    if (depth.toLowerCase() === breadth.toLowerCase() || _hueDelta(dH, nH) < 45) {
      breadth = hslToHex((pH + 120) % 360, Math.max(bS, 45), bL);
    }
    if (!_projectAccentGuardLogged) {
      console.info('[theme] Project accent hue guard adjusted breadth for depth/breadth separation');
      _projectAccentGuardLogged = true;
    }
  }
  s.setProperty('--project-depth-accent', depth);
  s.setProperty('--project-breadth-accent', breadth);
  s.setProperty('--project-depth-surface', 'color-mix(in srgb, var(--project-depth-accent) 12%, var(--panel))');
  s.setProperty('--project-breadth-surface', 'color-mix(in srgb, var(--project-breadth-accent) 12%, var(--panel))');
}

function deriveSyntaxColors(colors) {
  const [fgH, fgS, fgL] = hexToHSL(colors.fg);
  const [bgH, bgS, bgL] = hexToHSL(colors.bg);
  const [redH, redS, redL] = hexToHSL(colors.red || '#e06c75');
  const isDark = bgL < 50;
  const codeBgL = isDark ? Math.max(bgL - 4, 0) : Math.min(bgL + 4, 100);
  return {
    bg: hslToHex(bgH, bgS, codeBgL),
    fg: colors.fg,
    keyword: hslToHex((redH + 280) % 360, Math.min(redS + 10, 80), isDark ? 70 : 45),
    string: hslToHex(40, Math.min(fgS + 20, 70), isDark ? 72 : 42),
    comment: hslToHex(fgH, Math.max(fgS - 20, 5), isDark ? (fgL * 0.5 + bgL * 0.5) : (fgL * 0.5 + bgL * 0.5)),
    function: hslToHex(210, Math.min(fgS + 20, 75), isDark ? 70 : 45),
    // Extra token colors for richer highlighting
    number: hslToHex(20, Math.min(fgS + 15, 65), isDark ? 68 : 48),
    builtin: hslToHex(180, Math.min(fgS + 15, 60), isDark ? 65 : 40),
    variable: hslToHex((fgH + 30) % 360, Math.min(fgS + 5, 60), isDark ? fgL : fgL),
    params: hslToHex(fgH, Math.max(fgS - 5, 10), isDark ? Math.min(fgL + 8, 85) : Math.max(fgL - 8, 25)),
  };
}

// Advanced picker key → CSS variable mapping
const ADV_KEYS = [
  { key: 'userBubbleBg',       css: '--user-bubble-bg',    label: 'User Chat Bubble', group: 'Chat Bubbles' },
  { key: 'aiBubbleBg',         css: '--ai-bubble-bg',      label: 'AI Chat Bubble',   group: 'Chat Bubbles' },
  { key: 'bubbleBorder',       css: '--bubble-border',     label: 'Border Chat Bubble', group: 'Chat Bubbles' },
  { key: 'sidebarBg',          css: '--sidebar-bg',        label: 'Sidebar Bg',       group: 'Sidebar' },
  { key: 'brandColor',         css: '--brand-color',       label: 'Nobody Logo',    group: 'Sidebar' },
  { key: 'hamburgerColor',     css: '--hamburger-color',   label: 'Hamburger Menu',   group: 'Sidebar' },
  { key: 'inputBg',            css: '--input-bg',          label: 'Input Bg',         group: 'Chat Input / Prompt Area' },
  { key: 'inputBorder',        css: '--input-border',      label: 'Input Border',     group: 'Chat Input / Prompt Area' },
  { key: 'sendBtnBg',          css: '--send-btn-bg',       label: 'Send Btn',         group: 'Chat Input / Prompt Area' },
  { key: 'sendBtnHover',       css: '--send-btn-hover',    label: 'Send Hover',       group: 'Chat Input / Prompt Area' },
  { key: 'codeBg',             css: '--code-bg',           label: 'Code Bg',          group: 'Code Blocks' },
  { key: 'codeFg',             css: '--code-fg',           label: 'Code Text',        group: 'Code Blocks' },
  { key: 'toggleActive',       css: '--toggle-active',     label: 'Toggle On',        group: 'Controls' },
];

function computeAdvancedDefaults(colors) {
  const syn = deriveSyntaxColors(colors);
  const red = colors.red || '#e06c75';
  return {
    userBubbleBg: colors.bg,
    aiBubbleBg: colors.panel,
    bubbleBorder: colors.border,
    sidebarBg: colors.panel,
    brandColor: red,
    hamburgerColor: colors.fg,
    inputBg: colors.panel,
    inputBorder: colors.border,
    sendBtnBg: red,
    sendBtnHover: red,
    codeBg: syn.bg,
    codeFg: syn.fg,
    toggleActive: red,
  };
}

function generateHarmonyColors(accentHex, harmonyType, mode) {
  const [h, s] = hexToHSL(accentHex);
  const isDark = mode === 'dark';

  let bgH, bgS, bgL, fgS, fgL, panelL, borderH, borderS, borderL;

  if (harmonyType === 'complementary') {
    bgH = h; bgS = Math.max(s * 0.15, 3);
    bgL = isDark ? 13 : 95; fgL = isDark ? 85 : 15; fgS = Math.max(s * 0.2, 5);
    panelL = isDark ? 8 : 98;
    borderH = h; borderS = Math.max(s * 0.25, 8); borderL = isDark ? 28 : 75;
  } else if (harmonyType === 'analogous') {
    bgH = (h - 30 + 360) % 360; bgS = Math.max(s * 0.12, 3);
    bgL = isDark ? 14 : 95; fgL = isDark ? 84 : 18; fgS = Math.max(s * 0.15, 5);
    panelL = isDark ? 9 : 97;
    borderH = (h + 30) % 360; borderS = Math.max(s * 0.3, 10); borderL = isDark ? 30 : 72;
  } else if (harmonyType === 'triadic') {
    bgH = (h + 240) % 360; bgS = Math.max(s * 0.1, 2);
    bgL = isDark ? 13 : 96; fgL = isDark ? 86 : 14; fgS = Math.max(s * 0.18, 5);
    panelL = isDark ? 8 : 99;
    borderH = (h + 120) % 360; borderS = Math.max(s * 0.2, 8); borderL = isDark ? 28 : 74;
  } else { // monochromatic
    bgH = h; bgS = Math.max(s * 0.08, 2);
    bgL = isDark ? 12 : 96; fgL = isDark ? 87 : 13; fgS = Math.max(s * 0.15, 5);
    panelL = isDark ? 7 : 99;
    borderH = h; borderS = Math.max(s * 0.2, 6); borderL = isDark ? 26 : 76;
  }

  return {
    bg: hslToHex(bgH, bgS, bgL),
    fg: hslToHex(h, fgS, fgL),
    panel: hslToHex(bgH, bgS * 0.6, panelL),
    border: hslToHex(borderH, borderS, borderL),
    red: accentHex,
  };
}

export function applyColors(colors) {
  if (!colors || !colors.bg) return;
  const s = document.documentElement.style;
  s.setProperty('--bg', colors.bg);
  s.setProperty('--fg', colors.fg);
  s.setProperty('--panel', colors.panel);
  s.setProperty('--border', colors.border);
  if (colors.red) s.setProperty('--red', colors.red);

  // Derive and apply syntax highlighting colors
  const syn = deriveSyntaxColors(colors);
  s.setProperty('--hl-bg', syn.bg);
  s.setProperty('--hl-fg', syn.fg);
  s.setProperty('--hl-keyword', syn.keyword);
  s.setProperty('--hl-string', syn.string);
  s.setProperty('--hl-comment', syn.comment);
  s.setProperty('--hl-function', syn.function);
  s.setProperty('--hl-number', syn.number);
  s.setProperty('--hl-builtin', syn.builtin);
  s.setProperty('--hl-variable', syn.variable);
  s.setProperty('--hl-params', syn.params);

  // Apply advanced overrides (or defaults)
  const adv = colors.advanced || {};
  const defaults = computeAdvancedDefaults(colors);
  for (const { key, css } of ADV_KEYS) {
    s.setProperty(css, adv[key] || defaults[key]);
  }

  // Shared accent tokens for Todos, Calendar, chips, and focus highlights.
  const accentPrimary = adv.accentPrimary || colors.red || '#e06c75';
  const accentWarm = adv.accentWarm || syn.string || syn.number || accentPrimary;
  s.setProperty('--accent-primary', accentPrimary);
  s.setProperty('--accent', accentPrimary);
  s.setProperty('--accent-warm', accentWarm);
  if (adv.accentError) s.setProperty('--accent-error', adv.accentError);

  _applyProjectAccentTokens(s, syn.function, accentWarm, accentPrimary);

  // Keep the mobile browser toolbar / status bar matched to the theme bg
  // (same as the early head-script does on first paint).
  const _mtc = document.querySelector('meta[name="theme-color"]');
  if (_mtc && colors.bg) _mtc.setAttribute('content', colors.bg);
  _updateFavicon(colors.red || '#e06c75');
}

// Per-route SVG shape registry — kept in sync with the inline favicon
// script in index.html so a theme change keeps the route icon, not the
// default brand eye. Returns the inner SVG markup colored with `fg`.
const _ROUTE_FAVICON_SHAPES = {
  '/calendar':
    "<rect x='4' y='6' width='24' height='22' rx='2' fill='none' stroke='__C__' stroke-width='2.5'/>" +
    "<line x1='4' y1='12' x2='28' y2='12' stroke='__C__' stroke-width='2.5'/>" +
    "<line x1='10' y1='3' x2='10' y2='9' stroke='__C__' stroke-width='2.5' stroke-linecap='round'/>" +
    "<line x1='22' y1='3' x2='22' y2='9' stroke='__C__' stroke-width='2.5' stroke-linecap='round'/>",
  '/notes':
    "<rect x='6' y='4' width='20' height='24' rx='2' fill='none' stroke='__C__' stroke-width='2.5'/>" +
    "<line x1='10' y1='10' x2='22' y2='10' stroke='__C__' stroke-width='2'/>" +
    "<line x1='10' y1='15' x2='22' y2='15' stroke='__C__' stroke-width='2'/>" +
    "<line x1='10' y1='20' x2='18' y2='20' stroke='__C__' stroke-width='2'/>",
  '/cookbook':
    "<path d='M5 8 L5 26 A2 2 0 0 0 7 28 L25 28 A2 2 0 0 0 27 26 L27 8' fill='none' stroke='__C__' stroke-width='2.5' stroke-linejoin='round'/>" +
    "<path d='M9 4 L23 4 L23 8 L9 8 Z' fill='none' stroke='__C__' stroke-width='2.5' stroke-linejoin='round'/>" +
    "<line x1='11' y1='14' x2='21' y2='14' stroke='__C__' stroke-width='2'/>" +
    "<line x1='11' y1='19' x2='17' y2='19' stroke='__C__' stroke-width='2'/>",
  '/email':
    "<rect x='4' y='7' width='24' height='18' rx='2' fill='none' stroke='__C__' stroke-width='2.5'/>" +
    "<path d='M5 9 L16 17 L27 9' fill='none' stroke='__C__' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/>",
  '/memory':
    "<path d='M16 5 C10 5 6 9 6 14 C6 19 10 21 11 22 L11 26 L21 26 L21 22 C22 21 26 19 26 14 C26 9 22 5 16 5 Z' fill='none' stroke='__C__' stroke-width='2.5' stroke-linejoin='round'/>" +
    "<line x1='12' y1='28' x2='20' y2='28' stroke='__C__' stroke-width='2'/>",
  '/gallery':
    "<rect x='4' y='4' width='24' height='24' rx='2' fill='none' stroke='__C__' stroke-width='2.5'/>" +
    "<circle cx='12' cy='12' r='2.5' fill='__C__'/>" +
    "<path d='M4 22 L11 16 L18 21 L23 17 L28 22' fill='none' stroke='__C__' stroke-width='2.5' stroke-linejoin='round'/>",
  '/tasks':
    "<rect x='4' y='4' width='24' height='24' rx='3' fill='none' stroke='__C__' stroke-width='2.5'/>" +
    "<path d='M9 16 L14 21 L23 11' fill='none' stroke='__C__' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'/>",
  '/library':
    "<rect x='5' y='5' width='5' height='22' rx='1' fill='none' stroke='__C__' stroke-width='2.5'/>" +
    "<rect x='13' y='5' width='5' height='22' rx='1' fill='none' stroke='__C__' stroke-width='2.5'/>" +
    "<rect x='21' y='8' width='6' height='19' rx='1' fill='none' stroke='__C__' stroke-width='2.5' transform='rotate(8 24 17)'/>",
};

function _updateFavicon(fg) {
  const path = (window.location.pathname || '').toLowerCase();
  const routeShape = _ROUTE_FAVICON_SHAPES[path];
  let svg;
  if (routeShape) {
    svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>${routeShape.split('__C__').join(fg)}</svg>`;
  } else {
    svg = `<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><path d='M2.5 16C7 7.5 12.5 4.5 16 4.5s9 3 13.5 11.5C25 24.5 19.5 27.5 16 27.5S7 24.5 2.5 16z' fill='none' stroke='${fg}' stroke-width='2' stroke-linejoin='round'/><circle cx='16' cy='16' r='6.2' fill='none' stroke='${fg}' stroke-width='1.4'/><circle cx='16' cy='16' r='4' fill='${fg}'/><path d='M16 13.15c1.65.04 2.95 1.2 2.95 2.4 0 1.55-1.4 2.2-2.65 2.2-1.15 0-2.05-.55-2.05-1.4 0-.8.7-1.2 1.4-1.2.55 0 1 .28 1 .72' fill='none' stroke='#06060c' stroke-width='1.1' stroke-linecap='round'/><circle cx='16' cy='16' r='0.85' fill='#06060c'/></svg>`;
  }
  const href = 'data:image/svg+xml,' + encodeURIComponent(svg);
  let link = document.querySelector("link[rel='icon']");
  if (!link) {
    link = document.createElement('link');
    link.rel = 'icon';
    link.type = 'image/svg+xml';
    document.head.appendChild(link);
  }
  link.href = href;
  let apple = document.querySelector("link[rel='apple-touch-icon']");
  if (!apple) {
    apple = document.createElement('link');
    apple.rel = 'apple-touch-icon';
    document.head.appendChild(apple);
  }
  apple.href = href;
}

// Cache of discovered custom fonts: { "Family Name": [ {file, url, format} ] }
let _customFonts = {};
// Track which custom font families already have @font-face injected
const _injectedFonts = new Set();

function _injectFontFace(familyName, variants) {
  if (_injectedFonts.has(familyName)) return;
  const style = document.createElement('style');
  style.dataset.customFont = familyName;
  const fmtMap = { woff2: 'woff2', woff: 'woff', ttf: 'truetype', otf: 'opentype' };
  for (const v of variants) {
    style.textContent += `@font-face { font-family: '${familyName}'; src: url('${v.url}') format('${fmtMap[v.format] || v.format}'); font-display: swap; }\n`;
  }
  document.head.appendChild(style);
  _injectedFonts.add(familyName);
}

export function applyFontDensity(font, density) {
  const f = font || DEFAULT_FONT;
  const d = density || DEFAULT_DENSITY;
  let family = FONT_MAP[f];
  if (!family && _customFonts[f]) {
    // It's a custom font from the local folder
    _injectFontFace(f, _customFonts[f]);
    family = "'" + f + "', sans-serif";
  }
  if (!family) family = FONT_MAP[DEFAULT_FONT];
  document.documentElement.style.setProperty('--font-family', family);
  // Hint for CSS: mono theme fonts are narrower; proportional ones wrap on reading surfaces.
  const monoKeys = new Set(['mono', 'fira', 'jetbrains', 'roboto-mono']);
  document.documentElement.dataset.fontKind = monoKeys.has(f) ? 'mono' : 'proportional';
  document.documentElement.dataset.themeFont = f;
  document.documentElement.classList.remove('density-compact', 'density-spacious');
  if (d !== 'comfortable') document.documentElement.classList.add('density-' + d);
}

const _BG_CLASSES = ['bg-pattern-dots',
  'bg-pattern-synapse', 'bg-pattern-rain', 'bg-pattern-constellations',
  'bg-pattern-perlin-flow',
  'bg-pattern-petals', 'bg-pattern-sparkles', 'bg-pattern-embers',
  'bg-pattern-fireflies', 'bg-pattern-aurora', 'bg-pattern-paper-grain',
  'bg-pattern-ripple', 'bg-pattern-drift-grid', 'bg-pattern-orbit-rings',
  'bg-pattern-fog'];
const _CANVAS_PATTERNS = {
  synapse: _initSynapse, rain: _initRain, constellations: _initConstellations,
  'perlin-flow': _initPerlinFlow,
  petals: _initPetals, sparkles: _initSparkles, embers: _initEmbers,
  fireflies: _initFireflies, aurora: _initAurora, 'paper-grain': _initPaperGrain,
  ripple: _initRipple, 'drift-grid': _initDriftGrid, 'orbit-rings': _initOrbitRings,
  fog: _initFog,
};

export function applyBgEffectColor(color) {
  // Empty must remove the property — setting '' still counts as "set", so CSS
  // `var(--bg-effect-color, var(--fg))` would not fall back to --fg (breaks dots).
  if (color) document.documentElement.style.setProperty('--bg-effect-color', color);
  else document.documentElement.style.removeProperty('--bg-effect-color');
}

export function applyBgEffectIntensity(v) {
  // v is 0..1. Default 1 (full intensity) when missing.
  const n = (v === undefined || v === null || isNaN(v)) ? 1 : Math.max(0, Math.min(1, Number(v)));
  document.documentElement.style.setProperty('--bg-effect-intensity', String(n));
}

export function applyBgEffectSize(v) {
  // v is a multiplier 0.3..2.5. Default 1 when missing.
  const n = (v === undefined || v === null || isNaN(v)) ? 1 : Math.max(0.2, Math.min(3, Number(v)));
  document.documentElement.style.setProperty('--bg-effect-size', String(n));
}

/** Toggle the global "frosted glass" look — applies a translucent + blurred
 *  treatment to every panel, sidebar, modal, dropdown, and popover via CSS
 *  rules scoped to `body.theme-frosted`. */
export function applyFrostedGlass(on) {
  if (document.body) document.body.classList.toggle('theme-frosted', !!on);
  const s = document.documentElement.style;
  if (on) {
    s.setProperty('--project-glass-bg', 'color-mix(in srgb, var(--panel) 16%, transparent)');
    s.setProperty('--project-glass-blur', 'blur(28px) saturate(180%)');
  } else {
    s.removeProperty('--project-glass-bg');
    s.removeProperty('--project-glass-blur');
  }
}

/** Opt-in translucent window shells so theme bg effects show through.
 *  Scoped to `body.theme-glass` — off by default (backdrop-filter is costly). */
export function applyGlassWindows(on) {
  if (document.body) document.body.classList.toggle('theme-glass', !!on);
}

// Read current size / intensity for JS effects (canvas-based).
function _getEffectSize() {
  const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bg-effect-size'));
  return isNaN(v) ? 1 : v;
}
function _getEffectIntensity() {
  const v = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--bg-effect-intensity'));
  return isNaN(v) ? 1 : Math.max(0, Math.min(1, v));
}

// Patterns with no intensity/size controls (solid only).
const _STATIC_PATTERNS = new Set(['none']);

export function applyBgPattern(pattern) {
  const p = pattern || 'none';
  if (!document.body) return;
  document.body.classList.remove(..._BG_CLASSES);
  // Clean up any canvas backgrounds — detached canvases must stop via contains() check
  document.querySelectorAll('canvas[data-bg-effect]').forEach(c => c.remove());
  if (p !== 'none') document.body.classList.add('bg-pattern-' + p);
  if (_CANVAS_PATTERNS[p]) _CANVAS_PATTERNS[p]();
  // Hide sliders that do nothing on solid background.
  const hide = _STATIC_PATTERNS.has(p);
  const ig = document.getElementById('theme-bg-intensity-group');
  const sg = document.getElementById('theme-bg-size-group');
  if (ig) ig.style.display = hide ? 'none' : '';
  if (sg) sg.style.display = hide ? 'none' : '';
}

function _migrateThemeName(obj) {
  if (!obj || !obj.name) return obj;
  // Migration: 'chatgpt' preset was renamed to 'gpt'
  if (obj.name === 'chatgpt') obj.name = 'gpt';
  // Migration: 'sakura' preset was renamed to 'ume'
  if (obj.name === 'sakura') obj.name = 'ume';
  // Migration: legacy 'modus' → canonical Modus Operandi Tinted
  if (obj.name === 'modus') {
    obj.name = 'modus-operandi-tinted';
    if (THEMES['modus-operandi-tinted']) obj.colors = THEMES['modus-operandi-tinted'];
  }
  return obj;
}

export function getSaved() {
  const raw = Storage.getJSON(LS_KEY, null);
  if (!raw) return null;
  const prevName = raw.name;
  const obj = _migrateThemeName({ ...raw, colors: raw.colors });
  // Persist rename so the picker highlights the canonical swatch.
  if (obj && obj.name && obj.name !== prevName) {
    Storage.setJSON(LS_KEY, obj);
  }
  return obj;
}

export function save(name, colors, opts) {
  const obj = { name, colors };
  if (opts) {
    if (opts.font && opts.font !== DEFAULT_FONT) obj.font = opts.font;
    if (opts.density && opts.density !== DEFAULT_DENSITY) obj.density = opts.density;
    if (opts.bgPattern && opts.bgPattern !== 'none') obj.bgPattern = opts.bgPattern;
    if (opts.bgEffectColor) obj.bgEffectColor = opts.bgEffectColor;
    if (opts.bgEffectIntensity !== undefined && opts.bgEffectIntensity !== 1) obj.bgEffectIntensity = opts.bgEffectIntensity;
    if (opts.bgEffectSize !== undefined && opts.bgEffectSize !== 1) obj.bgEffectSize = opts.bgEffectSize;
    if (opts.frosted) obj.frosted = true;
    if (opts.glass) obj.glass = true;
  }
  Storage.setJSON(LS_KEY, obj);
  _syncToServer(obj);
}

function _syncToServer(obj) {
  try {
    fetch('/api/prefs/theme', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ value: obj }),
    }).catch(e => console.warn('Theme sync failed:', e));
  } catch (e) { console.warn('Theme sync error:', e); }
}

async function _loadFromServer() {
  try {
    const res = await fetch('/api/prefs/theme', { credentials: 'same-origin' });
    const data = await res.json();
    return data.value || null;
  } catch { return null; }
}


function syncPickers(colors) {
  if (!colors) return;
  const map = { bg: 'clr-bg', fg: 'clr-fg', panel: 'clr-panel', border: 'clr-border', red: 'clr-red' };
  for (const [key, id] of Object.entries(map)) {
    const el = document.getElementById(id);
    if (el && colors[key]) el.value = colors[key];
  }
  syncAdvancedPickers(colors);
}


function syncAdvancedPickers(colors) {
  const adv = colors.advanced || {};
  const defaults = computeAdvancedDefaults(colors);
  for (const { key } of ADV_KEYS) {
    const el = document.getElementById('adv-' + key);
    if (el) el.value = adv[key] || defaults[key];
  }
}

export function initThemeUI() {
  const themePopup = document.getElementById('theme-popup');
  const themeHeader = document.getElementById('theme-popup-header');
  if (themePopup && themeHeader && !themePopup.dataset.dragWired) {
    themePopup.dataset.dragWired = '1';
    makeDraggable(themePopup, themeHeader);
  }

  // Attach the in-house color picker to every color input in the theme panel.
  // Safe to call repeatedly — the picker marks inputs it's already wrapped.
  try { initColorPickers(document); } catch (e) { console.warn('Color picker init failed', e); }

  // Populate the advanced color inputs with their computed defaults right now.
  // BUG FIX: without this, untouched inputs sat at the browser-default `#000000`
  // until the user clicked a swatch; the first edit of ANY advanced input then
  // tripped readAdvanced() into storing every other `#000000` as an override —
  // e.g. editing Chat Bubble Border turned Sidebar Bg pure black.
  try {
    const saved = getSaved();
    if (saved && saved.colors) {
      syncAdvancedPickers(saved.colors);
    }
  } catch (e) { console.warn('syncAdvancedPickers on init failed', e); }
  // Wire up theme tabs (Themes / Customize)
  const themeTabs = document.getElementById('theme-tabs');
  if (themeTabs) {
    themeTabs.addEventListener('click', (e) => {
      const tab = e.target.closest('.admin-tab');
      if (!tab) return;
      const targetId = tab.dataset.tab;
      themeTabs.querySelectorAll('.admin-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      document.querySelectorAll('.theme-tab-panel').forEach(p => p.style.display = 'none');
      const panel = document.getElementById(targetId);
      if (panel) panel.style.display = '';
      // Show the opacity slider only on the Customize tab.
      const opWrap = document.getElementById('theme-opacity-wrap');
      if (opWrap) opWrap.classList.toggle('hidden', targetId !== 'theme-tab-customize');
      // Restore full opacity / blur on every other tab. The slider's effect
      // is meant to be Customize-only — peeking at the page while tweaking
      // colors — so swapping back to Themes (or Schedule) should look
      // exactly like the rest of the app's modals again.
      const popup = document.getElementById('theme-popup');
      if (popup) {
        if (targetId === 'theme-tab-customize') {
          // Reapply the Peek toggle's current state.
          if (opWrap && opWrap._apply) opWrap._apply();
        } else {
          popup.style.removeProperty('opacity');
          popup.style.removeProperty('background');
          popup.style.removeProperty('backdrop-filter');
          popup.style.removeProperty('-webkit-backdrop-filter');
          popup.querySelectorAll('.admin-card').forEach(c => {
            c.style.removeProperty('background');
            c.style.removeProperty('backdrop-filter');
            c.style.removeProperty('-webkit-backdrop-filter');
          });
        }
      }
    });
  }


  // Wire the "Peek" opacity toggle — fades the theme modal so the user can
  // see the page behind it while tweaking colors on the Customize tab.
  // On/off only (no slider); starts off, lives in the title bar, and is
  // cleared when the user swaps to Themes / Schedule.
  (function _wireOpacityToggle() {
    const toggle = document.getElementById('theme-opacity-wrap');
    const popup = document.getElementById('theme-popup');
    if (!toggle || !popup || toggle.dataset.bound === '1') return;
    toggle.dataset.bound = '1';
    const PEEK = 55; // % opacity when peeking
    const apply = (on) => {
      const cards = popup.querySelectorAll('.admin-card');
      if (on) {
        // Fade the modal + each inner card via color-mix — never element
        // opacity, so text, controls and swatches stay sharp.
        const bgMix    = `color-mix(in srgb, var(--bg)    ${PEEK}%, transparent)`;
        const panelMix = `color-mix(in srgb, var(--panel) ${PEEK}%, transparent)`;
        popup.style.setProperty('background', bgMix, 'important');
        popup.style.setProperty('backdrop-filter', 'none', 'important');
        popup.style.setProperty('-webkit-backdrop-filter', 'none', 'important');
        popup.style.removeProperty('opacity');
        cards.forEach(c => {
          c.style.setProperty('background', panelMix, 'important');
          c.style.setProperty('backdrop-filter', 'none', 'important');
          c.style.setProperty('-webkit-backdrop-filter', 'none', 'important');
        });
      } else {
        popup.style.removeProperty('opacity');
        popup.style.removeProperty('background');
        popup.style.removeProperty('backdrop-filter');
        popup.style.removeProperty('-webkit-backdrop-filter');
        cards.forEach(c => {
          c.style.removeProperty('background');
          c.style.removeProperty('backdrop-filter');
          c.style.removeProperty('-webkit-backdrop-filter');
        });
      }
    };
    // Expose so the tab-switch handler can reapply when returning to Customize.
    toggle._apply = () => apply(toggle.classList.contains('active'));
    toggle.addEventListener('click', () => {
      const on = !toggle.classList.contains('active');
      toggle.classList.toggle('active', on);
      toggle.setAttribute('aria-pressed', on ? 'true' : 'false');
      apply(on);
    });
  })();

  const grid = document.getElementById('themeGrid');
  if (!grid) return;

  const saved = getSaved();
  const activeName = saved ? saved.name : DEFAULT_THEME;
  const customThemes = _loadCustomThemes();

  // Render preset swatches (skip alias keys so Modus tinted isn't duplicated)
  grid.innerHTML = Object.entries(THEMES)
    .filter(([name]) => !THEME_ALIAS_KEYS.has(name))
    .map(([name, c]) => `
    <div class="theme-swatch${name === activeName ? ' active' : ''}" data-theme="${name}">
      <div class="theme-swatch-colors">
        <span style="background:${c.bg}"></span>
        <span style="background:${c.panel}"></span>
        <span style="background:${c.fg}"></span>
        <span style="background:${c.red}"></span>
      </div>
      ${THEME_LABELS[name] || name}
    </div>
  `).join('');

  // Render custom theme swatches into separate card
  const userGrid = document.getElementById('themeUserGrid');
  const userCard = document.getElementById('themeUserCard');
  const customEntries = Object.entries(customThemes);
  if (customEntries.length > 0 && userGrid && userCard) {
    userCard.style.display = '';
    userGrid.innerHTML = customEntries.map(([name, c]) => `
      <div class="theme-swatch${name === activeName ? ' active' : ''}" data-theme="${name}" data-custom="1">
        <div class="theme-swatch-colors">
          <span style="background:${c.bg}"></span>
          <span style="background:${c.panel}"></span>
          <span style="background:${c.fg}"></span>
          <span style="background:${c.red}"></span>
        </div>
        <span class="theme-swatch-name">${name}</span>
        <button type="button" class="theme-delete-btn" data-delete="${name}" title="Delete theme"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></button>
      </div>
    `).join('');
  } else if (userCard) {
    userCard.style.display = 'none';
  }

  // Helper: save with current font/density/bgPattern from UI selects
  function _getOpts() {
    const opts = {};
    const fs = document.getElementById('theme-font-select');
    const ds = document.getElementById('theme-density-select');
    const ps = document.getElementById('theme-bg-pattern-select');
    const ec = document.getElementById('theme-bg-effect-color');
    const es = document.getElementById('theme-bg-intensity');
    const sz = document.getElementById('theme-bg-size');
    if (fs) opts.font = fs.value;
    if (ds) opts.density = ds.value;
    if (ps) opts.bgPattern = ps.value;
    if (ec) opts.bgEffectColor = ec.value;
    if (es) opts.bgEffectIntensity = parseFloat(es.value) / 100;
    if (sz) opts.bgEffectSize = parseFloat(sz.value) / 100;
    const fr = document.getElementById('theme-frosted-toggle');
    if (fr) opts.frosted = !!fr.checked;
    const gl = document.getElementById('theme-glass-toggle');
    if (gl) opts.glass = !!gl.checked;
    return opts;
  }
  function _saveFull(name, colors) { save(name, colors, _getOpts()); }

  // Click handlers for all swatches (preset + custom) across both grids
  const allGrids = [grid, userGrid].filter(Boolean);
  function clearAllActive() { allGrids.forEach(g => g.querySelectorAll('.theme-swatch').forEach(s => s.classList.remove('active'))); }
  allGrids.forEach(g => {
    g.querySelectorAll('.theme-swatch').forEach(sw => {
      sw.addEventListener('click', (e) => {
        if (e.target.closest('.theme-delete-btn')) return;
        const name = sw.dataset.theme;
        const colors = sw.dataset.custom ? customThemes[name] : THEMES[name];
        if (!colors) return;
        applyColors(colors);
        clearAllActive();
        sw.classList.add('active');
        syncPickers(colors);
        const ct = sw.dataset.custom ? customThemes[name] : null;
        const f = ct && ct.font ? ct.font : DEFAULT_FONT;
        const d = ct && ct.density ? ct.density : DEFAULT_DENSITY;
        const p = ct && ct.bgPattern ? ct.bgPattern : (THEME_DEFAULT_PATTERN[name] || 'none');
        const ec = ct && ct.bgEffectColor ? ct.bgEffectColor : (THEME_DEFAULT_EFFECT_COLOR[name] || '');
        const ei = (ct && ct.bgEffectIntensity !== undefined) ? ct.bgEffectIntensity : (THEME_DEFAULT_INTENSITY[name] !== undefined ? THEME_DEFAULT_INTENSITY[name] : 1);
        const sz = (ct && ct.bgEffectSize !== undefined) ? ct.bgEffectSize : 1;
        const fr = (ct && ct.frosted !== undefined)
          ? !!ct.frosted
          : (THEME_DEFAULT_FROSTED[name] === true);
        const gl = (ct && ct.glass !== undefined) ? !!ct.glass : false;
        applyFontDensity(f, d);
        applyBgEffectColor(ec);
        applyBgEffectIntensity(ei);
        applyBgEffectSize(sz);
        applyFrostedGlass(fr);
        applyGlassWindows(gl);
        applyBgPattern(p);
        const fs = document.getElementById('theme-font-select');
        const ds = document.getElementById('theme-density-select');
        const ps = document.getElementById('theme-bg-pattern-select');
        const ecs = document.getElementById('theme-bg-effect-color');
        const eis = document.getElementById('theme-bg-intensity');
        const szs = document.getElementById('theme-bg-size');
        const frs = document.getElementById('theme-frosted-toggle');
        const gls = document.getElementById('theme-glass-toggle');
        if (fs) fs.value = f;
        if (ds) ds.value = d;
        if (ps) ps.value = p;
        if (ecs) ecs.value = ec || colors.fg || '#9cdef2';
        if (eis) eis.value = String(Math.round(ei * 100));
        if (szs) szs.value = String(Math.round(sz * 100));
        if (frs) frs.checked = fr;
        if (gls) gls.checked = gl;
        save(name, colors, { font: f, density: d, bgPattern: p, bgEffectColor: ec, bgEffectIntensity: ei, bgEffectSize: sz, frosted: fr, glass: gl });
      });
    });
    g.querySelectorAll('.theme-delete-btn').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const name = btn.dataset.delete;
        if (uiModule && uiModule.styledConfirm) {
          if (!await uiModule.styledConfirm(`Delete theme "${name}"?`, { confirmText: 'Delete', danger: true })) return;
        }
        deleteCustomTheme(name);
      });
    });
  });

  // Init color pickers from current theme and apply syntax colors
  const currentColors = saved ? saved.colors : THEMES[DEFAULT_THEME];
  applyColors(currentColors);
  syncPickers(currentColors);

  // Reference colors for per-picker reset (the theme you started from)
  const refName = saved ? saved.name : DEFAULT_THEME;
  const refColors = THEMES[refName] || customThemes[refName] || currentColors;
  const refDefaults = computeAdvancedDefaults(refColors);

  // Sync reset button visibility based on whether color differs from reference
  function syncResetButtons() {
    document.querySelectorAll('.color-reset-btn[data-reset]').forEach(btn => {
      const key = btn.dataset.reset;
      const picker = document.getElementById(pickerIds[key]);
      if (picker && refColors[key]) {
        btn.classList.toggle('changed', picker.value.toLowerCase() !== refColors[key].toLowerCase());
      }
    });
    document.querySelectorAll('.color-reset-btn[data-reset-adv]').forEach(btn => {
      const key = btn.dataset.resetAdv;
      const picker = document.getElementById('adv-' + key);
      const ref = refDefaults[key] || '';
      if (picker && ref) {
        btn.classList.toggle('changed', picker.value.toLowerCase() !== ref.toLowerCase());
      }
    });
  }

  // Color picker live updates.
  // NOTE: do NOT clone the input. attachColorPicker installed a value-getter
  // override + a mousedown handler on this exact element; cloning would orphan
  // both. Use a one-time bind flag instead.
  const pickerIds = { bg: 'clr-bg', fg: 'clr-fg', panel: 'clr-panel', border: 'clr-border', red: 'clr-red' };
  Object.entries(pickerIds).forEach(([key, id]) => {
    const el = document.getElementById(id);
    if (!el || el.dataset.themeBound === '1') return;
    el.dataset.themeBound = '1';
    el.addEventListener('input', () => {
      // Capture the OLD basic palette before we read the new picker values.
      // Used below to decide which advanced pickers carry a real user-set
      // override (value differs from the OLD computed default) vs. ones
      // that are just stale-default and should auto-refresh.
      const _oldColors = {};
      Object.entries(pickerIds).forEach(([k, pid]) => {
        // Picker value HAS already changed (input fired) for the one the
        // user touched. For that one, reading the current value gives the
        // NEW color, which is fine — _oldDefaults uses the rest. We use
        // computeAdvancedDefaults({...new}) once for the new defaults, and
        // the CSS variables for the OLD defaults.
      });
      const _rs = getComputedStyle(document.documentElement);
      _oldColors.bg     = (_rs.getPropertyValue('--bg')    || '').trim();
      _oldColors.fg     = (_rs.getPropertyValue('--fg')    || '').trim();
      _oldColors.panel  = (_rs.getPropertyValue('--panel') || '').trim();
      _oldColors.border = (_rs.getPropertyValue('--border')|| '').trim();
      _oldColors.red    = (_rs.getPropertyValue('--red')   || '').trim();
      const _oldDefaults = computeAdvancedDefaults(_oldColors);

      const colors = {};
      Object.entries(pickerIds).forEach(([k, pid]) => {
        colors[k] = document.getElementById(pid).value;
      });

      // Build the advanced override map: only pickers whose value differs
      // from the OLD default count as user-set. Untouched pickers (still
      // matching the old default) get auto-updated to the NEW default so
      // they keep tracking the basic palette (e.g. Send Btn follows Accent).
      const _newDefaults = computeAdvancedDefaults(colors);
      const _adv = {};
      let _hasAdv = false;
      // Normalize color strings to lowercase 6-char hex so getComputedStyle
      // values (which keep whatever was set — could be #abc, #ABCDEF, or
      // rgb()) compare correctly against color-input pickers (always
      // #rrggbb lowercase). Without this, every advanced picker reads as
      // "user-set" and we'd revert to the v161 bug.
      const _norm = (raw) => {
        let h = String(raw || '').trim().toLowerCase();
        if (!h) return '';
        // rgb(r,g,b) or rgba(r,g,b,a)
        const rgb = h.match(/^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
        if (rgb) {
          const hx = n => Math.max(0, Math.min(255, parseInt(n, 10))).toString(16).padStart(2, '0');
          return '#' + hx(rgb[1]) + hx(rgb[2]) + hx(rgb[3]);
        }
        if (h[0] !== '#') h = '#' + h;
        // Expand #rgb → #rrggbb
        if (/^#[0-9a-f]{3}$/.test(h)) {
          return '#' + h[1] + h[1] + h[2] + h[2] + h[3] + h[3];
        }
        return h;
      };
      for (const { key } of ADV_KEYS) {
        const pEl = document.getElementById('adv-' + key);
        if (!pEl) continue;
        if (_norm(pEl.value) !== _norm(_oldDefaults[key])) {
          _adv[key] = pEl.value;
          _hasAdv = true;
        } else {
          // Untouched — slide to the new default so it tracks the new palette.
          pEl.value = _newDefaults[key];
        }
      }
      if (_hasAdv) colors.advanced = _adv;
      applyColors(colors);
      // Auto-save: if the active theme is one of the user's custom themes,
      // route changes back into it so renaming/reloading keeps the edits.
      // Otherwise fall back to the transient 'custom' slot (existing behavior).
      const _activeSaved = getSaved();
      const _activeName = _activeSaved && _activeSaved.name;
      const _customMap = _loadCustomThemes();
      if (_activeName && _customMap && _customMap[_activeName]) {
        // Preserve advanced/opts keys that aren't part of basic colors.
        saveCustomTheme(_activeName, colors, {
          font: _activeSaved.font, density: _activeSaved.density,
          bgPattern: _activeSaved.bgPattern, bgEffectColor: _activeSaved.bgEffectColor,
          bgEffectIntensity: _activeSaved.bgEffectIntensity,
          bgEffectSize: _activeSaved.bgEffectSize,
        });
        _saveFull(_activeName, colors);
      } else {
        _saveFull('custom', colors);
      }
      _flashAutosaved();
      grid.querySelectorAll('.theme-swatch').forEach(s => s.classList.remove('active'));
      syncResetButtons();
    });
  });

  // Save custom theme — inline input
  const saveNameInputOld = document.getElementById('theme-save-name');
  const saveGoBtnOld = document.getElementById('theme-save-go');
  const saveError = document.getElementById('theme-save-error');
  if (saveGoBtnOld && saveNameInputOld) {
    const newGoBtn = saveGoBtnOld.cloneNode(true);
    saveGoBtnOld.parentNode.replaceChild(newGoBtn, saveGoBtnOld);
    const newNameInput = saveNameInputOld.cloneNode(true);
    saveNameInputOld.parentNode.replaceChild(newNameInput, saveNameInputOld);
    const doSave = () => {
      saveError.style.display = 'none';
      const name = newNameInput.value.trim();
      if (!name) { saveError.textContent = 'Enter a name.'; saveError.style.display = 'block'; return; }
      const slug = name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
      if (!slug) { saveError.textContent = 'Invalid name.'; saveError.style.display = 'block'; return; }
      if (THEMES[slug]) { saveError.textContent = 'Cannot overwrite a built-in theme.'; saveError.style.display = 'block'; return; }
      const colors = {};
      const pickerIds2 = { bg: 'clr-bg', fg: 'clr-fg', panel: 'clr-panel', border: 'clr-border', red: 'clr-red' };
      Object.entries(pickerIds2).forEach(([k, pid]) => { colors[k] = document.getElementById(pid).value; });
      const adv = {};
      const defaults = computeAdvancedDefaults(colors);
      let hasAdv = false;
      for (const { key } of ADV_KEYS) {
        const el = document.getElementById('adv-' + key);
        if (el && el.value !== defaults[key]) { adv[key] = el.value; hasAdv = true; }
      }
      if (hasAdv) colors.advanced = adv;
      const opts = _getOpts();
      const result = saveCustomTheme(slug, colors, opts);
      if (result === 'limit') { saveError.textContent = 'Max ' + MAX_CUSTOM_THEMES + ' custom themes. Delete one first.'; saveError.style.display = 'block'; return; }
      save(slug, colors, opts);
      newNameInput.value = '';
      _flashAutosaved('Theme saved');
      uiModule.showToast?.('Theme saved');
      const prevHtml = newGoBtn.innerHTML;
      newGoBtn.disabled = true;
      newGoBtn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg><span>Saved</span>';
      setTimeout(() => {
        newGoBtn.disabled = false;
        newGoBtn.innerHTML = prevHtml;
      }, 1200);
    };
    newGoBtn.addEventListener('click', doSave);
    newNameInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') doSave(); });
  }

  // Reset button
  const resetBtn = document.getElementById('theme-reset-btn');
  if (resetBtn) {
    const newReset = resetBtn.cloneNode(true);
    resetBtn.parentNode.replaceChild(newReset, resetBtn);
    newReset.addEventListener('click', () => {
      Storage.remove(LS_KEY);
      const colors = THEMES[DEFAULT_THEME];
      const defaultPattern = THEME_DEFAULT_PATTERN[DEFAULT_THEME] || 'none';
      // Persist + sync so the next load (and other devices) keep Modus instead
      // of re-hydrating a stale server theme after localStorage was cleared.
      save(DEFAULT_THEME, colors, {
        font: DEFAULT_FONT,
        density: DEFAULT_DENSITY,
        bgPattern: defaultPattern,
        bgEffectColor: THEME_DEFAULT_EFFECT_COLOR[DEFAULT_THEME] || '',
        bgEffectIntensity: THEME_DEFAULT_INTENSITY[DEFAULT_THEME] ?? 1,
        bgEffectSize: 1,
        frosted: THEME_DEFAULT_FROSTED[DEFAULT_THEME] === true,
        glass: false,
      });
      applyColors(colors);
      syncPickers(colors);
      applyFontDensity(DEFAULT_FONT, DEFAULT_DENSITY);
      applyBgEffectColor(THEME_DEFAULT_EFFECT_COLOR[DEFAULT_THEME] || '');
      applyBgEffectIntensity(THEME_DEFAULT_INTENSITY[DEFAULT_THEME] ?? 1);
      applyBgEffectSize(1);
      applyFrostedGlass(THEME_DEFAULT_FROSTED[DEFAULT_THEME] === true);
      applyGlassWindows(false);
      applyBgPattern(defaultPattern);
      const fs = document.getElementById('theme-font-select');
      const ds = document.getElementById('theme-density-select');
      const ps = document.getElementById('theme-bg-pattern-select');
      const frs = document.getElementById('theme-frosted-toggle');
      const gls = document.getElementById('theme-glass-toggle');
      if (fs) fs.value = DEFAULT_FONT;
      if (ds) ds.value = DEFAULT_DENSITY;
      if (ps) ps.value = defaultPattern;
      if (frs) frs.checked = THEME_DEFAULT_FROSTED[DEFAULT_THEME] === true;
      if (gls) gls.checked = false;
      grid.querySelectorAll('.theme-swatch').forEach(s => s.classList.remove('active'));
      const defaultSwatch = grid.querySelector(`[data-theme="${DEFAULT_THEME}"]`);
      if (defaultSwatch) defaultSwatch.classList.add('active');
    });
  }

  // Advanced section toggle
  const advToggle = document.getElementById('theme-adv-toggle');
  const advSection = document.getElementById('themeAdvanced');
  if (advToggle && advSection) {
    const newToggle = advToggle.cloneNode(true);
    advToggle.parentNode.replaceChild(newToggle, advToggle);
    newToggle.addEventListener('click', () => {
      advSection.classList.toggle('hidden');
      newToggle.classList.toggle('open');
      // Re-scan rows so advanced color inputs get the hover-highlight too.
      const root = document.getElementById('theme-tab-customize');
      if (root) root.dataset.zoneBound = '';
      initThemeZoneHighlight();
    });
  }
  // Wire hover-highlights on color rows so the user sees which UI zone
  // each input edits.
  initThemeZoneHighlight();

  // Advanced color picker live updates
  function readCurrentColors() {
    const pickerIds2 = { bg: 'clr-bg', fg: 'clr-fg', panel: 'clr-panel', border: 'clr-border', red: 'clr-red' };
    const c = {};
    Object.entries(pickerIds2).forEach(([k, pid]) => { c[k] = document.getElementById(pid).value; });
    return c;
  }

  function readAdvanced() {
    const adv = {};
    const base = readCurrentColors();
    const defaults = computeAdvancedDefaults(base);
    let hasOverrides = false;
    for (const { key } of ADV_KEYS) {
      const el = document.getElementById('adv-' + key);
      if (!el) continue;
      const v = (el.value || '').toLowerCase();
      // Skip empty or never-populated inputs so we don't accidentally store
      // them as overrides (and then write '#000000' to the CSS var).
      if (!v || !/^#[0-9a-f]{6}$/.test(v)) continue;
      if (v !== (defaults[key] || '').toLowerCase()) {
        adv[key] = el.value;
        hasOverrides = true;
      }
    }
    return hasOverrides ? adv : undefined;
  }

  for (const { key } of ADV_KEYS) {
    const el = document.getElementById('adv-' + key);
    if (!el || el.dataset.themeBound === '1') continue;
    el.dataset.themeBound = '1';
    el.addEventListener('input', () => {
      const base = readCurrentColors();
      base.advanced = readAdvanced();
      applyColors(base);
      // Same auto-save routing as the basic color inputs above — write
      // to the active custom theme if there is one, else fall back to
      // the transient 'custom' slot.
      const _activeSaved = getSaved();
      const _activeName = _activeSaved && _activeSaved.name;
      const _customMap = _loadCustomThemes();
      if (_activeName && _customMap && _customMap[_activeName]) {
        saveCustomTheme(_activeName, base, {
          font: _activeSaved.font, density: _activeSaved.density,
          bgPattern: _activeSaved.bgPattern, bgEffectColor: _activeSaved.bgEffectColor,
          bgEffectIntensity: _activeSaved.bgEffectIntensity,
          bgEffectSize: _activeSaved.bgEffectSize,
        });
        _saveFull(_activeName, base);
      } else {
        _saveFull('custom', base);
      }
      _flashAutosaved();
      grid.querySelectorAll('.theme-swatch').forEach(s => s.classList.remove('active'));
      syncResetButtons();
    });
  }

  // Clear advanced overrides button
  const advClearBtn = document.getElementById('theme-adv-clear');
  if (advClearBtn) {
    const newClear = advClearBtn.cloneNode(true);
    advClearBtn.parentNode.replaceChild(newClear, advClearBtn);
    newClear.addEventListener('click', () => {
      const base = readCurrentColors();
      delete base.advanced;
      applyColors(base);
      _saveFull('custom', base);
      syncAdvancedPickers(base);
      syncResetButtons();
    });
  }

  // Per-picker reset buttons (base colors)
  document.querySelectorAll('.color-reset-btn[data-reset]').forEach(btn => {
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener('click', () => {
      const key = newBtn.dataset.reset;
      const picker = document.getElementById(pickerIds[key]);
      if (picker && refColors[key]) {
        picker.value = refColors[key];
        picker.dispatchEvent(new Event('input'));
      }
    });
  });

  // Effect color reset button
  document.querySelectorAll('.color-reset-btn[data-reset-effect]').forEach(btn => {
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener('click', () => {
      const ec = document.getElementById('theme-bg-effect-color');
      if (ec) {
        const fg = currentColors.fg || '#9cdef2';
        ec.value = fg;
        applyBgEffectColor('');
        const s = getSaved(); if (s) _saveFull(s.name, s.colors);
      }
    });
  });

  // Per-picker reset buttons (advanced colors)
  document.querySelectorAll('.color-reset-btn[data-reset-adv]').forEach(btn => {
    const newBtn = btn.cloneNode(true);
    btn.parentNode.replaceChild(newBtn, btn);
    newBtn.addEventListener('click', () => {
      const key = newBtn.dataset.resetAdv;
      const picker = document.getElementById('adv-' + key);
      if (picker) {
        picker.value = refDefaults[key] || computeAdvancedDefaults(refColors)[key];
        picker.dispatchEvent(new Event('input'));
      }
    });
  });

  // Initial sync of reset button visibility
  syncResetButtons();

  // Font, density, background pattern controls
  const _initFont = (saved && saved.font) || DEFAULT_FONT;
  const _initDensity = (saved && saved.density) || DEFAULT_DENSITY;
  const _initPattern = (saved && saved.bgPattern)
    || THEME_DEFAULT_PATTERN[(saved && saved.name) || DEFAULT_THEME]
    || 'none';
  const _initEffectColor = (saved && saved.bgEffectColor)
    || THEME_DEFAULT_EFFECT_COLOR[(saved && saved.name) || DEFAULT_THEME]
    || '';
  const _initEffectIntensity = (saved && saved.bgEffectIntensity !== undefined)
    ? saved.bgEffectIntensity
    : (THEME_DEFAULT_INTENSITY[(saved && saved.name) || DEFAULT_THEME] !== undefined
        ? THEME_DEFAULT_INTENSITY[(saved && saved.name) || DEFAULT_THEME]
        : 1);
  const _initEffectSize = (saved && saved.bgEffectSize !== undefined) ? saved.bgEffectSize : 1;
  const _initFrosted = (saved && saved.frosted !== undefined)
    ? !!saved.frosted
    : (THEME_DEFAULT_FROSTED[(saved && saved.name) || DEFAULT_THEME] === true);
  const _initGlass = (saved && saved.glass !== undefined) ? !!saved.glass : false;
  applyFontDensity(_initFont, _initDensity);
  applyBgEffectColor(_initEffectColor);
  applyBgEffectIntensity(_initEffectIntensity);
  applyBgEffectSize(_initEffectSize);
  applyFrostedGlass(_initFrosted);
  applyGlassWindows(_initGlass);
  applyBgPattern(_initPattern);

  const fontSelect = document.getElementById('theme-font-select');
  const densitySelect = document.getElementById('theme-density-select');
  const patternSelect = document.getElementById('theme-bg-pattern-select');

  if (fontSelect) {
    const nf = fontSelect.cloneNode(true); fontSelect.parentNode.replaceChild(nf, fontSelect);
    nf.value = _initFont;
    nf.addEventListener('change', () => {
      applyFontDensity(nf.value, document.getElementById('theme-density-select').value);
      const s = getSaved(); if (s) _saveFull(s.name, s.colors);
    });
    // Fetch custom fonts from local folder and populate dropdown
    fetch('/api/fonts/custom', { credentials: 'same-origin' })
      .then(r => r.json())
      .then(data => {
        _customFonts = data.fonts || {};
        const families = Object.keys(_customFonts);
        nf.querySelectorAll('option[data-custom-font]').forEach(o => o.remove());
        for (const fam of families) {
          const opt = document.createElement('option');
          opt.value = fam;
          opt.textContent = fam;
          opt.dataset.customFont = '1';
          nf.appendChild(opt);
        }
        // Restore saved value after options are populated
        nf.value = _initFont;
      })
      .catch(e => console.warn('Custom fonts fetch failed:', e));
  }
  if (densitySelect) {
    const nd = densitySelect.cloneNode(true); densitySelect.parentNode.replaceChild(nd, densitySelect);
    nd.value = _initDensity;
    nd.addEventListener('change', () => {
      applyFontDensity(document.getElementById('theme-font-select').value, nd.value);
      const s = getSaved(); if (s) _saveFull(s.name, s.colors);
    });
  }
  if (patternSelect) {
    const np = patternSelect.cloneNode(true); patternSelect.parentNode.replaceChild(np, patternSelect);
    np.value = _initPattern;
    np.addEventListener('change', () => {
      applyBgPattern(np.value);
      const s = getSaved(); if (s) _saveFull(s.name, s.colors);
    });
  }

  const effectColorPicker = document.getElementById('theme-bg-effect-color');
  if (effectColorPicker) {
    effectColorPicker.value = _initEffectColor || currentColors.fg || '#9cdef2';
    effectColorPicker.addEventListener('input', () => {
      applyBgEffectColor(effectColorPicker.value);
      const s = getSaved(); if (s) _saveFull(s.name, s.colors);
    });
  }

  const intensitySlider = document.getElementById('theme-bg-intensity');
  if (intensitySlider) {
    intensitySlider.value = String(Math.round(_initEffectIntensity * 100));
    intensitySlider.addEventListener('input', () => {
      applyBgEffectIntensity(parseFloat(intensitySlider.value) / 100);
      const s = getSaved(); if (s) _saveFull(s.name, s.colors);
    });
  }

  const sizeSlider = document.getElementById('theme-bg-size');
  if (sizeSlider) {
    sizeSlider.value = String(Math.round(_initEffectSize * 100));
    sizeSlider.addEventListener('input', () => {
      applyBgEffectSize(parseFloat(sizeSlider.value) / 100);
      const s = getSaved(); if (s) _saveFull(s.name, s.colors);
    });
  }

  const frostedToggle = document.getElementById('theme-frosted-toggle');
  if (frostedToggle) {
    frostedToggle.checked = _initFrosted;
    frostedToggle.addEventListener('change', () => {
      applyFrostedGlass(frostedToggle.checked);
      const s = getSaved(); if (s) _saveFull(s.name, s.colors);
    });
  }

  const glassToggle = document.getElementById('theme-glass-toggle');
  if (glassToggle) {
    glassToggle.checked = _initGlass;
    glassToggle.addEventListener('change', () => {
      applyGlassWindows(glassToggle.checked);
      const s = getSaved(); if (s) _saveFull(s.name, s.colors);
    });
  }

  // --- Color Harmony Generator (inside Advanced section) ---
  const harmonyGenBtnEl = document.getElementById('harmony-generate-btn');
  const harmonyAccentEl = document.getElementById('harmony-accent');
  // Make sure the in-house color picker really attached to this one. The
  // global initColorPickers() call earlier in initThemeUI should have grabbed
  // it, but in older sessions / partial loads it sometimes wasn't wrapped —
  // call attachColorPicker idempotently so the popover, suggestions, recents
  // and hex syncing all match every other color row.
  if (harmonyAccentEl) {
    try { attachColorPicker(harmonyAccentEl); } catch (_) {}
  }
  // Keep the hex display chip in sync with whatever the picker reports.
  const _harmonyHex = document.getElementById('harmony-accent-hex');
  if (harmonyAccentEl && _harmonyHex) {
    _harmonyHex.textContent = harmonyAccentEl.value || '#e06c75';
    harmonyAccentEl.addEventListener('input', () => {
      _harmonyHex.textContent = harmonyAccentEl.value;
    });
  }
  if (harmonyGenBtnEl) {
    const newGen = harmonyGenBtnEl.cloneNode(true);
    harmonyGenBtnEl.parentNode.replaceChild(newGen, harmonyGenBtnEl);
    newGen.addEventListener('click', () => {
      const accent = document.getElementById('harmony-accent').value;
      const type = document.getElementById('harmony-type').value;
      const mode = document.getElementById('harmony-mode').value;
      const colors = generateHarmonyColors(accent, type, mode);
      applyColors(colors);
      syncPickers(colors);
      _saveFull('custom', colors);
      grid.querySelectorAll('.theme-swatch').forEach(s => s.classList.remove('active'));
      const prev = document.getElementById('harmony-preview');
      if (prev) prev.innerHTML = [colors.bg, colors.panel, colors.fg, colors.border, colors.red].map(c => `<span style="background:${c}"></span>`).join('');
    });
  }
  if (harmonyAccentEl) {
    const newAcc = harmonyAccentEl.cloneNode(true);
    harmonyAccentEl.parentNode.replaceChild(newAcc, harmonyAccentEl);
    // Re-attach the in-house color picker to the fresh clone. cloneNode
    // copies the data-cp-attached="1" flag but NOT the listeners, so we
    // have to clear the flag first or attachColorPicker bails as a no-op.
    delete newAcc.dataset.cpAttached;
    newAcc.type = 'color'; // clone may have been type=text from prior attach
    try { attachColorPicker(newAcc); } catch (_) {}
    newAcc.addEventListener('input', () => {
      const type = document.getElementById('harmony-type').value;
      const mode = document.getElementById('harmony-mode').value;
      const colors = generateHarmonyColors(newAcc.value, type, mode);
      const prev = document.getElementById('harmony-preview');
      if (prev) prev.innerHTML = [colors.bg, colors.panel, colors.fg, colors.border, colors.red].map(c => `<span style="background:${c}"></span>`).join('');
      // Sync the hex chip beside the picker.
      const hex = document.getElementById('harmony-accent-hex');
      if (hex) hex.textContent = newAcc.value;
    });
  }

  // --- Import / Export ---
  const exportBtnEl = document.getElementById('theme-export-btn');
  const importBtnEl = document.getElementById('theme-import-btn');
  const importAreaEl = document.getElementById('theme-import-area');
  const importActionsEl = document.getElementById('theme-import-actions');
  const importGoEl = document.getElementById('theme-import-go');
  const importCancelEl = document.getElementById('theme-import-cancel');

  if (exportBtnEl) {
    const newExp = exportBtnEl.cloneNode(true);
    exportBtnEl.parentNode.replaceChild(newExp, exportBtnEl);
    newExp.addEventListener('click', () => {
      const colors = readCurrentColors();
      const adv = readAdvanced();
      if (adv) colors.advanced = adv;
      const cur = getSaved();
      const obj = { name: cur ? cur.name : 'custom', colors };
      if (cur && cur.font) obj.font = cur.font;
      if (cur && cur.density) obj.density = cur.density;
      if (cur && cur.bgPattern) obj.bgPattern = cur.bgPattern;
      if (cur && cur.bgEffectColor) obj.bgEffectColor = cur.bgEffectColor;
      const json = JSON.stringify(obj, null, 2);
      const blob = new Blob([json], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'nobody_' + (obj.name || 'theme') + '.json';
      a.click();
      URL.revokeObjectURL(url);
      newExp.innerHTML = '&#x2713; Downloaded!';
      setTimeout(() => { newExp.innerHTML = '&#x2913; Export'; }, 1500);
    });
  }

  if (importBtnEl && importAreaEl && importActionsEl) {
    const newImp = importBtnEl.cloneNode(true);
    importBtnEl.parentNode.replaceChild(newImp, importBtnEl);
    newImp.addEventListener('click', () => {
      importAreaEl.classList.toggle('hidden');
      importActionsEl.classList.toggle('hidden');
      importAreaEl.value = '';
      saveError.style.display = 'none';
    });
  }

  if (importGoEl && importAreaEl) {
    const newGo = importGoEl.cloneNode(true);
    importGoEl.parentNode.replaceChild(newGo, importGoEl);
    newGo.addEventListener('click', () => {
      saveError.style.display = 'none';
      let parsed;
      try { parsed = JSON.parse(importAreaEl.value.trim()); }
      catch { saveError.textContent = 'Invalid JSON.'; saveError.style.display = 'block'; return; }
      let colors = parsed.colors || parsed;
      const name = parsed.name || 'imported';
      const required = ['bg', 'fg', 'panel', 'border', 'red'];
      const missing = required.filter(k => !colors[k]);
      if (missing.length) { saveError.textContent = 'Missing: ' + missing.join(', '); saveError.style.display = 'block'; return; }
      const hexRe = /^#[0-9a-fA-F]{6}$/;
      for (const k of required) {
        if (!hexRe.test(colors[k])) { saveError.textContent = 'Bad hex for ' + k; saveError.style.display = 'block'; return; }
      }
      const colorData = { bg: colors.bg, fg: colors.fg, panel: colors.panel, border: colors.border, red: colors.red };
      if (colors.advanced && typeof colors.advanced === 'object') colorData.advanced = colors.advanced;
      const slug = name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '') || 'imported';
      const opts = {};
      if (parsed.font) opts.font = parsed.font;
      if (parsed.density) opts.density = parsed.density;
      if (parsed.bgPattern) opts.bgPattern = parsed.bgPattern;
      if (parsed.bgEffectColor) opts.bgEffectColor = parsed.bgEffectColor;
      const result = saveCustomTheme(slug, colorData, opts);
      if (result === 'limit') { saveError.textContent = 'Max ' + MAX_CUSTOM_THEMES + ' custom themes. Delete one first.'; saveError.style.display = 'block'; return; }
      save(slug, colorData, opts);
      applyColors(colorData);
      applyFontDensity(opts.font || DEFAULT_FONT, opts.density || DEFAULT_DENSITY);
      applyBgEffectColor(opts.bgEffectColor || '');
      applyBgPattern(opts.bgPattern || 'none');
      importAreaEl.classList.add('hidden');
      importActionsEl.classList.add('hidden');
    });
  }

  if (importCancelEl && importAreaEl && importActionsEl) {
    const newCancel = importCancelEl.cloneNode(true);
    importCancelEl.parentNode.replaceChild(newCancel, importCancelEl);
    newCancel.addEventListener('click', () => {
      importAreaEl.classList.add('hidden');
      importActionsEl.classList.add('hidden');
      importAreaEl.value = '';
      saveError.style.display = 'none';
    });
  }

  // Theme popup now uses standard modal frame (not draggable)
}

// ── Zone highlighter ───────────────────────────────────────────────────
// Maps each color input id to a selector for the part of the UI it affects.
// When the user hovers the color row, we overlay a translucent box on the
// matching elements so it's obvious what's being edited.
const _THEME_ZONE_MAP = {
  'clr-bg':            'body',
  'clr-fg':            '.msg .body, .chat-input-bar',
  'clr-panel':         '.sidebar',
  'clr-border':        '.chat-input-bar, .sidebar, .msg .body',
  'clr-red':           '.send-btn, .icon-rail-btn.active',
  'theme-bg-effect-color': 'body',
  'adv-userBubbleBg':  '.msg.msg-user .body',
  'adv-aiBubbleBg':    '.msg.msg-ai .body',
  'adv-bubbleBorder':  '.msg .body',
  'adv-sidebarBg':     '.sidebar',
  'adv-sectionAccent': '.sidebar h4',
  'adv-brandColor':    '#sidebar-brand-btn',
  'adv-inputBg':       '#message',
  'adv-inputBorder':   '.chat-input-bar',
  'adv-sendBtnBg':     '.send-btn',
  'adv-sendBtnHover':  '.send-btn',
  'adv-codeBg':        'pre, code',
  'adv-codeFg':        'pre code, p code',
  'adv-toggleBg':      '.mode-toggle, .admin-switch',
  'adv-toggleActive':  '.mode-toggle-btn.active, .admin-switch input:checked + .admin-slider',
  'adv-accentPrimary': '.send-btn, .icon-rail-btn.active',
  'adv-accentError':   '.toast.error',
};

function _showThemeZoneHighlight(selector) {
  _clearThemeZoneHighlight();
  if (!selector) return;
  let els;
  try { els = document.querySelectorAll(selector); }
  catch { return; }
  els.forEach(el => {
    // Skip elements inside the theme modal — highlighting itself is noise.
    if (el.closest && el.closest('#theme-modal')) return;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    const overlay = document.createElement('div');
    overlay.className = 'theme-zone-highlight';
    overlay.style.top    = (r.top - 2) + 'px';
    overlay.style.left   = (r.left - 2) + 'px';
    overlay.style.width  = (r.width + 4) + 'px';
    overlay.style.height = (r.height + 4) + 'px';
    document.body.appendChild(overlay);
  });
}

function _clearThemeZoneHighlight() {
  document.querySelectorAll('.theme-zone-highlight').forEach(el => el.remove());
}

let _flashTimer = null;
function _flashAutosaved(label = 'Auto-saved') {
  let pill = document.getElementById('theme-autosaved-pill');
  if (!pill) {
    pill = document.createElement('div');
    pill.id = 'theme-autosaved-pill';
    pill.className = 'theme-autosaved-pill';
    pill.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg><span></span>';
    // Anchor inside the customize tab so it floats with the form.
    const customizeTab = document.getElementById('theme-tab-customize');
    (customizeTab || document.body).appendChild(pill);
  }
  const labelEl = pill.querySelector('span');
  if (labelEl) labelEl.textContent = label;
  pill.classList.add('visible');
  clearTimeout(_flashTimer);
  _flashTimer = setTimeout(() => pill.classList.remove('visible'), 1100);
}

// Wire hover-to-highlight on every color row inside the theme modal. Call
// once after the modal markup is in the DOM. Idempotent.
export function initThemeZoneHighlight() {
  const root = document.getElementById('theme-tab-customize');
  if (!root || root.dataset.zoneBound === '1') return;
  root.dataset.zoneBound = '1';
  root.querySelectorAll('.color-row').forEach(row => {
    const input = row.querySelector('input[type="color"]');
    if (!input) return;
    const sel = _THEME_ZONE_MAP[input.id];
    if (!sel) return;
    row.addEventListener('mouseenter', () => _showThemeZoneHighlight(sel));
    row.addEventListener('mouseleave', _clearThemeZoneHighlight);
    // Also trigger when the picker actually opens (input focus)
    input.addEventListener('focus', () => _showThemeZoneHighlight(sel));
    input.addEventListener('blur', _clearThemeZoneHighlight);
  });
  // Clear highlight when the modal closes.
  const modal = document.getElementById('theme-modal');
  if (modal) {
    new MutationObserver(() => {
      if (modal.classList.contains('hidden')) _clearThemeZoneHighlight();
    }).observe(modal, { attributes: true, attributeFilter: ['class'] });
  }
}

// Generic draggable helper for fixed-position elements
// Thin wrapper around the shared makeWindowDraggable helper. Existing
// callers pass (el, handle) — `el` is what gets moved, `handle` is the
// drag handle. No fullscreen support (none of these consumers wanted it).
export function makeDraggable(el, handle) {
  if (!el || !handle) return;
  const dockTarget = (el.closest && el.closest('.modal')) || el;
  const dragOptions = {
    content: el,
    header: handle,
    // Don't start a window-drag when the user grabs an interactive control
    // in the header — e.g. the theme opacity slider now lives next to the
    // title, and dragging its thumb must move the slider, not the window.
    skipSelector: 'button, input, select, .theme-opacity-wrap',
  };
  if (dockTarget && dockTarget.id === 'theme-modal') {
    dragOptions.onEnterFullscreen = () => {
      snapModalToZone(dockTarget, {
        name: 'fullscreen',
        rect: {
          left: 0,
          top: 0,
          width: window.innerWidth || document.documentElement.clientWidth || 0,
          height: window.innerHeight || document.documentElement.clientHeight || 0,
        },
      });
    };
  }
  makeWindowDraggable(dockTarget, dragOptions);
}

// Toggle the popup
export function togglePopup() {
  const modal = document.getElementById('theme-modal');
  if (!modal) return;
  const visible = !modal.classList.contains('hidden');
  if (visible) {
    modal.classList.add('hidden');
  } else {
    modal.classList.remove('hidden');
  }
}

export function closePopup() {
  const modal = document.getElementById('theme-modal');
  if (!modal) return;
  const content = modal.querySelector('.modal-content');
  if (content && !content.classList.contains('modal-closing')) {
    content.classList.add('modal-closing');
    content.addEventListener('animationend', () => {
      modal.classList.add('hidden');
      content.classList.remove('modal-closing');
    }, { once: true });
    setTimeout(() => { if (!modal.classList.contains('hidden')) { modal.classList.add('hidden'); content.classList.remove('modal-closing'); } }, 250);
  } else {
    modal.classList.add('hidden');
  }
}

// Expose for app.js wiring + AI ui_control
export function getCustomThemes() { return _loadCustomThemes(); }

// ── Canvas bg-effect lifecycle ──
// applyBgPattern removes canvases then may re-add the same pattern class before
// the previous rAF fires. Checking only the class would keep orphaned loops
// painting detached canvases (memory leak). Always require contains(canvas).
function _mountBgCanvas(id) {
  if (document.getElementById(id)) return null;
  const canvas = document.createElement('canvas');
  canvas.id = id;
  canvas.dataset.bgEffect = '1';
  canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  return canvas;
}
function _bgEffectColor(fallback) {
  const s = getComputedStyle(document.documentElement);
  return s.getPropertyValue('--bg-effect-color').trim()
    || s.getPropertyValue('--fg').trim()
    || fallback
    || '#9cdef2';
}
function _bgRgba(hex, a) {
  const { r, g, b } = hexToRgb(hex) || { r: 0, g: 0, b: 0 };
  return `rgba(${r},${g},${b},${a})`;
}
function _startCanvasLoop(canvas, patternClass, onResize, paint) {
  let raf = 0;
  window.addEventListener('resize', onResize);
  function stop() {
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    window.removeEventListener('resize', onResize);
  }
  function loop() {
    if (!document.body.contains(canvas) || !document.body.classList.contains(patternClass)) {
      stop();
      return;
    }
    raf = requestAnimationFrame(loop);
    if (document.hidden) return;
    paint();
  }
  raf = requestAnimationFrame(loop);
  return stop;
}

// ── Synapse background effect ──
// Uses the CSS grid pattern as base, overlays fast-moving small light pulses on grid lines
function _initSynapse() {
  if (document.getElementById('synapse-canvas')) return;
  const canvas = document.createElement('canvas');
  canvas.id = 'synapse-canvas';
  canvas.dataset.bgEffect = '1';
  canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;';
  // Decorative background effect — hide from assistive tech so screen readers
  // don't announce an empty canvas and axe's "region" rule doesn't flag it.
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const GRID = 24; // matches CSS grid size
  const MAX_PULSES = 20;
  const SPEED_MIN = 2;
  const SPEED_MAX = 22;
  const TRAIL_LEN = 12; // pixels of trailing glow

  let W, H, cols, rows, pulses = [];

  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    cols = Math.ceil(W / GRID); rows = Math.ceil(H / GRID);
  }
  resize();

  function getColor() {
    const s = getComputedStyle(document.documentElement);
    return s.getPropertyValue('--bg-effect-color').trim() || s.getPropertyValue('--fg').trim() || '#9cdef2';
  }

  function spawnPulse() {
    const speed = SPEED_MIN + Math.random() * (SPEED_MAX - SPEED_MIN);
    if (Math.random() > 0.5) {
      const row = Math.floor(Math.random() * (rows + 1));
      pulses.push({ x: -TRAIL_LEN, y: row * GRID, dx: speed, dy: 0 });
    } else {
      const col = Math.floor(Math.random() * (cols + 1));
      pulses.push({ x: col * GRID, y: -TRAIL_LEN, dx: 0, dy: speed });
    }
  }

  _startCanvasLoop(canvas, 'bg-pattern-synapse', resize, () => {
    ctx.clearRect(0, 0, W, H);
    const c = getColor();

    if (pulses.length < MAX_PULSES && Math.random() < 0.12) spawnPulse();

    for (let i = pulses.length - 1; i >= 0; i--) {
      const p = pulses[i];
      p.x += p.dx; p.y += p.dy;

      if (p.x > W + TRAIL_LEN || p.y > H + TRAIL_LEN) { pulses.splice(i, 1); continue; }

      const tx = p.x - (p.dx > 0 ? TRAIL_LEN : 0);
      const ty = p.y - (p.dy > 0 ? TRAIL_LEN : 0);
      const grad = ctx.createLinearGradient(tx, ty, p.x, p.y);
      grad.addColorStop(0, 'transparent');
      grad.addColorStop(1, c);
      ctx.strokeStyle = grad;
      ctx.globalAlpha = 0.35;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(p.x, p.y);
      ctx.stroke();

      ctx.globalAlpha = 0.55;
      ctx.fillStyle = c;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 1.2, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.globalAlpha = 1;
  });
}

// ── Rain — thin vertical streaks falling ──
function _initRain() {
  if (document.getElementById('rain-canvas')) return;
  const canvas = document.createElement('canvas');
  canvas.id = 'rain-canvas';
  canvas.dataset.bgEffect = '1';
  canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let W, H;
  const drops = [];
  const MAX_DROPS = 130;

  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();

  function getColor() {
    const s = getComputedStyle(document.documentElement);
    return s.getPropertyValue('--bg-effect-color').trim() || s.getPropertyValue('--fg').trim() || '#9cdef2';
  }

  function spawn() {
    const len = 20 + Math.random() * 40;
    const speed = 4 + Math.random() * 8;
    drops.push({ x: Math.random() * W, y: -len, len, speed, alpha: 0.32 + Math.random() * 0.28 });
  }

  _startCanvasLoop(canvas, 'bg-pattern-rain', resize, () => {
    ctx.clearRect(0, 0, W, H);
    const c = getColor();
    const inten = _getEffectIntensity();
    const speedMult = 0.35 + inten * 0.65;
    const sizeMult = _getEffectSize();

    if (drops.length < MAX_DROPS * inten && Math.random() < 0.6 * inten) spawn();

    for (let i = drops.length - 1; i >= 0; i--) {
      const d = drops[i];
      d.y += d.speed * speedMult;
      if (d.y > H + d.len * sizeMult) { drops.splice(i, 1); continue; }

      const effLen = d.len * sizeMult;
      const grad = ctx.createLinearGradient(d.x, d.y - effLen, d.x, d.y);
      grad.addColorStop(0, 'transparent');
      grad.addColorStop(1, c);
      ctx.strokeStyle = grad;
      ctx.globalAlpha = d.alpha;
      ctx.lineWidth = 1.3 * Math.min(2, Math.max(0.6, sizeMult));
      ctx.beginPath();
      ctx.moveTo(d.x, d.y - effLen);
      ctx.lineTo(d.x, d.y);
      ctx.stroke();
    }
    ctx.globalAlpha = 1;
  });
}

// ── Constellations — drifting stars whose links form and dissolve by proximity ──
function _initConstellations() {
  if (document.getElementById('constellations-canvas')) return;
  const canvas = document.createElement('canvas');
  canvas.id = 'constellations-canvas';
  canvas.dataset.bgEffect = '1';
  canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let W, H;
  // Original free-drift model: links appear when stars wander near each other
  // and fade as they drift apart (no clustering / home-pull).
  const STAR_COUNT = 55;
  const CONNECT_DIST = 145;
  let stars = [];
  let t = 0;

  function initStars() {
    stars = [];
    for (let i = 0; i < STAR_COUNT; i++) {
      stars.push({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.15,
        vy: (Math.random() - 0.5) * 0.15,
        r: 1.1 + Math.random() * 1.1,
        phase: Math.random() * Math.PI * 2,
      });
    }
  }

  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (stars.length === 0) initStars();
  }
  resize();
  const _onResize = () => { resize(); initStars(); };

  _startCanvasLoop(canvas, 'bg-pattern-constellations', _onResize, () => {
    t += 0.01;
    ctx.clearRect(0, 0, W, H);
    const c = _bgEffectColor();
    const sz = Math.max(0.4, _getEffectSize());
    // Size slider scales stars + link reach freely (no hard 1.4x cap)
    const connect = CONNECT_DIST * sz;

    for (const s of stars) {
      s.x += s.vx;
      s.y += s.vy;
      if (s.x < 0) s.x = W; if (s.x > W) s.x = 0;
      if (s.y < 0) s.y = H; if (s.y > H) s.y = 0;
    }

    ctx.strokeStyle = c;
    ctx.lineWidth = Math.max(0.5, 0.7 * sz);
    for (let i = 0; i < stars.length; i++) {
      for (let j = i + 1; j < stars.length; j++) {
        const dx = stars[i].x - stars[j].x;
        const dy = stars[i].y - stars[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        if (dist < connect) {
          // Fade in/out with distance — constellation forms then dissolves
          ctx.globalAlpha = (1 - dist / connect) * 0.18;
          ctx.beginPath();
          ctx.moveTo(stars[i].x, stars[i].y);
          ctx.lineTo(stars[j].x, stars[j].y);
          ctx.stroke();
        }
      }
    }

    ctx.fillStyle = c;
    for (const s of stars) {
      const twinkle = 0.5 + 0.5 * Math.sin(t * 2 + s.phase);
      ctx.globalAlpha = 0.15 + twinkle * 0.28;
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r * sz, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  });
}

// ── Noise helper for Perlin effects ──
function _bgNoise2d(x, y) { const n = Math.sin(x * 12.9898 + y * 78.233) * 43758.5453; return n - Math.floor(n); }
function _bgSmoothNoise(x, y) {
  const ix = Math.floor(x), iy = Math.floor(y), fx = x - ix, fy = y - iy;
  const a = _bgNoise2d(ix, iy), b = _bgNoise2d(ix + 1, iy), cc = _bgNoise2d(ix, iy + 1), d = _bgNoise2d(ix + 1, iy + 1);
  const ux = fx * fx * (3 - 2 * fx), uy = fy * fy * (3 - 2 * fy);
  return a + (b - a) * ux + (cc - a) * uy + (a - b - cc + d) * ux * uy;
}

// ── Perlin Flow — colored particle streams with finite fading trails ──
function _initPerlinFlow() {
  const canvas = _mountBgCanvas('perlin-flow-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let W, H, t = 0;
  // Keep particle + trail buffers bounded — no canvas trail accumulation
  // (slow alpha-fade compositing left residual ink and growing GPU pressure).
  const MAX_PARTICLES = 100;
  const TRAIL_LEN = 24;
  const particles = [];

  function makeParticle() {
    return {
      x: Math.random() * W,
      y: Math.random() * H,
      life: 0.4 + Math.random() * 0.6,
      // Fixed ring buffers — no per-frame array alloc / shift GC churn
      tx: new Float32Array(TRAIL_LEN),
      ty: new Float32Array(TRAIL_LEN),
      head: 0,
      len: 0,
    };
  }
  function resetParticle(p) {
    p.x = Math.random() * W;
    p.y = Math.random() * H;
    p.life = 0.5 + Math.random() * 0.5;
    p.head = 0;
    p.len = 0;
  }
  function pushTrail(p) {
    p.tx[p.head] = p.x;
    p.ty[p.head] = p.y;
    p.head = (p.head + 1) % TRAIL_LEN;
    if (p.len < TRAIL_LEN) p.len++;
  }
  function ensureCount() {
    const n = Math.max(16, Math.round(MAX_PARTICLES * _getEffectIntensity()));
    while (particles.length < n) particles.push(makeParticle());
    while (particles.length > n) particles.pop();
  }
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Resizing clears the bitmap; reset trails so we never keep stale pixels
    for (const p of particles) { p.head = 0; p.len = 0; }
    if (particles.length === 0) ensureCount();
  }
  resize();

  _startCanvasLoop(canvas, 'bg-pattern-perlin-flow', resize, () => {
    ensureCount();
    // Full clear every frame — trails live only in the ring buffers and fade out
    // as older points drop off / particle life ends (no residual canvas ink).
    ctx.clearRect(0, 0, W, H);
    const c = _bgEffectColor();
    const sz = _getEffectSize();
    const r = Math.max(0.6, 0.85 * sz);
    ctx.strokeStyle = c;
    ctx.fillStyle = c;
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (let i = 0; i < particles.length; i++) {
      const p = particles[i];
      const n = _bgSmoothNoise(p.x * 0.004 + t * 0.0008, p.y * 0.004 + 100);
      const angle = n * Math.PI * 6;
      const speed = 1 + _bgSmoothNoise(p.x * 0.003, p.y * 0.003 + 50) * 1.5;
      p.x += Math.cos(angle) * speed;
      p.y += Math.sin(angle) * speed;
      p.life -= 0.0025;
      pushTrail(p);

      if (p.life <= 0 || p.x < -20 || p.x > W + 20 || p.y < -20 || p.y > H + 20) {
        resetParticle(p);
        continue;
      }

      // Draw trail oldest → newest; alpha rises toward the head so the tail fades out
      if (p.len > 1) {
        const start = (p.head - p.len + TRAIL_LEN) % TRAIL_LEN;
        ctx.lineWidth = Math.max(0.6, r * 0.9);
        for (let k = 1; k < p.len; k++) {
          const i0 = (start + k - 1) % TRAIL_LEN;
          const i1 = (start + k) % TRAIL_LEN;
          ctx.globalAlpha = p.life * 0.22 * (k / p.len);
          ctx.beginPath();
          ctx.moveTo(p.tx[i0], p.ty[i0]);
          ctx.lineTo(p.tx[i1], p.ty[i1]);
          ctx.stroke();
        }
      }

      ctx.globalAlpha = p.life * 0.28;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    t++;
  });
}

// ── Petals — gentle falling flower petals ──
function _initPetals() {
  if (document.getElementById('petals-canvas')) return;
  const canvas = document.createElement('canvas');
  canvas.id = 'petals-canvas';
  canvas.dataset.bgEffect = '1';
  canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let W, H;
  const petals = [];
  function makePetal() {
    return {
      x: Math.random() * W, y: -10 - Math.random() * 40,
      size: 3 + Math.random() * 5, rot: Math.random() * Math.PI * 2,
      vr: (Math.random() - 0.5) * 0.03, vy: 0.3 + Math.random() * 0.6,
      drift: Math.random() * Math.PI * 2, driftSpeed: 0.008 + Math.random() * 0.012,
      wobble: 0.3 + Math.random() * 0.8
    };
  }
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (petals.length === 0) for (let i = 0; i < 30; i++) { const p = makePetal(); p.y = Math.random() * H; petals.push(p); }
  }
  resize();

  function getColor() {
    const s = getComputedStyle(document.documentElement);
    return s.getPropertyValue('--bg-effect-color').trim() || s.getPropertyValue('--fg').trim() || '#9cdef2';
  }

  _startCanvasLoop(canvas, 'bg-pattern-petals', resize, () => {
    ctx.clearRect(0, 0, W, H);
    const c = getColor();
    const sz = _getEffectSize();
    petals.forEach(p => {
      p.y += p.vy; p.rot += p.vr; p.drift += p.driftSpeed;
      p.x += Math.sin(p.drift) * p.wobble;
      if (p.y > H + 15) Object.assign(p, makePetal());
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot);
      ctx.globalAlpha = 0.2;
      ctx.fillStyle = c;
      ctx.beginPath(); ctx.ellipse(-p.size * 0.2 * sz, 0, p.size * 0.6 * sz, p.size * 0.3 * sz, 0.3, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 0.15;
      ctx.beginPath(); ctx.ellipse(p.size * 0.2 * sz, 0, p.size * 0.6 * sz, p.size * 0.3 * sz, -0.3, 0, Math.PI * 2); ctx.fill();
      ctx.restore();
    });
    ctx.globalAlpha = 1;
  });
}

// ── Sparkles — twinkling star-shaped sparkles ──
function _initSparkles() {
  if (document.getElementById('sparkles-canvas')) return;
  const canvas = document.createElement('canvas');
  canvas.id = 'sparkles-canvas';
  canvas.dataset.bgEffect = '1';
  canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let W, H;
  const sparkles = [];
  function makeSpark() {
    return { x: Math.random() * W, y: Math.random() * H, size: 2 + Math.random() * 5, phase: Math.random() * Math.PI * 2, speed: 0.015 + Math.random() * 0.03, life: 0.5 + Math.random() * 0.5 };
  }
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (sparkles.length === 0) for (let i = 0; i < 35; i++) sparkles.push(makeSpark());
  }
  resize();

  function getColor() {
    const s = getComputedStyle(document.documentElement);
    return s.getPropertyValue('--bg-effect-color').trim() || s.getPropertyValue('--fg').trim() || '#9cdef2';
  }
  function drawStar(x, y, r, c, alpha) {
    ctx.save(); ctx.translate(x, y); ctx.fillStyle = c; ctx.globalAlpha = alpha;
    ctx.beginPath();
    ctx.moveTo(0, -r); ctx.quadraticCurveTo(r * 0.15, -r * 0.15, r, 0);
    ctx.quadraticCurveTo(r * 0.15, r * 0.15, 0, r);
    ctx.quadraticCurveTo(-r * 0.15, r * 0.15, -r, 0);
    ctx.quadraticCurveTo(-r * 0.15, -r * 0.15, 0, -r);
    ctx.fill();
    ctx.restore();
  }

  _startCanvasLoop(canvas, 'bg-pattern-sparkles', resize, () => {
    ctx.clearRect(0, 0, W, H);
    const c = getColor();
    const sizeMult = _getEffectSize();
    sparkles.forEach(s => {
      s.phase += s.speed;
      const twinkle = Math.sin(s.phase);
      const alpha = Math.max(0, twinkle) * 0.25 * s.life;
      const scale = 0.5 + Math.max(0, twinkle) * 0.5;
      if (alpha > 0.01) drawStar(s.x, s.y, s.size * scale * sizeMult, c, alpha);
      if (s.phase > Math.PI * 6) Object.assign(s, makeSpark());
    });
    ctx.globalAlpha = 1;
  });
}

// ── Embers — warm particles rising with glow and occasional spark bursts ──
function _initEmbers() {
  if (document.getElementById('embers-canvas')) return;
  const canvas = document.createElement('canvas');
  canvas.id = 'embers-canvas';
  canvas.dataset.bgEffect = '1';
  canvas.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;pointer-events:none;z-index:0;';
  canvas.setAttribute('aria-hidden', 'true');
  document.body.prepend(canvas);
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let W, H;
  const embers = [];
  function makeEmber() {
    return {
      x: Math.random() * W,
      y: H + Math.random() * 40,
      vx: (Math.random() - 0.5) * 0.3,
      vy: -0.3 - Math.random() * 0.8,
      r: 0.3 + Math.random() * 0.6,
      life: 0,
      maxLife: 220 + Math.random() * 220,
      wobble: Math.random() * Math.PI * 2,
      spark: false,
    };
  }
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (embers.length === 0) {
      for (let i = 0; i < 60; i++) { const e = makeEmber(); e.y = Math.random() * H; e.life = Math.random() * e.maxLife; embers.push(e); }
    }
  }
  resize();

  function getColor() {
    const s = getComputedStyle(document.documentElement);
    return s.getPropertyValue('--bg-effect-color').trim() || s.getPropertyValue('--fg').trim() || '#c9a95a';
  }
  function rgba(hex, a) {
    const { r, g, b } = hexToRgb(hex) || { r: 0, g: 0, b: 0 };
    return `rgba(${r},${g},${b},${a})`;
  }

  _startCanvasLoop(canvas, 'bg-pattern-embers', resize, () => {
    ctx.globalCompositeOperation = 'destination-out';
    ctx.fillStyle = 'rgba(0,0,0,0.18)';
    ctx.fillRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'lighter';
    const color = getColor();
    for (let i = embers.length - 1; i >= 0; i--) {
      const e = embers[i];
      e.wobble += 0.03;
      e.x += e.vx + Math.sin(e.wobble) * 0.5;
      e.y += e.vy;
      e.life++;
      if (e.life > e.maxLife || e.y < -20) {
        embers.splice(i, 1);
        if (embers.length < 70) embers.push(makeEmber());
        continue;
      }
      if (!e.spark && Math.random() < 0.003) e.spark = true;
      const lifeRatio = e.life / e.maxLife;
      const fade = Math.min(1, Math.min(lifeRatio * 4, (1 - lifeRatio) * 3));
      const sz = _getEffectSize();
      const r = e.r * (e.spark ? 2.4 : 1) * sz;
      const a = (e.spark ? 0.9 : 0.55) * fade;
      const g = ctx.createRadialGradient(e.x, e.y, 0, e.x, e.y, r * 4);
      g.addColorStop(0, rgba(color, a));
      g.addColorStop(0.4, rgba(color, a * 0.3));
      g.addColorStop(1, rgba(color, 0));
      ctx.fillStyle = g;
      ctx.fillRect(e.x - r * 4, e.y - r * 4, r * 8, r * 8);
      ctx.fillStyle = rgba('#ffffff', a * 0.6);
      ctx.beginPath();
      ctx.arc(e.x, e.y, r * 0.5, 0, Math.PI * 2);
      ctx.fill();
      e.spark = false;
    }
    if (Math.random() < 0.015) {
      const bx = Math.random() * W;
      for (let i = 0; i < 5; i++) {
        const e = makeEmber();
        e.x = bx + (Math.random() - 0.5) * 40;
        e.y = H - 10;
        e.vy *= 1.5;
        embers.push(e);
      }
    }
    ctx.globalCompositeOperation = 'source-over';
  });
}

// ── Fireflies — sparse drifting glow points ──
function _initFireflies() {
  const canvas = _mountBgCanvas('fireflies-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const MAX = 28;
  let W, H;
  const flies = [];
  function makeFly() {
    return {
      x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.35, vy: (Math.random() - 0.5) * 0.35,
      phase: Math.random() * Math.PI * 2,
      speed: 0.02 + Math.random() * 0.03,
      r: 1.2 + Math.random() * 1.8,
    };
  }
  function ensureCount() {
    const n = Math.max(6, Math.round(MAX * _getEffectIntensity()));
    while (flies.length < n) flies.push(makeFly());
    while (flies.length > n) flies.pop();
  }
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!flies.length) ensureCount();
  }
  resize();
  _startCanvasLoop(canvas, 'bg-pattern-fireflies', resize, () => {
    ensureCount();
    ctx.clearRect(0, 0, W, H);
    const color = _bgEffectColor();
    const sz = _getEffectSize();
    for (const f of flies) {
      f.phase += f.speed;
      f.x += f.vx + Math.sin(f.phase) * 0.15;
      f.y += f.vy + Math.cos(f.phase * 0.7) * 0.12;
      if (f.x < -20) f.x = W + 20; if (f.x > W + 20) f.x = -20;
      if (f.y < -20) f.y = H + 20; if (f.y > H + 20) f.y = -20;
      const tw = 0.35 + 0.65 * Math.max(0, Math.sin(f.phase));
      const r = f.r * sz * (0.7 + tw * 0.5);
      const g = ctx.createRadialGradient(f.x, f.y, 0, f.x, f.y, r * 5);
      g.addColorStop(0, _bgRgba(color, 0.55 * tw));
      g.addColorStop(0.35, _bgRgba(color, 0.18 * tw));
      g.addColorStop(1, _bgRgba(color, 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(f.x, f.y, r * 5, 0, Math.PI * 2);
      ctx.fill();
    }
  });
}

// ── Aurora — soft vertical color bands drifting ──
function _initAurora() {
  const canvas = _mountBgCanvas('aurora-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const BANDS = 4;
  let W, H, t = 0;
  const bands = [];
  function initBands() {
    bands.length = 0;
    for (let i = 0; i < BANDS; i++) {
      bands.push({
        x: (i + 0.5) / BANDS,
        w: 0.14 + Math.random() * 0.08,
        amp: 20 + Math.random() * 24,
        freq: 0.7 + Math.random() * 0.7,
        phase: Math.random() * Math.PI * 2,
        drift: 0.00035 + Math.random() * 0.00045,
      });
    }
  }
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!bands.length) initBands();
  }
  resize();
  _startCanvasLoop(canvas, 'bg-pattern-aurora', resize, () => {
    ctx.clearRect(0, 0, W, H);
    const color = _bgEffectColor();
    const sz = _getEffectSize();
    const inten = _getEffectIntensity();
    t += 1;
    // Draw as stacked soft vertical strips — fixed band count, no path growth
    for (const b of bands) {
      b.phase += b.drift;
      const cx = ((b.x + Math.sin(t * 0.0018 + b.phase) * 0.1) % 1 + 1) % 1 * W
        + Math.sin(t * 0.01 * b.freq + b.phase) * b.amp * sz;
      const half = Math.max(50, b.w * W * (0.7 + 0.3 * sz));
      const g = ctx.createLinearGradient(cx - half, 0, cx + half, 0);
      g.addColorStop(0, _bgRgba(color, 0));
      g.addColorStop(0.5, _bgRgba(color, 0.1 * inten));
      g.addColorStop(1, _bgRgba(color, 0));
      ctx.fillStyle = g;
      ctx.fillRect(cx - half, 0, half * 2, H);
    }
  });
}

// ── Paper grain — fine film grain via reused low-res buffer (no per-frame alloc) ──
function _initPaperGrain() {
  const canvas = _mountBgCanvas('paper-grain-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const GW = 128, GH = 128; // fixed tiny buffer — RAM bounded
  const grain = document.createElement('canvas');
  grain.width = GW; grain.height = GH;
  const gctx = grain.getContext('2d', { willReadFrequently: true });
  const img = gctx.createImageData(GW, GH);
  const data = img.data;
  let W, H, tick = 0, pat = null;
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    pat = null; // pattern is tied to grain canvas; refresh after resize
  }
  resize();
  _startCanvasLoop(canvas, 'bg-pattern-paper-grain', resize, () => {
    tick++;
    // Refresh noise every other frame — cheaper, still looks alive
    if (tick % 2 === 0) {
      const color = _bgEffectColor('#888888');
      const { r, g, b } = hexToRgb(color) || { r: 128, g: 128, b: 128 };
      const aBase = Math.round(36 * _getEffectIntensity());
      for (let i = 0; i < data.length; i += 4) {
        const n = (Math.random() * 255) | 0;
        data[i] = r; data[i + 1] = g; data[i + 2] = b;
        data[i + 3] = Math.min(255, ((n * aBase) / 255) | 0);
      }
      gctx.putImageData(img, 0, 0);
      pat = ctx.createPattern(grain, 'repeat');
    }
    ctx.clearRect(0, 0, W, H);
    if (!pat) return;
    const s = Math.max(0.5, _getEffectSize());
    ctx.save();
    ctx.scale(s, s);
    ctx.fillStyle = pat;
    ctx.fillRect(0, 0, W / s, H / s);
    ctx.restore();
  });
}

// ── Ripple — sparse expanding circles ──
function _initRipple() {
  const canvas = _mountBgCanvas('ripple-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const MAX = 6;
  let W, H;
  const ripples = [];
  function spawn() {
    if (ripples.length >= MAX) return;
    ripples.push({
      x: Math.random() * W, y: Math.random() * H,
      r: 4, max: 60 + Math.random() * 100, life: 0.6 + Math.random() * 0.9, alpha: 0.35,
    });
  }
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();
  _startCanvasLoop(canvas, 'bg-pattern-ripple', resize, () => {
    ctx.clearRect(0, 0, W, H);
    const color = _bgEffectColor();
    const inten = _getEffectIntensity();
    const sz = _getEffectSize();
    if (ripples.length < Math.max(1, Math.round(MAX * inten)) && Math.random() < 0.025 * inten) spawn();
    for (let i = ripples.length - 1; i >= 0; i--) {
      const p = ripples[i];
      p.r += p.speed * sz;
      const life = 1 - p.r / (p.max * sz);
      if (life <= 0) { ripples.splice(i, 1); continue; }
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.strokeStyle = _bgRgba(color, p.alpha * life * inten);
      ctx.lineWidth = Math.max(0.6, 1.2 * sz);
      ctx.stroke();
    }
  });
}

// ── Drift grid — slow parallax of faint diagonal lines ──
function _initDriftGrid() {
  const canvas = _mountBgCanvas('drift-grid-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let W, H, t = 0;
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();
  _startCanvasLoop(canvas, 'bg-pattern-drift-grid', resize, () => {
    ctx.clearRect(0, 0, W, H);
    const color = _bgEffectColor();
    const inten = _getEffectIntensity();
    const spacing = Math.max(18, 36 / _getEffectSize());
    t += 0.15;
    const off = t % spacing;
    ctx.strokeStyle = _bgRgba(color, 0.08 * inten);
    ctx.lineWidth = 1;
    // Two diagonal directions — line count bounded by viewport / spacing
    const diag = W + H;
    const n = Math.ceil(diag / spacing) + 2;
    for (let i = -1; i < n; i++) {
      const x = i * spacing + off;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x - H, H);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x + H, H);
      ctx.stroke();
    }
  });
}

// ── Orbit rings — slow concentric arcs ──
function _initOrbitRings() {
  const canvas = _mountBgCanvas('orbit-rings-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const RINGS = 5;
  let W, H;
  const rings = [];
  for (let i = 0; i < RINGS; i++) {
    rings.push({
      frac: 0.12 + i * 0.12,
      phase: Math.random() * Math.PI * 2,
      speed: 0.003 + i * 0.0012,
      arc: Math.PI * (0.4 + Math.random() * 0.6),
      gap: Math.random() * Math.PI * 2,
    });
  }
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();
  _startCanvasLoop(canvas, 'bg-pattern-orbit-rings', resize, () => {
    ctx.clearRect(0, 0, W, H);
    const color = _bgEffectColor();
    const inten = _getEffectIntensity();
    const sz = _getEffectSize();
    const cx = W * 0.5, cy = H * 0.5;
    const base = Math.min(W, H) * 0.5 * sz;
    ctx.lineCap = 'round';
    for (const r of rings) {
      r.phase += r.speed;
      const rad = base * r.frac;
      ctx.beginPath();
      ctx.arc(cx, cy, rad, r.phase + r.gap, r.phase + r.gap + r.arc);
      ctx.strokeStyle = _bgRgba(color, 0.14 * inten);
      ctx.lineWidth = Math.max(0.8, 1.4 * sz);
      ctx.stroke();
      // faint counter-arc
      ctx.beginPath();
      ctx.arc(cx, cy, rad, r.phase + r.gap + Math.PI, r.phase + r.gap + Math.PI + r.arc * 0.5);
      ctx.strokeStyle = _bgRgba(color, 0.06 * inten);
      ctx.stroke();
    }
  });
}

// ── Fog / mist — few large soft blobs pooled mostly along the bottom ──
function _initFog() {
  const canvas = _mountBgCanvas('fog-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const MAX = 6; // hard cap — each blob is a large gradient
  let W, H;
  const blobs = [];
  function bottomY() {
    // Bias spawn into the lower ~40% of the viewport
    return H * (0.55 + Math.random() * 0.45);
  }
  function makeBlob() {
    return {
      x: Math.random() * W,
      y: bottomY(),
      vx: (Math.random() - 0.5) * 0.25,
      vy: (Math.random() - 0.5) * 0.08,
      r: 140 + Math.random() * 180,
      phase: Math.random() * Math.PI * 2,
    };
  }
  function ensureCount() {
    const n = Math.max(3, Math.round(MAX * _getEffectIntensity()));
    while (blobs.length < n) blobs.push(makeBlob());
    while (blobs.length > n) blobs.pop();
  }
  function resize() {
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = W * dpr; canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    if (!blobs.length) ensureCount();
    else for (const b of blobs) { if (b.y < H * 0.45) b.y = bottomY(); }
  }
  resize();
  _startCanvasLoop(canvas, 'bg-pattern-fog', resize, () => {
    ensureCount();
    ctx.clearRect(0, 0, W, H);
    const color = _bgEffectColor();
    const sz = _getEffectSize();
    const inten = _getEffectIntensity();
    const floor = H * 0.5;
    for (const b of blobs) {
      b.phase += 0.004;
      b.x += b.vx + Math.sin(b.phase) * 0.12;
      b.y += b.vy + Math.cos(b.phase * 0.8) * 0.05;
      // Soft spring back toward the lower band so fog stays grounded
      if (b.y < floor) b.vy += 0.02;
      if (b.y > H + b.r * 0.2) b.vy -= 0.015;
      b.vy *= 0.99;
      if (b.x < -b.r) b.x = W + b.r; if (b.x > W + b.r) b.x = -b.r;
      if (b.y < H * 0.35) b.y = bottomY();
      if (b.y > H + b.r) b.y = bottomY();
      const r = b.r * sz;
      const g = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, r);
      g.addColorStop(0, _bgRgba(color, 0.09 * inten));
      g.addColorStop(0.5, _bgRgba(color, 0.04 * inten));
      g.addColorStop(1, _bgRgba(color, 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(b.x, b.y, r, 0, Math.PI * 2);
      ctx.fill();
    }
  });
}

const themeModule = { initThemeUI, togglePopup, closePopup, makeDraggable,
                       THEMES, applyColors, applyFontDensity, applyBgPattern,
                       applyBgEffectColor, applyBgEffectIntensity, applyBgEffectSize,
                       applyFrostedGlass, applyGlassWindows,
                       save, getSaved, saveCustomTheme, deleteCustomTheme,
                       getCustomThemes };

export default themeModule;

// Init on DOM ready, with server-side sync fallback
async function _initWithSync() {
  try {
  // If no local theme, try loading from server (cross-device sync)
  if (!getSaved()) {
    const serverTheme = await _loadFromServer();
    if (serverTheme && serverTheme.colors) {
      _migrateThemeName(serverTheme);
      Storage.setJSON(LS_KEY, serverTheme);
      applyColors(serverTheme.colors);
    } else {
      // Truly fresh install — seed the product default so FOUC + sync agree.
      const colors = THEMES[DEFAULT_THEME];
      const defaultPattern = THEME_DEFAULT_PATTERN[DEFAULT_THEME] || 'none';
      try {
        save(DEFAULT_THEME, colors, {
          font: DEFAULT_FONT,
          density: DEFAULT_DENSITY,
          bgPattern: defaultPattern,
        });
      } catch (e) { console.warn('Default theme persist failed:', e); }
      applyColors(colors);
    }
  }
  // Also sync custom themes from server
  try {
    const res = await fetch('/api/prefs/custom-themes', { credentials: 'same-origin' });
    const data = await res.json();
    if (data.value && typeof data.value === 'object') {
      const local = _loadCustomThemes();
      // Merge: server themes fill in missing local ones
      let changed = false;
      for (const [name, colors] of Object.entries(data.value)) {
        if (!local[name]) { local[name] = colors; changed = true; }
      }
      if (changed) _saveCustomThemes(local);
    }
  } catch (e) { console.warn('Custom theme server sync failed:', e); }
  try {
    initThemeUI();
  } catch (e) {
    console.error('[theme] initThemeUI failed:', e);
  }
  } catch (e) {
    console.error('[theme] _initWithSync failed:', e);
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => _initWithSync());
} else {
  _initWithSync();
}
