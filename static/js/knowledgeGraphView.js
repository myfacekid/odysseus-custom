/**
 * Links graph view — a dependency-free, Obsidian-style force-directed graph
 * for the Links window. Renders nodes and typed, colour-coded edges on a
 * <canvas> with pan, zoom, node dragging, distance-based highlight, search
 * dimming, per-edge-kind motifs, a legend, tooltips, a context menu, keyboard
 * navigation, an isolate (local-graph) mode, and a Barnes–Hut layout.
 *
 * Kept self-contained (no vendored graph library) so it works offline and adds
 * no build/dependency surface.
 */

import { edgeKind, EDGE_KINDS, LEGEND_EDGE_KINDS } from './edgeKinds.js';

// Node fill colors by graph node type.
const TYPE_COLORS = {
  task: '#f2a35e',
  document: '#6b8cff',
  note: '#6b8cff',
  memory: '#c084fc',
  skill: '#4dd4ac',
  paper: '#6b8cff',
  research: '#9b6bff',
  collection: '#f4d160',
  project: '#66bb88',
};
const DEFAULT_COLOR = '#8aa0c0';

const TYPE_LABELS = {
  task: 'Task', document: 'Document', note: 'Document', memory: 'Memory',
  skill: 'Skill', paper: 'Paper', research: 'Research', project: 'Project',
  collection: 'Collection',
};

const STORAGE_KEY = 'nobody-links-graph-view';
const ISOLATE_HOPS = 1;      // "local graph" = focus + direct neighbours
const DRIFT_AMP = 1.6;       // gentle idle sway, in world units
const DRIFT_SPEED = 0.0006;  // radians per ms
const ANIM_SPEED = 6;        // focus fade-in/out per second

function _typeColor(type) {
  const t = type === 'note' ? 'document' : (type || '');
  return TYPE_COLORS[t] || DEFAULT_COLOR;
}

/** Collapse whitespace / strip markdown markers so canvas labels stay short titles. */
function _sanitizeGraphLabel(text, maxLen = 24) {
  let s = String(text || 'Untitled')
    .replace(/[\r\n\t]+/g, ' ')
    .replace(/^#+\s*/, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!s) s = 'Untitled';
  if (s.length > maxLen) s = s.slice(0, maxLen - 1) + '…';
  return s;
}

function _cssVar(name, fallback) {
  try {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  } catch {
    return fallback;
  }
}

export class KnowledgeGraphView {
  constructor(container, { onSelect, onOpen, onAddLink, onRemoveLink, onRebuild } = {}) {
    this.container = container;
    this.onSelect = onSelect || (() => {});
    this.onOpen = onOpen || (() => {});
    this.onAddLink = onAddLink || (() => {});
    this.onRemoveLink = onRemoveLink || (() => {});
    this.onRebuild = onRebuild || null;

    this.canvas = document.createElement('canvas');
    this.canvas.className = 'kg-graph-canvas';
    this.canvas.tabIndex = 0;
    this.ctx = this.canvas.getContext('2d');
    container.appendChild(this.canvas);

    this.legend = document.createElement('div');
    this.legend.className = 'kg-graph-legend';
    container.appendChild(this.legend);

    this.overlay = document.createElement('div');
    this.overlay.className = 'kg-graph-overlay';
    this.overlay.innerHTML = `
      <button type="button" class="kg-graph-ctl" data-act="legend" title="Toggle legend (L)" aria-label="Toggle legend">⊞</button>
      <button type="button" class="kg-graph-ctl" data-act="isolate" title="Isolate local graph (I)" aria-label="Isolate local graph">◎</button>
      <button type="button" class="kg-graph-ctl" data-act="fit" title="Fit to view" aria-label="Fit to view">⤢</button>
      <button type="button" class="kg-graph-ctl" data-act="in" title="Zoom in" aria-label="Zoom in">+</button>
      <button type="button" class="kg-graph-ctl" data-act="out" title="Zoom out" aria-label="Zoom out">−</button>`;
    container.appendChild(this.overlay);

    this.tooltip = document.createElement('div');
    this.tooltip.className = 'kg-graph-tooltip hidden';
    container.appendChild(this.tooltip);

    this.menu = document.createElement('div');
    this.menu.className = 'kg-graph-menu hidden';
    container.appendChild(this.menu);

    this.hint = document.createElement('div');
    this.hint.className = 'kg-graph-hint';
    container.appendChild(this.hint);

    this.empty = document.createElement('div');
    this.empty.className = 'kg-graph-emptystate hidden';
    container.appendChild(this.empty);

    this.nodes = [];
    this.edges = [];
    this.nodeById = new Map();
    this.adjacency = new Map();   // id -> Set<id>
    this.incident = new Map();    // id -> [{ other, kind, dir }]

    this.transform = { k: 1, x: 0, y: 0 };
    this.selectedId = null;
    this.hoverId = null;
    this.query = '';

    // Ripple focus (explicit graph interaction only — not list auto-select).
    this._graphFocusId = null;
    this._animFocus = null;
    this._focusStrength = 0;
    this.isolate = false;
    this.legendVisible = true;
    this._navIdx = 0;

    this._distFocus = null;
    this._distMap = null;
    this._kindFromFocus = null;

    // Barnes–Hut tuning.
    this._repel = 5200;
    this._theta2 = 0.81;

    this._alpha = 0;
    this._raf = null;
    this._lastTs = 0;
    this._dragNode = null;
    this._panning = false;
    this._pointerStart = null;
    this._moved = false;
    this._active = false;
    this._dpr = Math.max(1, window.devicePixelRatio || 1);
    this._persistTimer = null;

    this._loadPersisted();

    this._onWheel = this._onWheel.bind(this);
    this._onPointerDown = this._onPointerDown.bind(this);
    this._onPointerMove = this._onPointerMove.bind(this);
    this._onPointerUp = this._onPointerUp.bind(this);
    this._onDblClick = this._onDblClick.bind(this);
    this._onContextMenu = this._onContextMenu.bind(this);
    this._onKeyDown = this._onKeyDown.bind(this);
    this._onDocClick = this._onDocClick.bind(this);
    this._loop = this._loop.bind(this);

    this.canvas.addEventListener('wheel', this._onWheel, { passive: false });
    this.canvas.addEventListener('pointerdown', this._onPointerDown);
    window.addEventListener('pointermove', this._onPointerMove);
    window.addEventListener('pointerup', this._onPointerUp);
    this.canvas.addEventListener('dblclick', this._onDblClick);
    this.canvas.addEventListener('contextmenu', this._onContextMenu);
    this.canvas.addEventListener('keydown', this._onKeyDown);
    document.addEventListener('click', this._onDocClick);
    this.overlay.addEventListener('click', (ev) => {
      const act = ev.target.closest('.kg-graph-ctl')?.dataset.act;
      if (act === 'fit') this.fit();
      else if (act === 'in') this._zoomBy(1.3);
      else if (act === 'out') this._zoomBy(1 / 1.3);
      else if (act === 'isolate') this._toggleIsolate();
      else if (act === 'legend') this._toggleLegend();
    });

    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(container);
    this._resize();
  }

  destroy() {
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
    this._ro?.disconnect();
    this.canvas.removeEventListener('wheel', this._onWheel);
    this.canvas.removeEventListener('pointerdown', this._onPointerDown);
    window.removeEventListener('pointermove', this._onPointerMove);
    window.removeEventListener('pointerup', this._onPointerUp);
    this.canvas.removeEventListener('dblclick', this._onDblClick);
    this.canvas.removeEventListener('contextmenu', this._onContextMenu);
    this.canvas.removeEventListener('keydown', this._onKeyDown);
    document.removeEventListener('click', this._onDocClick);
    this.container.innerHTML = '';
  }

  // ── persistence ───────────────────────────────────────────────
  _loadPersisted() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        this._savedK = typeof s.k === 'number' ? s.k : null;
        this._savedFocus = s.focusId || null;
        this.isolate = !!s.isolate;
        if (typeof s.legendVisible === 'boolean') this.legendVisible = s.legendVisible;
      }
    } catch { /* ignore */ }
  }

  _persist() {
    clearTimeout(this._persistTimer);
    this._persistTimer = setTimeout(() => {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
          k: this.transform.k,
          focusId: this._graphFocusId,
          isolate: this.isolate,
          legendVisible: this.legendVisible,
        }));
      } catch { /* ignore */ }
    }, 400);
  }

  // ── data ──────────────────────────────────────────────────────
  setData(nodes, edges) {
    const prev = new Map(this.nodes.map((n) => [n.id, n]));
    this.nodeById = new Map();
    this.adjacency = new Map();
    this.incident = new Map();

    const cx = this._worldW() / 2;
    const cy = this._worldH() / 2;
    const count = nodes.length || 1;

    this.nodes = nodes.map((raw, i) => {
      const old = prev.get(raw.id);
      const angle = (i / count) * Math.PI * 2;
      const radius = 40 + Math.min(this._worldW(), this._worldH()) * 0.3;
      const node = {
        id: raw.id,
        type: raw.type || 'document',
        title: raw.title || raw.id || 'Untitled',
        x: old ? old.x : cx + Math.cos(angle) * radius,
        y: old ? old.y : cy + Math.sin(angle) * radius,
        vx: 0,
        vy: 0,
        degree: 0,
        _phase: old ? old._phase : Math.random() * Math.PI * 2,
        _sx: 0,
        _sy: 0,
      };
      this.nodeById.set(node.id, node);
      this.adjacency.set(node.id, new Set());
      this.incident.set(node.id, []);
      return node;
    });

    this.edges = (edges || []).filter(
      (e) => this.nodeById.has(e.from) && this.nodeById.has(e.to) && e.from !== e.to,
    ).map((e) => ({ from: e.from, to: e.to, kind: (e.kind || 'relates').toLowerCase() }));

    for (const e of this.edges) {
      this.nodeById.get(e.from).degree += 1;
      this.nodeById.get(e.to).degree += 1;
      this.adjacency.get(e.from).add(e.to);
      this.adjacency.get(e.to).add(e.from);
      this.incident.get(e.from).push({ other: e.to, kind: e.kind, dir: 'out' });
      this.incident.get(e.to).push({ other: e.from, kind: e.kind, dir: 'in' });
    }

    if (this.selectedId && !this.nodeById.has(this.selectedId)) this.selectedId = null;
    if (this._graphFocusId && !this.nodeById.has(this._graphFocusId)) this._graphFocusId = null;

    // Restore a persisted focus once its node exists.
    if (!this._graphFocusId && this._savedFocus && this.nodeById.has(this._savedFocus)) {
      this._graphFocusId = this._savedFocus;
      this._animFocus = this._savedFocus;
      this._focusStrength = 1;
    }
    this._distFocus = null;
    this._distMap = null;

    this._buildLegend();
    this.empty.classList.toggle('hidden', this.nodes.length > 0);
    if (!this.nodes.length) this._renderEmptyState();

    this._reheat(1);
    this._pendingFit = true;
    this._start();
  }

  setSelected(id) {
    // Selection drives only the ring/preview — not the ripple (that is explicit
    // graph interaction). This keeps the graph calm during list auto-select.
    this.selectedId = id && this.nodeById.has(id) ? id : null;
    this._start();
    this._draw();
  }

  /**
   * Focus a node as if the user had clicked it in the graph: select it and
   * light up its ripple trace. Used when a row is clicked in the list so the
   * two surfaces behave identically. Centers the view so the trace is visible.
   */
  focusNode(id, { center = true } = {}) {
    if (!id || !this.nodeById.has(id)) return;
    this.selectedId = id;
    this._setGraphFocus(id, { center });
  }

  setQuery(q) {
    this.query = (q || '').trim().toLowerCase();
    this._draw();
  }

  isEmpty() {
    return this.nodes.length === 0;
  }

  /** Center + focus the first node whose title matches the current query. */
  focusSearchMatch(query) {
    const q = (query != null ? query : this.query).trim().toLowerCase();
    if (!q) return false;
    const hit = this.nodes.find((n) => n.title.toLowerCase().includes(q));
    if (!hit) return false;
    this.selectedId = hit.id;
    this._setGraphFocus(hit.id, { center: true });
    this.onSelect(hit.id);
    return true;
  }

  /** Called by the host when the modal opens/closes, to gate idle animation. */
  setActive(active) {
    this._active = !!active;
    if (this._active) {
      this._resize();
      this._start();
    }
  }

  // ── layout / simulation ───────────────────────────────────────
  _nodeRadius(node) {
    return 5 + Math.min(9, Math.sqrt(node.degree || 0) * 2.4);
  }

  _reheat(alpha = 0.6) {
    this._alpha = Math.max(this._alpha, alpha);
    this._start();
  }

  _start() {
    if (!this._raf) this._raf = requestAnimationFrame(this._loop);
  }

  _loop(ts) {
    this._raf = null;
    const dt = this._lastTs ? Math.min(0.05, (ts - this._lastTs) / 1000) : 0.016;
    this._lastTs = ts;

    if (this._alpha > 0.005 || this._dragNode) this._physics();
    const animating = this._stepFocusAnim(dt);
    this._draw();

    if (this._pendingFit && this._alpha < 0.25) {
      this._pendingFit = false;
      this.fit();
    }

    if (this._alpha > 0.005 || this._dragNode || this._panning || animating
        || (this._active && this.nodes.length)) {
      this._start();
    }
  }

  _stepFocusAnim(dt) {
    const target = this.hoverId || this._graphFocusId;
    if (target) {
      if (this._animFocus !== target) {
        this._animFocus = target;
        this._distFocus = null;
      }
      this._focusStrength = Math.min(1, this._focusStrength + dt * ANIM_SPEED);
      return this._focusStrength < 1;
    }
    this._focusStrength = Math.max(0, this._focusStrength - dt * ANIM_SPEED);
    if (this._focusStrength <= 0.001) { this._animFocus = null; return false; }
    return true;
  }

  _physics() {
    const nodes = this.nodes;
    const n = nodes.length;
    if (!n) { this._alpha = 0; return; }
    const cx = this._worldW() / 2;
    const cy = this._worldH() / 2;
    const alpha = this._alpha;

    // Repulsion via Barnes–Hut (O(n log n)).
    const tree = this._buildTree(nodes);
    if (tree) for (const a of nodes) this._applyTreeForce(tree, a, alpha);

    // Springs.
    const ideal = 90;
    const spring = 0.04;
    for (const e of this.edges) {
      const a = this.nodeById.get(e.from);
      const b = this.nodeById.get(e.to);
      const dx = b.x - a.x;
      const dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = (dist - ideal) * spring * alpha;
      const fx = (dx / dist) * force;
      const fy = (dy / dist) * force;
      a.vx += fx; a.vy += fy;
      b.vx -= fx; b.vy -= fy;
    }

    const center = 0.015 * alpha;
    const damp = 0.82;
    for (const node of nodes) {
      if (node === this._dragNode) { node.vx = 0; node.vy = 0; continue; }
      node.vx += (cx - node.x) * center;
      node.vy += (cy - node.y) * center;
      node.vx *= damp;
      node.vy *= damp;
      node.x += node.vx;
      node.y += node.vy;
    }
    this._alpha *= 0.985;
  }

  // ── Barnes–Hut quadtree ───────────────────────────────────────
  _buildTree(nodes) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of nodes) {
      if (n.x < minX) minX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.x > maxX) maxX = n.x;
      if (n.y > maxY) maxY = n.y;
    }
    if (!Number.isFinite(minX)) return null;
    const size = Math.max(maxX - minX, maxY - minY, 1) + 1;
    const root = { x: minX, y: minY, size, mass: 0, sumX: 0, sumY: 0, body: null, children: null };
    for (const n of nodes) this._treeInsert(root, n);
    return root;
  }

  _treeInsert(cell, n) {
    if (cell.mass === 0 && !cell.children) {
      cell.body = n; cell.mass = 1; cell.sumX = n.x; cell.sumY = n.y;
      return;
    }
    if (cell.body) {
      const b = cell.body;
      cell.body = null;
      cell.children = [null, null, null, null];
      this._treeToChild(cell, b);
    }
    cell.mass += 1; cell.sumX += n.x; cell.sumY += n.y;
    this._treeToChild(cell, n);
  }

  _treeToChild(cell, n) {
    const half = cell.size / 2;
    if (!cell.children) cell.children = [null, null, null, null];
    const right = n.x >= cell.x + half ? 1 : 0;
    const bottom = n.y >= cell.y + half ? 1 : 0;
    const idx = right + bottom * 2;
    let c = cell.children[idx];
    if (!c) {
      c = {
        x: cell.x + right * half,
        y: cell.y + bottom * half,
        size: half, mass: 0, sumX: 0, sumY: 0, body: null, children: null,
      };
      cell.children[idx] = c;
    }
    this._treeInsert(c, n);
  }

  _applyTreeForce(cell, n, alpha) {
    if (!cell || cell.mass === 0) return;
    const comx = cell.sumX / cell.mass;
    const comy = cell.sumY / cell.mass;
    let dx = n.x - comx;
    let dy = n.y - comy;
    let d2 = dx * dx + dy * dy;
    if (cell.body) {
      if (cell.body === n) return;
      if (d2 < 0.01) { dx = Math.random() - 0.5; dy = Math.random() - 0.5; d2 = 0.01; }
      const d = Math.sqrt(d2);
      const f = (this._repel / d2) * alpha;
      n.vx += (dx / d) * f; n.vy += (dy / d) * f;
      return;
    }
    if ((cell.size * cell.size) / d2 < this._theta2) {
      if (d2 < 0.01) d2 = 0.01;
      const d = Math.sqrt(d2);
      const f = (this._repel * cell.mass / d2) * alpha;
      n.vx += (dx / d) * f; n.vy += (dy / d) * f;
      return;
    }
    if (cell.children) for (const c of cell.children) this._applyTreeForce(c, n, alpha);
  }

  // ── focus / distances ─────────────────────────────────────────
  _focusInfo() {
    const focus = this._animFocus;
    if (!focus || !this.nodeById.has(focus)) return null;
    if (this._distFocus === focus && this._distMap) {
      return { dist: this._distMap, kinds: this._kindFromFocus };
    }
    const dist = new Map([[focus, 0]]);
    let frontier = [focus];
    while (frontier.length) {
      const next = [];
      for (const id of frontier) {
        const d = dist.get(id);
        for (const nb of this.adjacency.get(id) || []) {
          if (!dist.has(nb)) { dist.set(nb, d + 1); next.push(nb); }
        }
      }
      frontier = next;
    }
    const kinds = new Map();
    for (const inc of this.incident.get(focus) || []) {
      if (!kinds.has(inc.other)) kinds.set(inc.other, inc);
    }
    this._distFocus = focus;
    this._distMap = dist;
    this._kindFromFocus = kinds;
    return { dist, kinds };
  }

  _distAlpha(dist, base, decay, floor) {
    if (dist === undefined || dist === Infinity) return floor;
    return Math.max(floor, base * Math.pow(decay, dist));
  }

  _setGraphFocus(id, { center = false } = {}) {
    this._graphFocusId = id && this.nodeById.has(id) ? id : null;
    this._navIdx = 0;
    if (center && this._graphFocusId) {
      const node = this.nodeById.get(this._graphFocusId);
      this.transform.x = this._worldW() / 2 - node.x * this.transform.k;
      this.transform.y = this._worldH() / 2 - node.y * this.transform.k;
    }
    this._persist();
    this._start();
    this._draw();
  }

  _toggleIsolate() {
    this.isolate = !this.isolate;
    this.overlay.querySelector('[data-act="isolate"]')?.classList.toggle('active', this.isolate);
    this._persist();
    this._draw();
  }

  _toggleLegend() {
    this.legendVisible = !this.legendVisible;
    this._syncLegendVisibility();
    this._persist();
    this._draw();
  }

  _syncLegendVisibility() {
    const hasContent = !!this.legend.innerHTML.trim();
    const show = this.legendVisible && hasContent;
    this.legend.classList.toggle('hidden', !show);
    this.overlay.querySelector('[data-act="legend"]')?.classList.toggle('active', show);
  }

  // ── rendering ─────────────────────────────────────────────────
  _dispX(node, now) {
    return node.x + (this._active ? Math.sin(now * DRIFT_SPEED + node._phase) * DRIFT_AMP : 0);
  }

  _dispY(node, now) {
    return node.y + (this._active ? Math.cos(now * DRIFT_SPEED + node._phase) * DRIFT_AMP : 0);
  }

  _draw() {
    const ctx = this.ctx;
    const W = this.canvas.width;
    const H = this.canvas.height;
    if (!W || !H) return;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, W, H);

    const { k, x, y } = this.transform;
    const dpr = this._dpr;
    ctx.setTransform(k * dpr, 0, 0, k * dpr, x * dpr, y * dpr);

    const info = this._focusInfo();
    const dist = info?.dist || null;
    const kinds = info?.kinds || null;
    const s = this._focusStrength;
    const focus = this._animFocus;
    const query = this.query;
    const labelColor = _cssVar('--fg', '#e6e6e6');
    const bg = _cssVar('--bg', '#111');
    const accent = _cssVar('--accent', '#6b8cff');
    const now = performance.now();
    const isolating = this.isolate && focus && dist;
    const visible = (id) => !isolating || (dist.get(id) ?? Infinity) <= ISOLATE_HOPS;

    // cache display positions for hit-testing
    for (const node of this.nodes) {
      node._sx = this._dispX(node, now);
      node._sy = this._dispY(node, now);
    }

    ctx.lineCap = 'round';

    // ── Edges ──
    for (const e of this.edges) {
      if (isolating && !(visible(e.from) && visible(e.to))) continue;
      const a = this.nodeById.get(e.from);
      const b = this.nodeById.get(e.to);
      const kd = edgeKind(e.kind);
      let d = Infinity;
      let target = 0.22;
      if (dist) {
        d = Math.min(dist.get(e.from) ?? Infinity, dist.get(e.to) ?? Infinity);
        target = d === Infinity ? 0.05 : this._distAlpha(d, 0.85, 0.5, 0.05);
      }
      const alpha = 0.22 + (target - 0.22) * s;
      const lit = d === 0 && s > 0.05;
      ctx.strokeStyle = kd.color;
      ctx.globalAlpha = alpha;
      ctx.lineWidth = (lit ? 1 + 0.9 * s : 1) / k;
      if (lit) { ctx.shadowColor = kd.color; ctx.shadowBlur = 6 / k; }
      ctx.beginPath();
      ctx.moveTo(a._sx, a._sy);
      ctx.lineTo(b._sx, b._sy);
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Direction arrow + kind glyph on edges touching the focused node.
      if (lit && k > 0.35) {
        this._drawArrow(a, b, kd.color, alpha, k);
        this._drawEdgeGlyph(a, b, kd, alpha, k, bg);
      }
    }
    ctx.globalAlpha = 1;

    // ── Nodes ──
    const showAllLabels = this.nodes.length <= 35 && k > 1.6;
    const labelCandidates = [];
    for (const node of this.nodes) {
      if (!visible(node.id)) continue;
      const r = this._nodeRadius(node);
      const hops = dist ? dist.get(node.id) : 0;
      const isFocus = node.id === focus;
      const matches = query && node.title.toLowerCase().includes(query);
      // Keep dimmed nodes readable — neighbours stay mostly solid, far nodes
      // only soft-fade (was 0.55 / 0.12, which read as too transparent).
      const targetA = dist ? this._distAlpha(hops, 1, 0.78, 0.38) : 1;
      let alpha = 1 + (targetA - 1) * s;
      if (query && !matches) alpha = Math.min(alpha, 0.38);
      const color = _typeColor(node.type);

      if ((isFocus || node.id === this.selectedId)) {
        ctx.save();
        ctx.globalAlpha = Math.max(alpha, 0.85);
        ctx.shadowColor = color;
        ctx.shadowBlur = 16 / k;
        ctx.beginPath();
        ctx.arc(node._sx, node._sy, r, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
        ctx.restore();
      }

      ctx.globalAlpha = alpha;
      ctx.beginPath();
      ctx.arc(node._sx, node._sy, r, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();

      if (node.id === this.selectedId) {
        ctx.lineWidth = 2.5 / k; ctx.strokeStyle = accent; ctx.globalAlpha = Math.max(alpha, 0.9); ctx.stroke();
      } else if (matches) {
        ctx.lineWidth = 2 / k; ctx.strokeStyle = accent; ctx.stroke();
      } else {
        ctx.lineWidth = 1.2 / k; ctx.strokeStyle = bg; ctx.stroke();
      }

      // Relationship motif badge on the focus node's direct neighbours.
      if (kinds && s > 0.4 && hops === 1 && kinds.has(node.id)) {
        this._drawKindBadge(node, r, edgeKind(kinds.get(node.id).kind), Math.max(alpha, 0.9), k, bg);
      }

      if ((isFocus || matches || showAllLabels) && alpha > 0.25) {
        labelCandidates.push({
          node, r,
          text: _sanitizeGraphLabel(node.title, isFocus || matches ? 32 : 22),
          alpha: isFocus || matches ? 1 : Math.min(0.9, alpha + 0.1),
          priority: isFocus ? 4 : (node.id === this.selectedId || matches ? 3 : 1 + Math.min(2, (node.degree || 0) / 6)),
          forced: isFocus || matches,
        });
      }
      ctx.globalAlpha = 1;
    }

    // ── Labels with collision avoidance + halo ──
    const fontPx = Math.max(9, 11 / k);
    ctx.font = `${fontPx}px system-ui, -apple-system, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.lineJoin = 'round';
    const padX = 2 / k;
    const padY = 1.5 / k;
    const overlaps = (a, b) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
    const reserved = this._reservedWorldRects();
    const placed = [...reserved];
    labelCandidates.sort((a, b) => b.priority - a.priority);
    for (const cand of labelCandidates) {
      const w = ctx.measureText(cand.text).width;
      const gap = 2 / k;
      const placements = [
        { x: cand.node._sx, y: cand.node._sy + cand.r + gap, align: 'center', baseline: 'top' },
        { x: cand.node._sx, y: cand.node._sy - cand.r - gap, align: 'center', baseline: 'bottom' },
        { x: cand.node._sx + cand.r + gap, y: cand.node._sy, align: 'left', baseline: 'middle' },
        { x: cand.node._sx - cand.r - gap, y: cand.node._sy, align: 'right', baseline: 'middle' },
      ];
      let drawn = false;
      for (const pos of placements) {
        const rect = this._labelRect(w, fontPx, pos, padX, padY);
        const hitsReserved = reserved.some((p) => overlaps(rect, p));
        const hitsPeer = placed.some((p) => overlaps(rect, p));
        if (hitsReserved) continue;
        if (hitsPeer && !cand.forced) continue;
        placed.push(rect);
        ctx.globalAlpha = cand.alpha;
        ctx.textAlign = pos.align;
        ctx.textBaseline = pos.baseline;
        ctx.lineWidth = 3 / k;
        ctx.strokeStyle = bg;
        ctx.strokeText(cand.text, pos.x, pos.y);
        ctx.fillStyle = labelColor;
        ctx.fillText(cand.text, pos.x, pos.y);
        drawn = true;
        break;
      }
      if (!drawn && cand.forced) {
        // Last resort for focused/matched nodes: draw above the node even if
        // peers overlap, but never under the hint/legend/controls.
        const pos = placements[1];
        const rect = this._labelRect(w, fontPx, pos, padX, padY);
        if (!reserved.some((p) => overlaps(rect, p))) {
          placed.push(rect);
          ctx.globalAlpha = cand.alpha;
          ctx.textAlign = pos.align;
          ctx.textBaseline = pos.baseline;
          ctx.lineWidth = 3 / k;
          ctx.strokeStyle = bg;
          ctx.strokeText(cand.text, pos.x, pos.y);
          ctx.fillStyle = labelColor;
          ctx.fillText(cand.text, pos.x, pos.y);
        }
      }
    }
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.globalAlpha = 1;
    this._updateHint();
  }

  _labelRect(textW, fontPx, pos, padX, padY) {
    let x0; let x1; let y0; let y1;
    if (pos.baseline === 'top') {
      x0 = pos.x - textW / 2 - padX;
      x1 = pos.x + textW / 2 + padX;
      y0 = pos.y - padY;
      y1 = pos.y + fontPx + padY;
    } else if (pos.baseline === 'bottom') {
      x0 = pos.x - textW / 2 - padX;
      x1 = pos.x + textW / 2 + padX;
      y1 = pos.y + padY;
      y0 = pos.y - fontPx - padY;
    } else if (pos.align === 'left') {
      x0 = pos.x - padX;
      x1 = pos.x + textW + padX;
      y0 = pos.y - fontPx / 2 - padY;
      y1 = pos.y + fontPx / 2 + padY;
    } else {
      x1 = pos.x + padX;
      x0 = pos.x - textW - padX;
      y0 = pos.y - fontPx / 2 - padY;
      y1 = pos.y + fontPx / 2 + padY;
    }
    return { x0, y0, x1, y1 };
  }

  _drawArrow(a, b, color, alpha, k) {
    const ctx = this.ctx;
    const dx = b._sx - a._sx;
    const dy = b._sy - a._sy;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const rb = this._nodeRadius(b);
    const tipX = b._sx - ux * (rb + 2 / k);
    const tipY = b._sy - uy * (rb + 2 / k);
    const size = 6 / k;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    ctx.lineTo(tipX - ux * size - uy * size * 0.5, tipY - uy * size + ux * size * 0.5);
    ctx.lineTo(tipX - ux * size + uy * size * 0.5, tipY - uy * size - ux * size * 0.5);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  _drawEdgeGlyph(a, b, kd, alpha, k, bg) {
    const ctx = this.ctx;
    const mx = (a._sx + b._sx) / 2;
    const my = (a._sy + b._sy) / 2;
    const fp = 12 / k;
    ctx.save();
    ctx.globalAlpha = Math.min(1, alpha + 0.2);
    ctx.font = `${fp}px system-ui, -apple-system, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.lineJoin = 'round';
    ctx.lineWidth = 3 / k;
    ctx.strokeStyle = bg;
    ctx.strokeText(kd.glyph, mx, my);
    ctx.fillStyle = kd.color;
    ctx.fillText(kd.glyph, mx, my);
    ctx.restore();
  }

  _drawKindBadge(node, r, kd, alpha, k, bg) {
    const ctx = this.ctx;
    const br = 6 / k;
    const bx = node._sx + r * 0.75;
    const by = node._sy - r * 0.75;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.beginPath();
    ctx.arc(bx, by, br, 0, Math.PI * 2);
    ctx.fillStyle = kd.color;
    ctx.fill();
    ctx.lineWidth = 1.2 / k;
    ctx.strokeStyle = bg;
    ctx.stroke();
    ctx.font = `${9 / k}px system-ui, -apple-system, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = bg;
    ctx.fillText(kd.glyph, bx, by + 0.5 / k);
    ctx.restore();
  }

  // Bounding boxes (in world coords) of the floating DOM overlays, so labels
  // can steer clear of them. Elements that are hidden / not laid out are
  // skipped.
  _reservedWorldRects() {
    const rects = [];
    const cRect = this.canvas.getBoundingClientRect();
    if (!cRect.width) return rects;
    const m = 10 / this.transform.k;
    for (const el of [this.hint, this.legend, this.overlay]) {
      if (!el || el.classList.contains('hidden')) continue;
      const r = el.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      const p0 = this._screenToWorld(r.left - cRect.left, r.top - cRect.top);
      const p1 = this._screenToWorld(r.right - cRect.left, r.bottom - cRect.top);
      rects.push({ x0: p0.x - m, y0: p0.y - m, x1: p1.x + m, y1: p1.y + m });
    }
    return rects;
  }

  _updateHint() {
    if (!this.nodes.length) { this.hint.textContent = ''; return; }
    this.hint.textContent =
      `${this.nodes.length} nodes · ${this.edges.length} links · click to trace · double-click to open`;
  }

  _buildLegend() {
    this.legend.innerHTML = LEGEND_EDGE_KINDS.map((k) => {
      const kd = EDGE_KINDS[k];
      return `<span class="kg-legend-item"><span class="kg-legend-glyph" style="color:${kd.color}">${kd.glyph}</span>${kd.label}</span>`;
    }).join('');
    this._syncLegendVisibility();
  }

  _renderEmptyState() {
    this.empty.innerHTML = `
      <div class="kg-graph-emptystate-title">No links yet</div>
      <p class="kg-graph-emptystate-msg">Add todos, documents, or memories, then rebuild the graph to see how everything connects.</p>
      ${this.onRebuild ? '<button type="button" class="admin-btn-sm kg-graph-emptystate-btn">Rebuild graph</button>' : ''}`;
    this.empty.querySelector('.kg-graph-emptystate-btn')?.addEventListener('click', () => this.onRebuild?.());
  }

  // ── geometry helpers ──────────────────────────────────────────
  _worldW() { return this.canvas.clientWidth || this.container.clientWidth || 600; }
  _worldH() { return this.canvas.clientHeight || this.container.clientHeight || 400; }

  _resize() {
    const w = this.container.clientWidth;
    const h = this.container.clientHeight;
    if (!w || !h) return;
    this._dpr = Math.max(1, window.devicePixelRatio || 1);
    this.canvas.width = Math.round(w * this._dpr);
    this.canvas.height = Math.round(h * this._dpr);
    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
    this._draw();
  }

  _screenToWorld(px, py) {
    const { k, x, y } = this.transform;
    return { x: (px - x) / k, y: (py - y) / k };
  }

  _pointerPos(ev) {
    const rect = this.canvas.getBoundingClientRect();
    return { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
  }

  _nodeAt(px, py) {
    const w = this._screenToWorld(px, py);
    let best = null;
    let bestD = Infinity;
    for (const node of this.nodes) {
      const r = this._nodeRadius(node) + 4;
      const dx = node._sx - w.x;
      const dy = node._sy - w.y;
      const d = dx * dx + dy * dy;
      if (d < r * r && d < bestD) { best = node; bestD = d; }
    }
    return best;
  }

  fit() {
    if (!this.nodes.length) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of this.nodes) {
      minX = Math.min(minX, n.x); minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x); maxY = Math.max(maxY, n.y);
    }
    const pad = 60;
    const w = this._worldW();
    const h = this._worldH();
    const bw = Math.max(1, maxX - minX);
    const bh = Math.max(1, maxY - minY);
    let k = Math.min((w - pad * 2) / bw, (h - pad * 2) / bh, 2.5);
    k = Math.max(0.15, k);
    // Honour a persisted zoom the first time we fit after a reload.
    if (this._savedK && !this._appliedSavedK) { k = this._savedK; this._appliedSavedK = true; }
    this.transform.k = k;
    this.transform.x = w / 2 - ((minX + maxX) / 2) * k;
    this.transform.y = h / 2 - ((minY + maxY) / 2) * k;
    this._draw();
  }

  _zoomBy(factor) {
    this._zoomAt(this._worldW() / 2, this._worldH() / 2, factor);
  }

  _zoomAt(px, py, factor) {
    const before = this._screenToWorld(px, py);
    this.transform.k = Math.min(4, Math.max(0.1, this.transform.k * factor));
    this.transform.x = px - before.x * this.transform.k;
    this.transform.y = py - before.y * this.transform.k;
    this._persist();
    this._draw();
  }

  // ── tooltip / menu ────────────────────────────────────────────
  _showTooltip(node, px, py) {
    const label = TYPE_LABELS[node.type === 'note' ? 'document' : node.type] || node.type || 'Node';
    this.tooltip.innerHTML =
      `<div class="kg-graph-tooltip-title">${_escape(node.title)}</div>` +
      `<div class="kg-graph-tooltip-meta">${_escape(label)} · ${node.degree} link${node.degree === 1 ? '' : 's'}</div>`;
    this.tooltip.classList.remove('hidden');
    const cw = this.container.clientWidth;
    const left = Math.min(px + 12, cw - this.tooltip.offsetWidth - 8);
    this.tooltip.style.left = Math.max(6, left) + 'px';
    this.tooltip.style.top = Math.max(6, py + 12) + 'px';
  }

  _hideTooltip() {
    this.tooltip.classList.add('hidden');
  }

  _showMenu(node, px, py) {
    const focusInc = (this._graphFocusId && this._graphFocusId !== node.id)
      ? (this.incident.get(node.id) || []).find((i) => i.other === this._graphFocusId)
      : null;
    const removable = focusInc && ['relates', 'derives_from', 'refutes', 'supports', 'depends_on', 'link', 'related'].includes(focusInc.kind);
    const focusTitle = removable ? (this.nodeById.get(this._graphFocusId)?.title || 'focus') : '';
    this.menu.innerHTML = `
      <button type="button" class="kg-graph-menu-item" data-act="open">Open</button>
      <button type="button" class="kg-graph-menu-item" data-act="addlink">Add link from here…</button>
      ${removable ? `<button type="button" class="kg-graph-menu-item" data-act="removelink">Remove link to “${_escape(_trunc(focusTitle, 22))}”</button>` : ''}`;
    this.menu.dataset.nodeId = node.id;
    if (removable) {
      this.menu.dataset.removeFrom = focusInc.dir === 'in' ? node.id : this._graphFocusId;
      this.menu.dataset.removeTo = focusInc.dir === 'in' ? this._graphFocusId : node.id;
      this.menu.dataset.removeKind = focusInc.kind;
    } else {
      delete this.menu.dataset.removeFrom;
    }
    this.menu.classList.remove('hidden');
    const cw = this.container.clientWidth;
    const ch = this.container.clientHeight;
    this.menu.style.left = Math.min(px, cw - this.menu.offsetWidth - 6) + 'px';
    this.menu.style.top = Math.min(py, ch - this.menu.offsetHeight - 6) + 'px';
  }

  _hideMenu() {
    this.menu.classList.add('hidden');
  }

  // ── interaction ───────────────────────────────────────────────
  _onWheel(ev) {
    ev.preventDefault();
    const p = this._pointerPos(ev);
    this._zoomAt(p.x, p.y, ev.deltaY < 0 ? 1.12 : 1 / 1.12);
  }

  _onPointerDown(ev) {
    this._hideMenu();
    this.canvas.focus?.();
    const p = this._pointerPos(ev);
    this._pointerStart = p;
    this._moved = false;
    const node = this._nodeAt(p.x, p.y);
    if (node) { this._dragNode = node; this._reheat(0.3); }
    else { this._panning = true; }
    this.canvas.setPointerCapture?.(ev.pointerId);
  }

  _onPointerMove(ev) {
    // These listeners live on window (so a drag can continue off-canvas), so
    // ignore movement entirely while the modal is closed.
    if (!this._active && !this._dragNode && !this._panning) return;
    const p = this._pointerPos(ev);
    if (this._dragNode) {
      const w = this._screenToWorld(p.x, p.y);
      this._dragNode.x = w.x; this._dragNode.y = w.y;
      this._dragNode.vx = 0; this._dragNode.vy = 0;
      this._moved = true;
      this._hideTooltip();
      this._reheat(0.2);
      return;
    }
    if (this._panning) {
      this.transform.x += p.x - this._pointerStart.x;
      this.transform.y += p.y - this._pointerStart.y;
      this._pointerStart = p;
      this._moved = true;
      this._hideTooltip();
      this._persist();
      this._draw();
      return;
    }
    // Hover only when the pointer is actually over the canvas.
    const overCanvas = ev.target === this.canvas;
    const node = overCanvas ? this._nodeAt(p.x, p.y) : null;
    const id = node ? node.id : null;
    if (id !== this.hoverId) {
      this.hoverId = id;
      this.canvas.style.cursor = id ? 'pointer' : 'grab';
      this._start();
      this._draw();
    }
    if (node) this._showTooltip(node, p.x, p.y);
    else this._hideTooltip();
  }

  _onPointerUp(ev) {
    const wasNode = this._dragNode;
    const wasPan = this._panning;
    this._dragNode = null;
    this._panning = false;
    if (!wasNode && !wasPan) return;
    if (wasNode && !this._moved) {
      this.selectedId = wasNode.id;
      this._setGraphFocus(wasNode.id);
      this.onSelect(wasNode.id);
    } else if (wasNode) {
      this._reheat(0.25);
    } else if (wasPan && !this._moved) {
      this._setGraphFocus(null);
    }
    this._moved = false;
  }

  _onDblClick(ev) {
    const p = this._pointerPos(ev);
    const node = this._nodeAt(p.x, p.y);
    if (node) { ev.preventDefault(); this.onOpen(node.id); }
  }

  _onContextMenu(ev) {
    const p = this._pointerPos(ev);
    const node = this._nodeAt(p.x, p.y);
    if (!node) return;
    ev.preventDefault();
    this._hideTooltip();
    this._showMenu(node, p.x, p.y);
  }

  _onDocClick(ev) {
    if (this.menu.classList.contains('hidden')) return;
    const item = ev.target.closest('.kg-graph-menu-item');
    if (item && this.menu.contains(item)) {
      const id = this.menu.dataset.nodeId;
      const act = item.dataset.act;
      if (act === 'open') this.onOpen(id);
      else if (act === 'addlink') this.onAddLink(id);
      else if (act === 'removelink') {
        this.onRemoveLink(this.menu.dataset.removeFrom, this.menu.dataset.removeTo, this.menu.dataset.removeKind);
      }
    }
    this._hideMenu();
  }

  _onKeyDown(ev) {
    if (ev.key === 'Escape') {
      if (this._graphFocusId) {
        ev.stopPropagation();
        ev.preventDefault();
        this._setGraphFocus(null);
      }
      return;
    }
    if (ev.key === 'Enter') {
      const id = this._graphFocusId || this.selectedId;
      if (id) { ev.preventDefault(); this.onOpen(id); }
      return;
    }
    if (ev.key === 'l' || ev.key === 'L') {
      ev.preventDefault();
      this._toggleLegend();
      return;
    }
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown' || ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') {
      const anchor = this._graphFocusId || this.selectedId;
      const neighbours = anchor ? [...(this.adjacency.get(anchor) || [])] : this.nodes.map((n) => n.id);
      if (!neighbours.length) return;
      ev.preventDefault();
      const step = (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') ? 1 : -1;
      this._navIdx = ((this._navIdx + step) % neighbours.length + neighbours.length) % neighbours.length;
      const nextId = neighbours[this._navIdx];
      this.selectedId = nextId;
      this._setGraphFocus(nextId, { center: true });
      this.onSelect(nextId);
    }
  }
}

function _escape(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _trunc(s, n) {
  s = String(s || '');
  return s.length > n ? s.slice(0, n - 1) + '…' : s;
}

export default { KnowledgeGraphView };
