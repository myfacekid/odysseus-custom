/**
 * tileManager.js — desktop window tiling for tool modals and tile-windows.
 *
 * Contract (any of these host shapes):
 *   1. Classic: `.modal` / `.research-overlay` → `.modal-content` / `.research-pane`
 *   2. Tagged:  `[data-tile-window="1"]` / `.tile-window` →
 *               `.tile-window-content` | `.modal-content` | `.research-pane` |
 *               `.doc-editor-pane` | `.notes-pane` | the host itself
 *
 * Drag starts on `.modal-header` (or `.tile-window-header`). Header buttons are
 * skipped. Shows a translucent ghost when the cursor nears a snap zone; on
 * release, snaps the content with a springy animation.
 *
 * Active zones (all durable windows):
 *   - y ≤ 0              → fullscreen (covers sidebar)
 *   - top strip          → maximize (safe area next to sidebar/rail)
 *   - right edge         → right half
 *   - bottom edge        → bottom half
 *   - left edge          → left half (within safe area next to sidebar/rail)
 *
 * Multi-tile composition: when bottom-half is occupied, left/right shrink to
 * the top half so L|R|bottom never overlap. Vacating bottom restores full height.
 *
 * Chat insets: left/right compose occupancy drives body/main-column padding so
 * chat fills the leftover region (same 160ms curve as right-dock). Left uses
 * --tile-inset-left on the main column (rail/sidebar stay put); right reuses
 * --right-dock-w. Bottom-half tiles overlay without pushing chat so the
 * composer/toolbar stays put.
 *
 * Corner quarters stay disabled. Mobile (≤768px) is excluded.
 *
 * Occupancy: each zone has at most one owner; snapping into an occupied zone
 * evicts the previous window (unsnap). Ctrl+Shift+T → tileAllOpenWindows().
 */

const EDGE_THRESHOLD_PX = 32;
const TOP_FULL_STRIP_PX = 8;

/** Host ids → allowed zone names. Empty / missing = all active zones. */
const ZONE_ALLOWLIST = {};

const HOST_SELECTOR = '.modal, .research-overlay, [data-tile-window="1"], .tile-window';
const CONTENT_SELECTOR = [
  '.tile-window-content',
  '.modal-content',
  '.research-pane',
  '.doc-editor-pane',
  '.notes-pane',
].join(', ');
const HEADER_SELECTOR = '.modal-header, .tile-window-header, .notes-pane-header, .ge-adj-head, .ge-fx-popup-head, .ge-history-head, .doc-version-panel-header';
const SNAPPED_SELECTOR = [
  '.modal-content[data-_tile-zone]',
  '.research-pane[data-_tile-zone]',
  '.tile-window-content[data-_tile-zone]',
  '.doc-editor-pane[data-_tile-zone]',
  '.notes-pane[data-_tile-zone]',
  '[data-tile-window="1"][data-_tile-zone]',
  '.tile-window[data-_tile-zone]',
].join(', ');

const COMPOSE_ZONES = new Set(['left-half', 'right-half', 'bottom-half']);

let _ghost = null;
let _activeZone = null;
let _tracking = null; // { content, startX, startY, willUnsnap }
let _dragSafeRect = null; // cached during an active tile drag
let _reflowing = false;

/** zoneName → content element currently occupying that zone. */
const _zoneOccupancy = new Map();

function _isDesktop() { return window.innerWidth > 768; }

/** Drop occupancy for disconnected, hidden, or externally-cleared windows. */
function _pruneOccupancy() {
  for (const [zone, el] of [..._zoneOccupancy.entries()]) {
    if (!el || !el.isConnected) {
      _zoneOccupancy.delete(zone);
      continue;
    }
    const claimed = el.dataset._tileZone;
    if (!claimed || (claimed !== zone && !String(claimed).startsWith('bottom-half-stack-'))) {
      _zoneOccupancy.delete(zone);
      continue;
    }
    const host = _hostForContent(el) || el;
    if (host.classList?.contains('hidden') || host.classList?.contains('modal-minimized')) {
      _zoneOccupancy.delete(zone);
      continue;
    }
    if (el.closest?.('.hidden, .modal-minimized, [hidden]')) {
      _zoneOccupancy.delete(zone);
    }
  }
}

/**
 * Non-overlapping rects for the multi-tile trio.
 * When `bottom-half` is (or will be) occupied, left/right use the top half only.
 */
function _composedRect(zoneName, safeRect = null, { bottomOccupied = null, exceptContent = null } = {}) {
  const safe = safeRect || _viewportSafeRect();
  const W = safe.right - safe.left;
  const H = safe.bottom - safe.top;
  let bottomBusy = bottomOccupied;
  if (bottomBusy == null) {
    _pruneOccupancy();
    const occ = _zoneOccupancy.get('bottom-half');
    bottomBusy = !!(occ && occ.isConnected && occ !== exceptContent);
  }

  switch (zoneName) {
    case 'fullscreen':
      return { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight };
    case 'maximize':
      return { left: safe.left, top: safe.top, width: W, height: H };
    case 'left-half':
      return {
        left: safe.left,
        top: safe.top,
        width: W / 2,
        height: bottomBusy ? H / 2 : H,
      };
    case 'right-half':
      return {
        left: safe.left + W / 2,
        top: safe.top,
        width: W / 2,
        height: bottomBusy ? H / 2 : H,
      };
    case 'bottom-half':
      return { left: safe.left, top: safe.top + H / 2, width: W, height: H / 2 };
    default:
      return null;
  }
}

function _rectForZoneName(zoneName, safeRect = null) {
  return _composedRect(zoneName, safeRect);
}

/** True when Tile All stacked extra windows inside bottom-half. */
function _hasBottomStacks() {
  return !!document.querySelector('[data-_tile-zone^="bottom-half-stack-"]');
}

function _hasLiveRightDock() {
  return !!document.querySelector('.modal-right-docked');
}

/** Rebuild compose/exclusive occupancy from DOM so reflow never misses siblings. */
function _reconcileOccupancyFromDom() {
  _pruneOccupancy();
  document.querySelectorAll(SNAPPED_SELECTOR).forEach((el) => {
    if (!el || !el.isConnected) return;
    const zone = el.dataset._tileZone;
    if (!zone || String(zone).startsWith('bottom-half-stack-')) return;
    if (!COMPOSE_ZONES.has(zone) && zone !== 'maximize' && zone !== 'fullscreen') return;
    const host = _hostForContent(el) || el;
    if (host.classList?.contains('hidden') || host.classList?.contains('modal-minimized')) return;
    if (el.closest?.('.hidden, .modal-minimized, [hidden]')) return;
    _zoneOccupancy.set(zone, el);
  });
}

/**
 * Push chat into the leftover region complementary to compose tiles.
 * Right reuses the edge-dock CSS path for identical 160ms animation.
 */
function _syncChatInsetsFromTiles() {
  const root = document.documentElement;
  const body = document.body;
  if (!body || !root) return;

  const clearHalfInsets = () => {
    root.style.setProperty('--tile-inset-left', '0px');
    root.style.setProperty('--tile-inset-right', '0px');
    root.style.setProperty('--tile-inset-bottom', '0px');
    body.classList.remove('tile-inset-left', 'tile-inset-right', 'tile-inset-bottom');
  };

  if (!_isDesktop()) {
    clearHalfInsets();
    if (!_hasLiveRightDock()) {
      body.classList.remove('right-dock-active');
      // Only strip the var when we were the ones driving it via tiles.
      if (!document.querySelector('.modal-right-docked')) {
        root.style.removeProperty('--right-dock-w');
      }
    }
    return;
  }

  _reconcileOccupancyFromDom();

  const exclusive = _zoneOccupancy.get('maximize') || _zoneOccupancy.get('fullscreen');
  let leftW = 0;
  let rightW = 0;

  if (!exclusive) {
    const safe = _viewportSafeRect();
    const bottomOcc = _zoneOccupancy.get('bottom-half');
    const leftOcc = _zoneOccupancy.get('left-half');
    const rightOcc = _zoneOccupancy.get('right-half');
    const bottomBusy = !!(bottomOcc && bottomOcc.isConnected);
    if (leftOcc && leftOcc.isConnected) {
      leftW = _composedRect('left-half', safe, { bottomOccupied: bottomBusy }).width;
    }
    if (rightOcc && rightOcc.isConnected) {
      rightW = _composedRect('right-half', safe, { bottomOccupied: bottomBusy }).width;
    }
  }

  // Bottom tiles overlay — do not pad body (keeps chat composer/toolbar in place).
  root.style.setProperty('--tile-inset-bottom', '0px');
  body.classList.remove('tile-inset-bottom');

  if (leftW > 0) {
    root.style.setProperty('--tile-inset-left', Math.round(leftW) + 'px');
    body.classList.add('tile-inset-left');
  } else {
    root.style.setProperty('--tile-inset-left', '0px');
    body.classList.remove('tile-inset-left');
  }

  if (rightW > 0) {
    const w = Math.round(rightW);
    root.style.setProperty('--tile-inset-right', w + 'px');
    root.style.setProperty('--right-dock-w', w + 'px');
    body.classList.add('tile-inset-right');
    body.classList.add('right-dock-active');
  } else {
    root.style.setProperty('--tile-inset-right', '0px');
    body.classList.remove('tile-inset-right');
    // Do not steal a live edge-dock push when no right-half tile is present.
    if (!_hasLiveRightDock()) {
      body.classList.remove('right-dock-active');
      root.style.removeProperty('--right-dock-w');
    }
  }
}

/** After occupancy changes, resize L/R so they don't overlap bottom. */
function _reflowComposedLayout(animate = true) {
  if (_reflowing) return;
  _reflowing = true;
  try {
    _reconcileOccupancyFromDom();
    const safe = _viewportSafeRect();
    const bottomOcc = _zoneOccupancy.get('bottom-half');
    const bottomBusy = !!(bottomOcc && bottomOcc.isConnected);
    const skipBottomResize = _hasBottomStacks();
    for (const zoneName of ['left-half', 'right-half', 'bottom-half']) {
      const el = _zoneOccupancy.get(zoneName);
      if (!el || !el.isConnected) {
        if (el) _zoneOccupancy.delete(zoneName);
        continue;
      }
      // Preserve Tile All row stacks inside bottom-half.
      if (zoneName === 'bottom-half' && skipBottomResize) continue;
      const rect = _composedRect(zoneName, safe, { bottomOccupied: bottomBusy, exceptContent: null });
      if (!rect) continue;
      if (animate) {
        el.style.transition = 'left 0.18s cubic-bezier(0.22, 1, 0.36, 1), top 0.18s cubic-bezier(0.22, 1, 0.36, 1), width 0.18s cubic-bezier(0.22, 1, 0.36, 1), height 0.18s cubic-bezier(0.22, 1, 0.36, 1)';
      } else {
        el.style.transition = 'none';
      }
      el.style.setProperty('position', 'fixed', 'important');
      el.style.setProperty('left', rect.left + 'px', 'important');
      el.style.setProperty('top', rect.top + 'px', 'important');
      el.style.setProperty('width', rect.width + 'px', 'important');
      el.style.setProperty('height', rect.height + 'px', 'important');
      el.style.setProperty('max-height', rect.height + 'px', 'important');
      el.style.setProperty('margin', '0', 'important');
      el.style.setProperty('transform', 'none', 'important');
      if (animate) {
        setTimeout(() => { el.style.transition = ''; }, 200);
      } else {
        el.style.transition = '';
      }
    }
    _syncChatInsetsFromTiles();
  } finally {
    _reflowing = false;
  }
}

/** Evict another window from `zoneName` (restore pre-snap or float offset). */
function _evictZoneOccupant(zoneName, exceptContent) {
  const occupant = _zoneOccupancy.get(zoneName);
  if (!occupant || occupant === exceptContent) return;
  if (!occupant.isConnected) {
    _zoneOccupancy.delete(zoneName);
    return;
  }
  _unsnap(occupant, { skipReflow: true });
  // If unsnap had no pre-snap snapshot, nudge so it isn't invisible under the new owner.
  if (!occupant.dataset._tileZone && !occupant.style.left) {
    const safe = _viewportSafeRect();
    occupant.style.position = 'fixed';
    occupant.style.left = (safe.left + 48) + 'px';
    occupant.style.top = (safe.top + 48) + 'px';
  }
}

function _clearOccupancyFor(content) {
  for (const [zone, el] of [..._zoneOccupancy.entries()]) {
    if (el === content) _zoneOccupancy.delete(zone);
  }
}

function _dockClassForSide(side) {
  return side === 'left' ? 'modal-left-docked' : 'modal-right-docked';
}

function _hasOtherDockedWindow(side, owner) {
  const cls = _dockClassForSide(side);
  return Array.from(document.querySelectorAll(`.${cls}`)).some((el) => {
    if (!el || el === owner) return false;
    if (owner && el.contains && el.contains(owner)) return false;
    if (owner && owner.contains && owner.contains(el)) return false;
    return true;
  });
}

function _clearDockSide(side, owner = null) {
  if (side !== 'left' && side !== 'right') return;
  if (_hasOtherDockedWindow(side, owner)) return;
  document.body.classList.remove(side === 'left' ? 'left-dock-active' : 'right-dock-active');
  document.documentElement.style.removeProperty(side === 'left' ? '--left-dock-w' : '--right-dock-w');
  if (side === 'left') {
    try { window._restoreSidebarIfRouteCollapsed?.(); } catch (_) {}
  }
}

function _ensureGhost() {
  if (_ghost) return _ghost;
  _ghost = document.createElement('div');
  _ghost.id = 'tile-ghost';
  document.body.appendChild(_ghost);
  return _ghost;
}

function _hideGhost() {
  if (_ghost) _ghost.classList.remove('visible');
}

function _showGhost(rect) {
  const g = _ensureGhost();
  g.style.left = rect.left + 'px';
  g.style.top  = rect.top  + 'px';
  g.style.width  = rect.width  + 'px';
  g.style.height = rect.height + 'px';
  g.classList.add('visible');
}

function _viewportSafeRect() {
  if (_dragSafeRect) return _dragSafeRect;
  const sidebar = document.getElementById('sidebar');
  const rail = document.querySelector('.icon-rail') || document.querySelector('#icon-rail');
  let leftEdge = 0;
  const sb = sidebar?.getBoundingClientRect();
  if (sb && sb.right > 0 && !sidebar.classList.contains('hidden')) leftEdge = Math.max(leftEdge, sb.right);
  const rr = rail?.getBoundingClientRect();
  if (rr && rr.right > 0) leftEdge = Math.max(leftEdge, rr.right);
  return {
    left: leftEdge + 4,
    top: 4,
    right: window.innerWidth - 4,
    bottom: window.innerHeight - 4,
  };
}

function _leftHalfAllowed() {
  // Left half uses the safe rect (already inset past sidebar/rail), so it is
  // always available for multi-tiling. Only block if another window already
  // owns the legacy left edge-dock strip (chat-push dock).
  return !_hasOtherDockedWindow('left', null);
}

function _hostForContent(content) {
  if (!content) return null;
  if (content.matches && content.matches(HOST_SELECTOR)) return content;
  return content.closest ? content.closest(HOST_SELECTOR) : null;
}

function _contentForHost(host) {
  if (!host) return null;
  if (host.matches && (
    host.matches('.doc-editor-pane, .notes-pane, .tile-window-content')
    || host.getAttribute?.('data-tile-window') === '1'
  ) && !host.querySelector?.('.modal-content, .research-pane, .tile-window-content')) {
    // Standalone pane that is both host and content (notes, doc editor, etc.)
    if (host.matches('.doc-editor-pane, .notes-pane') || host.classList.contains('tile-window')) {
      const inner = host.querySelector(CONTENT_SELECTOR);
      return inner || host;
    }
  }
  const found = host.querySelector?.(CONTENT_SELECTOR);
  return found || host;
}

function _zoneAllowed(host, zoneName) {
  if (!host || !host.id) return true;
  const allowed = ZONE_ALLOWLIST[host.id];
  if (!allowed || !allowed.length) return true;
  return allowed.includes(zoneName);
}

function _zoneForPointer(x, y, exceptContent = null) {
  const safe = _viewportSafeRect();
  const W = safe.right - safe.left;
  const H = safe.bottom - safe.top;

  if (y <= 0) {
    return { name: 'fullscreen', rect: { left: 0, top: 0, width: window.innerWidth, height: window.innerHeight } };
  }
  if (y <= safe.top + TOP_FULL_STRIP_PX) {
    return { name: 'maximize', rect: { left: safe.left, top: safe.top, width: W, height: H } };
  }

  // Prefer side edges over bottom when in a corner (clearer multi-tile intent).
  const nearRight = x >= safe.right - EDGE_THRESHOLD_PX;
  const nearLeft = x <= safe.left + EDGE_THRESHOLD_PX && _leftHalfAllowed();
  const nearBottom = y >= safe.bottom - EDGE_THRESHOLD_PX;

  if (nearRight && !nearBottom) {
    return {
      name: 'right-half',
      rect: _composedRect('right-half', safe, { exceptContent }),
    };
  }
  if (nearLeft && !nearBottom) {
    return {
      name: 'left-half',
      rect: _composedRect('left-half', safe, { exceptContent }),
    };
  }
  if (nearBottom) {
    return {
      name: 'bottom-half',
      rect: _composedRect('bottom-half', safe, { bottomOccupied: true, exceptContent }),
    };
  }
  // Corner: side wins if both edge thresholds hit
  if (nearRight) {
    return {
      name: 'right-half',
      rect: _composedRect('right-half', safe, { exceptContent }),
    };
  }
  if (nearLeft) {
    return {
      name: 'left-half',
      rect: _composedRect('left-half', safe, { exceptContent }),
    };
  }

  return null;
}

function _zoneForContent(content, x, y) {
  const host = _hostForContent(content);
  const zone = _zoneForPointer(x, y, content);
  if (!zone) return null;
  if (!_zoneAllowed(host, zone.name)) return null;
  return zone;
}

function _clearEdgeDockResidue(modal, content) {
  const hadDockState = !!(
    (modal && (modal.classList.contains('modal-left-docked') || modal.classList.contains('modal-right-docked')))
    || (content && (content._preDockSnapshot || content._dockSide || content._dockSuspended))
  );
  if (modal) {
    const hadLeft = modal.classList.contains('modal-left-docked');
    const hadRight = modal.classList.contains('modal-right-docked');
    modal.classList.remove('modal-left-docked', 'modal-right-docked');
    if (hadLeft) _clearDockSide('left', modal);
    if (hadRight) _clearDockSide('right', modal);
    if (modal._dockCloseWatcher) {
      try { modal._dockCloseWatcher.obs && modal._dockCloseWatcher.obs.disconnect(); } catch (_) {}
      try { modal._dockCloseWatcher.parentObs && modal._dockCloseWatcher.parentObs.disconnect(); } catch (_) {}
      delete modal._dockCloseWatcher;
    }
  }
  if (!content) return;
  if (content._leftDockNavObs) {
    try { content._leftDockNavObs.navObs.disconnect(); } catch (_) {}
    try { window.removeEventListener('resize', content._leftDockNavObs.reanchor); } catch (_) {}
    delete content._leftDockNavObs;
  }
  delete content._preDockSnapshot;
  delete content._dockSide;
  delete content._dockSuspended;
  if (hadDockState) {
    ['right', 'bottom', 'max-width', 'border-radius']
      .forEach(p => content.style.removeProperty(p));
  }
}

function _applySnap(content, rect, zoneName, opts = {}) {
  const animate = opts.animate !== false;
  const skipReflow = opts.skipReflow === true;
  const keepRect = opts.keepRect === true;
  const _modal = _hostForContent(content);
  const _fromRect = content.getBoundingClientRect();
  _clearEdgeDockResidue(_modal, content);

  // Occupancy: eviction before claiming this zone (no stacking).
  _evictZoneOccupant(zoneName, content);
  // Fullscreen / maximize are exclusive of half zones.
  if (zoneName === 'fullscreen' || zoneName === 'maximize') {
    for (const z of ['left-half', 'right-half', 'bottom-half', 'maximize', 'fullscreen']) {
      if (z === zoneName) continue;
      _evictZoneOccupant(z, content);
    }
  } else if (COMPOSE_ZONES.has(zoneName)) {
    _evictZoneOccupant('fullscreen', content);
    _evictZoneOccupant('maximize', content);
  }

  // Prefer composed geometry so L|R|bottom never overlap (unless caller
  // already computed a custom sub-rect, e.g. Tile All bottom stacks).
  if (COMPOSE_ZONES.has(zoneName) && !keepRect) {
    const bottomWillBe = zoneName === 'bottom-half'
      || !!(_zoneOccupancy.get('bottom-half') && _zoneOccupancy.get('bottom-half') !== content);
    rect = _composedRect(zoneName, _viewportSafeRect(), {
      bottomOccupied: bottomWillBe,
      exceptContent: content,
    }) || rect;
  }

  if (!content.dataset._tilePreSnap) {
    content.dataset._tilePreSnap = JSON.stringify({
      position: 'fixed',
      left:   content.style.left || (Math.round(_fromRect.left) + 'px'),
      top:    content.style.top  || (Math.round(_fromRect.top)  + 'px'),
      width:  content.style.width || (Math.round(_fromRect.width) + 'px'),
      height: content.style.height || (Math.round(_fromRect.height) + 'px'),
      maxHeight: content.style.maxHeight,
      transform: content.style.transform,
    });
  }
  // Leaving a previous zone frees it for others.
  const prevZone = content.dataset._tileZone;
  if (prevZone && prevZone !== zoneName && _zoneOccupancy.get(prevZone) === content) {
    _zoneOccupancy.delete(prevZone);
  }
  // Drop synthetic stack zones from a prior Tile All.
  if (prevZone && String(prevZone).startsWith('bottom-half-stack-')) {
    _clearOccupancyFor(content);
  }

  if (animate) {
    content.style.transition = 'left 0.18s cubic-bezier(0.22, 1, 0.36, 1), top 0.18s cubic-bezier(0.22, 1, 0.36, 1), width 0.18s cubic-bezier(0.22, 1, 0.36, 1), height 0.18s cubic-bezier(0.22, 1, 0.36, 1)';
  } else {
    content.style.transition = 'none';
  }
  content.style.setProperty('position', 'fixed', 'important');
  content.style.setProperty('left',   rect.left   + 'px', 'important');
  content.style.setProperty('top',    rect.top    + 'px', 'important');
  content.style.setProperty('width',  rect.width  + 'px', 'important');
  content.style.setProperty('height', rect.height + 'px', 'important');
  content.style.setProperty('max-height', rect.height + 'px', 'important');
  content.style.setProperty('margin', '0', 'important');
  content.style.setProperty('transform', 'none', 'important');
  // Keep tiled shells above inert modal overlays of other windows.
  const z = parseInt(content.style.zIndex || '0', 10);
  if (!z || z < 260) content.style.setProperty('z-index', '260');
  content.dataset._tileZone = zoneName;
  if (!String(zoneName).startsWith('bottom-half-stack-')) {
    _zoneOccupancy.set(zoneName, content);
  }
  if (animate) {
    setTimeout(() => { content.style.transition = ''; }, 200);
  } else {
    content.style.transition = '';
  }

  // Reflow siblings so L|R shrink/expand when bottom joins or leaves.
  if (!skipReflow && COMPOSE_ZONES.has(zoneName)) {
    _reflowComposedLayout(animate);
  } else if (!skipReflow) {
    // maximize / fullscreen / non-compose: still refresh chat insets
    _syncChatInsetsFromTiles();
  }
}

function _unsnap(content, opts = {}) {
  const skipReflow = opts.skipReflow === true;
  const pre = content.dataset._tilePreSnap;
  const wasCompose = COMPOSE_ZONES.has(content.dataset._tileZone)
    || String(content.dataset._tileZone || '').startsWith('bottom-half-stack-');
  _clearOccupancyFor(content);
  if (!pre) {
    delete content.dataset._tileZone;
    if (skipReflow) return;
    if (wasCompose) _reflowComposedLayout(true);
    else _syncChatInsetsFromTiles();
    return;
  }
  ['position', 'left', 'top', 'width', 'height', 'max-height', 'margin', 'transform']
    .forEach(p => content.style.removeProperty(p));
  try {
    const r = JSON.parse(pre);
    Object.assign(content.style, r);
  } catch {}
  if (!content.style.position) content.style.position = 'fixed';
  delete content.dataset._tilePreSnap;
  delete content.dataset._tileZone;
  if (skipReflow) return;
  if (wasCompose) _reflowComposedLayout(true);
  else _syncChatInsetsFromTiles();
}

function _findDragTarget(e) {
  const header = e.target.closest(HEADER_SELECTOR);
  if (!header) return null;
  if (e.target.closest('button')) return null;
  const host = header.closest(HOST_SELECTOR)
    || header.closest('.doc-editor-pane, .notes-pane')
    || (header.classList.contains('ge-adj-head') || header.classList.contains('ge-fx-popup-head')
      ? header.closest('.ge-adj-popup, .ge-fx-popup, .ge-transform-popup, .ge-inpaint-popup, #ge-history-panel')
      : null)
    || (header.classList.contains('doc-version-panel-header')
      ? header.closest('#doc-version-panel, .doc-version-panel')
      : null);
  if (!host) return null;
  // Photo / version panels may not use HOST_SELECTOR yet — treat self as content
  if (host.matches?.('.ge-adj-popup, .ge-fx-popup, .ge-transform-popup, .ge-inpaint-popup, #ge-history-panel, #doc-version-panel, .doc-version-panel')) {
    return host;
  }
  if (host.matches?.('.doc-editor-pane, .notes-pane')) return host;
  return _contentForHost(host);
}

document.addEventListener('pointerdown', (e) => {
  if (!_isDesktop()) return;
  const content = _findDragTarget(e);
  if (!content) return;

  // Cache safe rect for the duration of this drag (sidebar/rail queries are
  // expensive if repeated on every pointermove).
  _dragSafeRect = _viewportSafeRect();
  if (content.dataset._tileZone) {
    _tracking = { content, startX: e.clientX, startY: e.clientY, willUnsnap: true };
  } else {
    _tracking = { content, startX: e.clientX, startY: e.clientY, willUnsnap: false };
  }
});

document.addEventListener('pointermove', (e) => {
  if (!_tracking) return;
  if (!_isDesktop()) return;
  const dx = e.clientX - _tracking.startX;
  const dy = e.clientY - _tracking.startY;
  if (Math.hypot(dx, dy) < 6) return;

  if (_tracking.willUnsnap) {
    _unsnap(_tracking.content);
    _tracking.willUnsnap = false;
  }

  const zone = _zoneForContent(_tracking.content, e.clientX, e.clientY);
  if (zone) {
    _showGhost(zone.rect);
    _activeZone = zone;
  } else {
    _hideGhost();
    _activeZone = null;
  }
});

document.addEventListener('pointerup', () => {
  if (!_tracking) return;
  const t = _tracking;
  _tracking = null;
  _dragSafeRect = null;
  _hideGhost();
  if (_activeZone && _isDesktop()) {
    _applySnap(t.content, _activeZone.rect, _activeZone.name);
  }
  _activeZone = null;
});

document.addEventListener('pointercancel', () => {
  _tracking = null;
  _dragSafeRect = null;
  _hideGhost();
  _activeZone = null;
});

function _reclampAll(animate = false) {
  _reconcileOccupancyFromDom();
  const safe = _viewportSafeRect();
  const bottomOcc = _zoneOccupancy.get('bottom-half');
  const bottomBusy = !!(bottomOcc && bottomOcc.isConnected);
  const skipBottomResize = _hasBottomStacks();

  document.querySelectorAll(SNAPPED_SELECTOR).forEach(c => {
    const name = c.dataset._tileZone;
    if (!name) return;
    // Keep Tile All bottom stacks at their row geometry.
    if (String(name).startsWith('bottom-half-stack-')) return;
    if (name === 'bottom-half' && skipBottomResize) return;

    let r = null;
    if (COMPOSE_ZONES.has(name) || name === 'maximize' || name === 'fullscreen') {
      r = _composedRect(name, safe, { bottomOccupied: bottomBusy });
    }
    if (!r) return;
    if (animate) {
      c.style.transition = 'left 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), top 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), width 0.22s cubic-bezier(0.34, 1.56, 0.64, 1), height 0.22s cubic-bezier(0.34, 1.56, 0.64, 1)';
      setTimeout(() => { c.style.transition = ''; }, 250);
    }
    c.style.setProperty('left', r.left + 'px', 'important');
    c.style.setProperty('top',  r.top  + 'px', 'important');
    c.style.setProperty('width', r.width + 'px', 'important');
    c.style.setProperty('height', r.height + 'px', 'important');
    c.style.setProperty('max-height', r.height + 'px', 'important');
  });
  _syncChatInsetsFromTiles();
}

let _reclampPending = false;
function _reclampAllThrottled(animate) {
  if (_reclampPending) return;
  _reclampPending = true;
  requestAnimationFrame(() => {
    try { _reclampAll(animate); } finally { _reclampPending = false; }
  });
}

window.addEventListener('resize', () => _reclampAllThrottled(false));

function _watchSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) {
    requestAnimationFrame(_watchSidebar);
    return;
  }
  const mo = new MutationObserver(() => _reclampAllThrottled(true));
  mo.observe(sidebar, { attributes: true, attributeFilter: ['class'] });
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _watchSidebar);
} else {
  _watchSidebar();
}

export function previewZoneAt(x, y, target = null) {
  if (!_isDesktop()) { _hideGhost(); _activeZone = null; return null; }
  const content = target
    ? (target.querySelector ? (_contentForHost(target) || target.querySelector(CONTENT_SELECTOR) || target) : target)
    : null;
  const zone = content ? _zoneForContent(content, x, y) : _zoneForPointer(x, y);
  if (zone) { _showGhost(zone.rect); _activeZone = zone; }
  else { _hideGhost(); _activeZone = null; }
  return zone;
}

export function clearPreview() {
  _hideGhost();
  _activeZone = null;
}

export function snapModalToZone(modal, zone) {
  if (!modal || !zone) return;
  const content = modal.querySelector
    ? (_contentForHost(modal) || modal.querySelector(CONTENT_SELECTOR) || modal)
    : modal;
  if (!content) return;
  const host = _hostForContent(content) || modal;
  if (!_zoneAllowed(host, zone.name)) return;
  const rect = zone.rect || _rectForZoneName(zone.name);
  if (!rect) return;
  _applySnap(content, rect, zone.name);
}

/** Collect visible durable window contents eligible for Tile All. */
const _TILE_ALL_SKIP_IDS = new Set([
  'styled-confirm-overlay',
  'styled-prompt-overlay',
  'rename-session-modal',
  'rename-ai-modal',
  'custom-preset-modal',
  'kg-merge-modal',
]);

function _collectDurableContents() {
  const out = [];
  const seen = new Set();
  const push = (el) => {
    if (!el || seen.has(el) || !el.isConnected) return;
    const host = _hostForContent(el) || el;
    if (host.id && _TILE_ALL_SKIP_IDS.has(host.id)) return;
    if (el.id && _TILE_ALL_SKIP_IDS.has(el.id)) return;
    if (host.classList?.contains('hidden') || host.classList?.contains('modal-minimized')) return;
    if (el.closest?.('.hidden, .modal-minimized, [hidden]')) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    // Skip zero-size shells
    const r = el.getBoundingClientRect();
    if (r.width < 40 || r.height < 40) return;
    seen.add(el);
    out.push(el);
  };

  document.querySelectorAll('.modal:not(.hidden):not(.modal-minimized)').forEach((m) => {
    if (_TILE_ALL_SKIP_IDS.has(m.id)) return;
    push(_contentForHost(m) || m.querySelector('.modal-content'));
  });
  document.querySelectorAll('.research-overlay:not(.hidden) .research-pane').forEach(push);
  document.querySelectorAll('#doc-editor-pane, #notes-pane').forEach(push);
  // Promoted tile shells (toolbar palettes, version panel, GE floaters, etc.)
  document.querySelectorAll('[data-tile-window="1"]:not(.hidden)').forEach((host) => {
    if (host.matches('.modal, .research-overlay')) return; // already covered
    if (host.id === 'doc-editor-pane' || host.id === 'notes-pane') return;
    push(_contentForHost(host) || host.querySelector(CONTENT_SELECTOR) || host);
  });
  return out;
}

/**
 * Arrange all open durable windows: 1→left-half, 2→right-half,
 * remaining stacked as rows inside bottom-half.
 * Desktop only. Returns the number of windows tiled.
 */
export function tileAllOpenWindows() {
  if (!_isDesktop()) return 0;
  const windows = _collectDurableContents();
  if (!windows.length) return 0;

  const safe = _viewportSafeRect();
  const batch = { animate: false, skipReflow: true };

  // Clear prior occupancy so batch assignment doesn't thrash evictions.
  for (const el of windows) {
    const z = el.dataset._tileZone;
    if (z && _zoneOccupancy.get(z) === el) _zoneOccupancy.delete(z);
    if (z && String(z).startsWith('bottom-half-stack-')) delete el.dataset._tileZone;
  }

  if (windows.length === 1) {
    const rect = _rectForZoneName('maximize', safe);
    if (rect) _applySnap(windows[0], rect, 'maximize', batch);
    _syncChatInsetsFromTiles();
    return 1;
  }

  let left = windows[0] || null;
  let right = windows[1] || null;
  const rest = windows.slice(2);
  const bottomBusy = rest.length > 0;

  if (left) {
    _applySnap(left, _composedRect('left-half', safe, { bottomOccupied: bottomBusy }), 'left-half', batch);
  }
  if (right) {
    _applySnap(right, _composedRect('right-half', safe, { bottomOccupied: bottomBusy }), 'right-half', batch);
  }

  if (rest.length) {
    const bottom = _composedRect('bottom-half', safe, { bottomOccupied: true });
    const n = rest.length;
    const rowH = bottom.height / n;
    rest.forEach((el, i) => {
      const rect = {
        left: bottom.left + Math.min(i * 12, 36),
        top: bottom.top + i * rowH,
        width: bottom.width - Math.min(i * 12, 36),
        height: Math.max(100, rowH - 4),
      };
      if (i === 0) {
        _applySnap(el, rect, 'bottom-half', { ...batch, keepRect: true });
      } else {
        if (!el.dataset._tilePreSnap) {
          const r = el.getBoundingClientRect();
          el.dataset._tilePreSnap = JSON.stringify({
            position: 'fixed',
            left: Math.round(r.left) + 'px',
            top: Math.round(r.top) + 'px',
            width: Math.round(r.width) + 'px',
            height: Math.round(r.height) + 'px',
            maxHeight: el.style.maxHeight,
            transform: el.style.transform,
          });
        }
        const prev = el.dataset._tileZone;
        if (prev && _zoneOccupancy.get(prev) === el) _zoneOccupancy.delete(prev);
        el.style.transition = 'none';
        el.style.setProperty('position', 'fixed', 'important');
        el.style.setProperty('left', rect.left + 'px', 'important');
        el.style.setProperty('top', rect.top + 'px', 'important');
        el.style.setProperty('width', rect.width + 'px', 'important');
        el.style.setProperty('height', rect.height + 'px', 'important');
        el.style.setProperty('max-height', rect.height + 'px', 'important');
        el.style.setProperty('margin', '0', 'important');
        el.style.setProperty('transform', 'none', 'important');
        el.style.setProperty('z-index', String(260 + i));
        el.dataset._tileZone = 'bottom-half-stack-' + i;
      }
    });
  }

  // One composed pass so L|R match bottom occupancy without thrash.
  _reflowComposedLayout(false);
  return windows.length;
}

/** Mark an element as a tileable window host (idempotent). */
export function markTileWindow(el, { content = null } = {}) {
  if (!el) return;
  el.setAttribute('data-tile-window', '1');
  el.classList.add('tile-window');
  if (content && content !== el) {
    content.classList.add('tile-window-content');
  } else if (!el.querySelector('.tile-window-content, .modal-content, .research-pane')) {
    el.classList.add('tile-window-content');
  }
}

export { ZONE_ALLOWLIST, HOST_SELECTOR, CONTENT_SELECTOR, HEADER_SELECTOR };
