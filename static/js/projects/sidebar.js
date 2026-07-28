/**
 * Projects sidebar — list chrome parity with Chats (P1).
 * Overflow sort menu, bulk select/archive, per-row context menus, meta lines.
 */
import Storage from '../storage.js';
import uiModule from '../ui.js';
import { mountEmptyState } from '../ui/feedback.js';

const API_BASE = window.API_BASE || window.location.origin;
export const PROJECT_SORT_KEY = 'odysseus-project-sort';
const META_TTL_MS = 30000;

const FOLDER_ICON =
  '<svg class="project-list-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg>';

let _sortMode = Storage.get(PROJECT_SORT_KEY) || 'active';
let _selectMode = false;
let _selectedIds = new Set();
let _metaCache = new Map();
let _handlers = null;

function _relativeTime(ts) {
  if (!ts) return '';
  const then = typeof ts === 'number' ? ts * 1000 : Date.parse(ts);
  if (!then || Number.isNaN(then)) return '';
  const diff = Date.now() - then;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(then).toLocaleDateString();
}

function _metaLine(project) {
  const parts = [];
  const cached = _metaCache.get(project.id);
  if (cached?.links != null) {
    const n = cached.links;
    parts.push(`${n} link${n === 1 ? '' : 's'}`);
  }
  const rel = _relativeTime(project.updated_at);
  if (rel) parts.push(rel);
  return parts.join(' · ');
}

export function recordProjectLinkCount(projectId, count) {
  if (!projectId) return;
  _metaCache.set(projectId, { links: count, at: Date.now() });
}

export function getSortMode() {
  return _sortMode;
}

export function setSortMode(mode) {
  if (mode === 'active' || mode === 'name') {
    _sortMode = mode;
    Storage.set(PROJECT_SORT_KEY, mode);
  } else {
    _sortMode = 'active';
    Storage.remove(PROJECT_SORT_KEY);
  }
}

export function sortProjects(projects) {
  const list = [...(projects || [])];
  if (_sortMode === 'name') {
    list.sort((a, b) => (a.title || a.id || '').localeCompare(b.title || b.id || '', undefined, { sensitivity: 'base' }));
    return list;
  }
  list.sort((a, b) => {
    const ta = a.updated_at || a.created_at || 0;
    const tb = b.updated_at || b.created_at || 0;
    return tb - ta;
  });
  return list;
}

export function isSelectMode() {
  return _selectMode;
}

export function exitSelectMode() {
  _selectMode = false;
  _selectedIds.clear();
  const bulkBar = document.getElementById('project-bulk-bar');
  bulkBar?.classList.add('hidden');
  document.querySelectorAll('.project-select-cb').forEach((el) => el.remove());
  _updateBulkButtons();
}

function _updateBulkButtons() {
  const count = _selectedIds.size;
  const archiveBtn = document.getElementById('project-bulk-archive');
  if (archiveBtn) {
    archiveBtn.disabled = count === 0;
    archiveBtn.style.opacity = count === 0 ? '0.2' : '';
  }
}

function _enterSelectMode() {
  _selectMode = true;
  _selectedIds.clear();
  document.getElementById('project-bulk-bar')?.classList.remove('hidden');
  document.getElementById('project-sort-dropdown').style.display = 'none';
  _handlers?.onListRender?.();
}

function _toggleSelectId(projectId, checked) {
  if (checked) _selectedIds.add(projectId);
  else _selectedIds.delete(projectId);
  _updateBulkButtons();
}

function _statusBadgeEl(project) {
  const status = project?.working_dir_status || '';
  if (status === 'ok') return null;
  const span = document.createElement('span');
  span.className = `project-status project-status-${status}`;
  span.textContent = status;
  return span;
}

function _positionDropdown(dd, anchor) {
  const rect = anchor.getBoundingClientRect();
  dd.style.position = 'fixed';
  dd.style.left = `${rect.left}px`;
  dd.style.top = `${rect.bottom + 4}px`;
  dd.style.right = 'auto';
  dd.style.display = 'block';
  dd.style.zIndex = '1000';
  requestAnimationFrame(() => {
    const mr = dd.getBoundingClientRect();
    if (mr.bottom > window.innerHeight - 8) dd.style.top = `${rect.top - mr.height - 4}px`;
    if (mr.right > window.innerWidth - 8) {
      dd.style.left = 'auto';
      dd.style.right = '8px';
    }
  });
}

function _closeDropdowns(except) {
  document.querySelectorAll('.project-dropdown').forEach((d) => {
    if (d !== except) d.style.display = 'none';
  });
}

function _buildRowMenu(project, row) {
  const dd = document.createElement('div');
  dd.className = 'dropdown project-dropdown project-dropdown-menu';
  dd.style.display = 'none';

  const icon = (svg) => {
    const s = document.createElement('span');
    s.className = 'dropdown-icon';
    s.innerHTML = svg;
    return s;
  };

  const renameItem = document.createElement('div');
  renameItem.className = 'dropdown-item-compact';
  renameItem.appendChild(icon('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>'));
  const renameSpan = document.createElement('span');
  renameSpan.textContent = 'Rename';
  renameItem.appendChild(renameSpan);
  renameItem.addEventListener('click', async (e) => {
    e.stopPropagation();
    dd.style.display = 'none';
    await _handlers?.onRename?.(project.id);
  });

  const dirItem = document.createElement('div');
  dirItem.className = 'dropdown-item-compact';
  dirItem.appendChild(icon('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>'));
  const dirSpan = document.createElement('span');
  dirSpan.textContent = 'Change folder';
  dirItem.appendChild(dirSpan);
  dirItem.addEventListener('click', async (e) => {
    e.stopPropagation();
    dd.style.display = 'none';
    await _handlers?.onChangeDir?.(project.id);
  });

  const archiveItem = document.createElement('div');
  archiveItem.className = 'dropdown-item-compact dropdown-item-danger';
  archiveItem.appendChild(icon('<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="21 8 21 21 3 21 3 8"/><rect x="1" y="3" width="22" height="5"/><line x1="10" y1="12" x2="14" y2="12"/></svg>'));
  const archiveSpan = document.createElement('span');
  archiveSpan.textContent = 'Archive';
  archiveItem.appendChild(archiveSpan);
  archiveItem.addEventListener('click', async (e) => {
    e.stopPropagation();
    dd.style.display = 'none';
    await _handlers?.onArchive?.(project.id);
  });

  dd.appendChild(renameItem);
  dd.appendChild(dirItem);
  dd.appendChild(archiveItem);
  document.body.appendChild(dd);
  row._projectDropdown = dd;
  return dd;
}

function _bindRowInteractions(row, project) {
  const menuBtn = row.querySelector('.project-menu-btn');
  const dd = row._projectDropdown || _buildRowMenu(project, row);

  menuBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = dd.style.display === 'block';
    _closeDropdowns();
    if (!open) _positionDropdown(dd, menuBtn);
  });

  let longPressTimer = null;
  let touchMoved = false;
  let longPressed = false;

  row.addEventListener('touchstart', () => {
    touchMoved = false;
    longPressed = false;
    if (window.innerWidth > 768) return;
    longPressTimer = setTimeout(() => {
      longPressed = true;
      if (navigator.vibrate) navigator.vibrate(30);
      _closeDropdowns();
      _positionDropdown(dd, row);
      const close = (ev) => {
        if (!dd.contains(ev.target)) {
          dd.style.display = 'none';
          document.removeEventListener('click', close, true);
        }
      };
      setTimeout(() => document.addEventListener('click', close, true), 100);
    }, 500);
  }, { passive: true });

  row.addEventListener('touchmove', () => {
    touchMoved = true;
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  }, { passive: true });

  row.addEventListener('touchend', () => {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
  }, { passive: true });

  const activate = (e) => {
    if (e.target.closest('.project-menu-btn') || e.target.closest('.project-dropdown') || e.target.closest('.project-select-cb')) return;
    if (touchMoved || longPressed) {
      touchMoved = false;
      longPressed = false;
      return;
    }
    if (_selectMode) {
      const dot = row.querySelector('.project-select-cb');
      if (dot) dot.click();
      return;
    }
    _handlers?.onOpen?.(project.id);
  };

  row.addEventListener('click', activate);
  row.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter' && e.key !== ' ') return;
    if (e.target !== row) return;
    e.preventDefault();
    activate(e);
  });
}

function _createListRow(project, openId) {
  // Use a div (like session rows) so the overflow menu can be a real <button>
  // without nested-button HTML, which browsers rewrite and break layout.
  const row = document.createElement('div');
  row.className = `list-item project-list-item${project.id === openId ? ' active' : ''}`;
  row.dataset.projectId = project.id;
  row.setAttribute('role', 'option');
  row.tabIndex = 0;

  if (_selectMode) {
    const dot = document.createElement('span');
    dot.className = 'project-select-cb session-select-cb';
    dot.textContent = '○';
    dot._checked = _selectedIds.has(project.id);
    if (dot._checked) {
      dot.textContent = '●';
      dot.style.opacity = '1';
      dot.style.color = 'var(--accent, var(--red))';
    }
    dot.addEventListener('click', (e) => {
      e.stopPropagation();
      dot._checked = !dot._checked;
      dot.textContent = dot._checked ? '●' : '○';
      dot.style.opacity = dot._checked ? '1' : '0.4';
      dot.style.color = dot._checked ? 'var(--accent, var(--red))' : '';
      _toggleSelectId(project.id, dot._checked);
    });
    row.appendChild(dot);
  }

  const iconWrap = document.createElement('span');
  iconWrap.className = 'project-list-icon-wrap';
  iconWrap.innerHTML = FOLDER_ICON;
  row.appendChild(iconWrap);

  const body = document.createElement('span');
  body.className = 'grow project-list-body';

  const titleRow = document.createElement('span');
  titleRow.className = 'project-list-title-row';

  const title = document.createElement('span');
  title.className = 'project-list-title text-ellipsis';
  title.textContent = project.title || project.id;
  title.title = project.title || project.id;
  titleRow.appendChild(title);

  if (project.working_dir_warning) {
    const warn = document.createElement('span');
    warn.className = 'project-warn-dot';
    warn.textContent = '!';
    warn.title = project.working_dir_warning;
    titleRow.appendChild(warn);
  }

  const badge = _statusBadgeEl(project);
  if (badge) titleRow.appendChild(badge);

  body.appendChild(titleRow);

  const meta = _metaLine(project);
  if (meta) {
    const metaEl = document.createElement('span');
    metaEl.className = 'project-list-meta';
    metaEl.textContent = meta;
    body.appendChild(metaEl);
  }

  row.appendChild(body);

  const menuBtn = document.createElement('button');
  menuBtn.type = 'button';
  menuBtn.className = 'hamburger project-menu-btn';
  menuBtn.setAttribute('aria-label', 'Project actions');
  menuBtn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="12" cy="19" r="1.8"/></svg>';
  row.appendChild(menuBtn);

  _bindRowInteractions(row, project);
  return row;
}

export function renderProjectList(listEl, projects, openId) {
  if (!listEl) return;
  listEl.replaceChildren();

  if (!projects?.length) {
    mountEmptyState(listEl, {
      kind: 'setup',
      title: 'No projects yet',
      message: 'Create a project to link papers and code in one workspace.',
      actionLabel: 'New project',
      onAction: () => _handlers?.onCreate?.(),
    });
    return;
  }

  for (const project of sortProjects(projects)) {
    listEl.appendChild(_createListRow(project, openId));
  }
}

async function _hydrateMeta(projects) {
  const now = Date.now();
  const pending = (projects || []).filter((p) => {
    const c = _metaCache.get(p.id);
    return !c || now - c.at >= META_TTL_MS;
  });
  if (!pending.length) return;

  await Promise.all(pending.map(async (p) => {
    try {
      const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(p.id)}/links`, {
        credentials: 'same-origin',
      });
      if (!res.ok) return;
      const data = await res.json();
      const outgoing = data.outgoing?.length || 0;
      const incoming = data.incoming?.length || 0;
      _metaCache.set(p.id, { links: outgoing + incoming, at: Date.now() });
    } catch {
      /* ignore */
    }
  }));
  _handlers?.onListRender?.();
}

function _syncSortChecks() {
  const dropdown = document.getElementById('project-sort-dropdown');
  const sortBtn = document.getElementById('project-sort-btn');
  if (!dropdown) return;
  dropdown.querySelectorAll('.sort-option').forEach((o) => {
    let check = o.querySelector('.sort-check');
    if (!check) {
      check = document.createElement('span');
      check.className = 'sort-check';
      check.style.cssText = 'float:right;font-size:20px;line-height:1;position:relative;top:3px;color:var(--accent, var(--red));';
      check.textContent = '\u2022';
      o.appendChild(check);
    }
    check.style.opacity = o.dataset.sort === _sortMode ? '1' : '0';
  });
  sortBtn?.classList.toggle('active', !!_sortMode);
}

export function initProjectSidebar(handlers) {
  _handlers = handlers;

  const sortBtn = document.getElementById('project-sort-btn');
  const sortDropdown = document.getElementById('project-sort-dropdown');
  if (sortBtn && sortDropdown) {
    sortBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      sortDropdown.style.display = sortDropdown.style.display === 'block' ? 'none' : 'block';
      _syncSortChecks();
    });
    document.addEventListener('click', () => { sortDropdown.style.display = 'none'; });
    sortDropdown.addEventListener('click', (e) => e.stopPropagation());

    sortDropdown.querySelectorAll('.sort-option').forEach((opt) => {
      opt.addEventListener('click', () => {
        const mode = opt.dataset.sort;
        if (_sortMode === mode) {
          setSortMode('active');
          uiModule.showToast?.('Sorted: last active');
        } else {
          setSortMode(mode);
          uiModule.showToast?.(`Sorted: ${opt.textContent.trim().toLowerCase()}`);
        }
        sortDropdown.style.display = 'none';
        _handlers?.onListRender?.();
        _syncSortChecks();
      });
    });
    _syncSortChecks();
  }

  document.getElementById('project-select-from-dropdown')?.addEventListener('click', () => {
    _enterSelectMode();
  });

  document.getElementById('project-bulk-cancel')?.addEventListener('click', () => exitSelectMode());

  document.getElementById('project-bulk-archive')?.addEventListener('click', async () => {
    if (!_selectedIds.size) return;
    const n = _selectedIds.size;
    if (!await uiModule.styledConfirm(
      `Archive ${n} project${n === 1 ? '' : 's'}? They will be hidden from the list.`,
      { confirmText: 'Archive', danger: true },
    )) return;
    const ids = [..._selectedIds];
    exitSelectMode();
    for (const id of ids) {
      await _handlers?.onArchive?.(id, { bulk: true, quiet: true });
    }
    await _handlers?.onRefresh?.();
    uiModule.showToast?.(`Archived ${n} project${n === 1 ? '' : 's'}`);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && _selectMode) exitSelectMode();
  });

  document.addEventListener('click', () => _closeDropdowns());
}

export function scheduleMetaHydration(projects) {
  void _hydrateMeta(projects);
}

export function toggleSelectAll(select) {
  document.querySelectorAll('.project-list-item[data-project-id]').forEach((row) => {
    const cb = row.querySelector('.project-select-cb');
    const id = row.dataset.projectId;
    if (!cb || !id) return;
    cb._checked = !!select;
    cb.textContent = select ? '●' : '○';
    cb.style.opacity = select ? '1' : '0.4';
    cb.style.color = select ? 'var(--accent, var(--red))' : '';
    _toggleSelectId(id, !!select);
  });
}

export default {
  initProjectSidebar,
  renderProjectList,
  sortProjects,
  getSortMode,
  setSortMode,
  recordProjectLinkCount,
  scheduleMetaHydration,
  toggleSelectAll,
  isSelectMode,
  exitSelectMode,
};
