/**
 * Project file tree — depth boundary (Phase B).
 * Row actions mirror chat session menus: chevron menu, inline rename, no modals.
 */
import uiModule from '../ui.js';

const API_BASE = window.API_BASE || window.location.origin;
const esc = uiModule.esc;

const _renameIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>';
const _moveIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>';
const _deleteIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/></svg>';
const _menuChevron = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';

let _projectId = null;
let _container = null;
let _onFileSelect = null;
let _onPathChange = null;
let _onAfterRefresh = null;
let _expanded = new Set(['.']);
let _selectedPath = null;
let _loading = false;

function _icon(svg) {
  return `<span class="dropdown-icon">${svg}</span>`;
}

async function _listDir(path) {
  const q = path && path !== '.' ? `?path=${encodeURIComponent(path)}` : '';
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/files${q}`, {
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to list files');
  return data.entries || [];
}

async function _readFile(path) {
  const res = await fetch(
    `${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/file?path=${encodeURIComponent(path)}`,
    { credentials: 'same-origin' },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to read file');
  return data;
}

async function _writeFile(path, content = '') {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/file`, {
    method: 'PUT',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, content, create_dirs: true }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to write file');
  return data;
}

async function _mkdir(path) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/mkdir`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to create folder');
  return data;
}

async function _deletePath(path, recursive = false) {
  const q = new URLSearchParams({ path });
  if (recursive) q.set('recursive', 'true');
  const res = await fetch(
    `${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/file?${q.toString()}`,
    { method: 'DELETE', credentials: 'same-origin' },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to delete');
  return data;
}

async function _renamePath(src, dest) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/rename`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ src, dest }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to rename');
  return data;
}

function _parentPath(relPath) {
  const parts = (relPath || '').split('/').filter(Boolean);
  if (parts.length <= 1) return '.';
  return parts.slice(0, -1).join('/');
}

function _basename(relPath) {
  const parts = (relPath || '').split('/').filter(Boolean);
  return parts[parts.length - 1] || relPath || '';
}

function _joinPath(dir, name) {
  if (!dir || dir === '.') return name;
  return `${dir}/${name}`;
}

function _expandPathChain(relPath) {
  let cur = _parentPath(relPath);
  while (cur && cur !== '.') {
    _expanded.add(cur);
    cur = _parentPath(cur);
  }
  _expanded.add('.');
}

function _setSelected(path) {
  _selectedPath = path || null;
  _container?.querySelectorAll('.project-tree-row.selected').forEach((el) => {
    el.classList.remove('selected');
  });
  if (!path) return;
  const row = _container?.querySelector(`.project-tree-row[data-path="${CSS.escape(path)}"]`);
  row?.classList.add('selected');
}

async function _selectFile(path) {
  _setSelected(path);
  if (!_onFileSelect) return;
  try {
    const payload = await _readFile(path);
    _onFileSelect(payload);
  } catch (err) {
    uiModule.showToast?.(err.message || 'Could not open file', 4000);
  }
}

function _toggleExpanded(dirPath) {
  if (_expanded.has(dirPath)) _expanded.delete(dirPath);
  else _expanded.add(dirPath);
}

function _closeActionMenus() {
  document.querySelectorAll('.project-tree-action-menu, .project-tree-move-submenu').forEach((el) => {
    el.style.display = 'none';
  });
}

function _closeTreeDropdowns() {
  _closeActionMenus();
  _container?.querySelectorAll('.project-tree-dropdown.show').forEach((el) => {
    el.classList.remove('show');
    el.style.position = '';
    el.style.left = '';
    el.style.top = '';
    el.style.right = '';
  });
  _container?.querySelectorAll('.project-tree-dropdown-wrap.is-open').forEach((el) => {
    el.classList.remove('is-open');
  });
  _container?.querySelector('[data-action="new"]')?.setAttribute('aria-expanded', 'false');
}

function _removeActionMenusFromBody() {
  document.querySelectorAll('.project-tree-action-menu, .project-tree-move-submenu').forEach((el) => el.remove());
}

function _positionDropdown(dropdown, anchorEl) {
  const rect = anchorEl.getBoundingClientRect();
  dropdown.style.left = '';
  dropdown.style.right = `${Math.max(0, window.innerWidth - rect.right)}px`;
  dropdown.style.top = '-9999px';
  dropdown.style.display = 'block';
  const ddRect = dropdown.getBoundingClientRect();
  if (rect.bottom + 2 + ddRect.height > window.innerHeight) {
    dropdown.style.top = `${Math.max(2, rect.top - ddRect.height - 2)}px`;
  } else {
    dropdown.style.top = `${rect.bottom + 2}px`;
  }
}

function _positionMoveSubmenu(sub, moveItem, dropdown) {
  const rect = moveItem.getBoundingClientRect();
  const isMobile = window.innerWidth <= 768;
  sub.style.top = '-9999px';
  sub.style.display = 'block';
  const subRect = sub.getBoundingClientRect();
  if (isMobile) {
    const ddRect = dropdown.getBoundingClientRect();
    sub.style.left = `${Math.max(8, ddRect.left)}px`;
    sub.style.right = 'auto';
    sub.style.width = `${Math.min(ddRect.width, window.innerWidth - 16)}px`;
    const topBelow = ddRect.bottom + 4;
    if (topBelow + subRect.height > window.innerHeight) {
      sub.style.top = `${Math.max(8, ddRect.top - subRect.height - 4)}px`;
    } else {
      sub.style.top = `${topBelow}px`;
    }
    return;
  }
  sub.style.width = '';
  sub.style.right = 'auto';
  sub.style.left = `${rect.right + 2}px`;
  if (rect.top + subRect.height > window.innerHeight) {
    sub.style.top = `${Math.max(2, window.innerHeight - subRect.height - 4)}px`;
  } else {
    sub.style.top = `${rect.top}px`;
  }
  if (rect.right + 2 + subRect.width > window.innerWidth - 8) {
    sub.style.left = `${Math.max(8, rect.left - subRect.width - 2)}px`;
  }
}

async function _openMoveSubmenu(sub, entry, moveItem, dropdown) {
  document.querySelectorAll('.project-tree-move-submenu').forEach((el) => {
    if (el !== sub) el.style.display = 'none';
  });

  sub.replaceChildren();
  const loading = document.createElement('div');
  loading.className = 'dropdown-item-compact';
  loading.style.opacity = '0.55';
  loading.textContent = 'Loading…';
  sub.appendChild(loading);
  _positionMoveSubmenu(sub, moveItem, dropdown);

  try {
    const folders = await _listSiblingFolders(entry);
    if (sub.style.display !== 'block') return;
    _populateMoveSubmenu(sub, entry, folders, dropdown);
    _positionMoveSubmenu(sub, moveItem, dropdown);
  } catch {
    if (sub.style.display !== 'block') return;
    sub.replaceChildren();
    const errEl = document.createElement('div');
    errEl.className = 'dropdown-item-compact';
    errEl.style.opacity = '0.55';
    errEl.textContent = 'Could not list folders';
    sub.appendChild(errEl);
  }
}

async function _applyRename(entry, newName) {
  const trimmed = (newName || '').trim();
  if (!trimmed || trimmed === entry.name) return false;
  if (trimmed.includes('/') || trimmed.includes('\\')) {
    uiModule.showToast?.('Name cannot contain path separators', 3000);
    return false;
  }
  const parent = _parentPath(entry.path);
  const dest = parent === '.' ? trimmed : `${parent}/${trimmed}`;
  if (dest === entry.path) return false;
  const wasExpanded = entry.type === 'dir' && _expanded.has(entry.path);
  await _renamePath(entry.path, dest);
  if (wasExpanded) {
    _expanded.delete(entry.path);
    _expanded.add(dest);
  }
  if (_selectedPath === entry.path) {
    _selectedPath = dest;
    _onPathChange?.(entry.path, dest);
  }
  return true;
}

function _startInlineRename(entry, rowEl) {
  _closeActionMenus();
  const nameEl = rowEl.querySelector('.project-tree-name');
  if (!nameEl || rowEl.querySelector('.project-tree-rename-input')) return;
  const input = document.createElement('input');
  input.type = 'text';
  input.value = entry.name;
  input.className = 'session-rename-input project-tree-rename-input';
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  const commit = async () => {
    try {
      const ok = await _applyRename(entry, input.value);
      if (ok) uiModule.showToast?.('Renamed');
    } catch (err) {
      uiModule.showToast?.(err.message || 'Rename failed', 4000);
    }
    await refresh();
  };

  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      input.blur();
    }
    if (ev.key === 'Escape') {
      input.removeEventListener('blur', commit);
      void refresh();
    }
  });
}

async function _moveEntry(entry, destDir) {
  const base = _basename(entry.path);
  const dest = _joinPath(destDir === '.' ? '' : destDir, base);
  if (dest === entry.path) return;
  const wasExpanded = entry.type === 'dir' && _expanded.has(entry.path);
  await _renamePath(entry.path, dest);
  if (wasExpanded) {
    _expanded.delete(entry.path);
    _expanded.add(dest);
  }
  if (_selectedPath === entry.path) {
    _selectedPath = dest;
    _onPathChange?.(entry.path, dest);
  }
  uiModule.showToast?.('Moved');
}

async function _deleteEntry(entry) {
  const label = entry.type === 'dir'
    ? `Delete folder “${entry.name}” and all contents?`
    : `Delete file “${entry.name}”?`;
  if (!await uiModule.styledConfirm(label, { confirmText: 'Delete', danger: true })) return;
  await _deletePath(entry.path, entry.type === 'dir');
  _expanded.delete(entry.path);
  if (_selectedPath === entry.path) {
    _selectedPath = null;
    _onFileSelect?.(null);
  }
  uiModule.showToast?.('Deleted');
}

async function _listSiblingFolders(entry) {
  const parent = _parentPath(entry.path);
  let entries;
  try {
    entries = await _listDir(parent);
  } catch {
    return [];
  }
  return entries
    .filter((e) => e.type === 'dir' && e.path !== entry.path)
    .sort((a, b) => a.name.localeCompare(b.name));
}

function _populateMoveSubmenu(sub, entry, folders, dropdown) {
  sub.replaceChildren();
  const parent = _parentPath(entry.path);
  const head = document.createElement('div');
  head.className = 'project-tree-move-submenu-head';
  head.textContent = parent === '.' ? 'Folders in project root' : `Folders in ${parent}`;
  sub.appendChild(head);

  if (!folders.length) {
    const empty = document.createElement('div');
    empty.className = 'dropdown-item-compact';
    empty.style.opacity = '0.55';
    empty.textContent = 'No other folders here';
    sub.appendChild(empty);
    return;
  }
  for (const dir of folders) {
    const opt = document.createElement('div');
    opt.className = 'dropdown-item-compact';
    opt.textContent = dir.name;
    opt.title = dir.path;
    opt.addEventListener('click', async (e) => {
      e.stopPropagation();
      dropdown.style.display = 'none';
      sub.style.display = 'none';
      try {
        await _moveEntry(entry, dir.path);
        await refresh();
      } catch (err) {
        uiModule.showToast?.(err.message || 'Move failed', 4000);
      }
    });
    sub.appendChild(opt);
  }
}

function _buildMoveSubmenu(entry, dropdown, moveItem) {
  const sub = document.createElement('div');
  sub.className = 'dropdown session-dropdown session-dropdown-menu session-folder-submenu project-tree-move-submenu';

  const toggleSubmenu = (e) => {
    e.stopPropagation();
    if (sub.style.display === 'block') {
      sub.style.display = 'none';
      return;
    }
    void _openMoveSubmenu(sub, entry, moveItem, dropdown);
  };

  moveItem.addEventListener('click', toggleSubmenu);
  moveItem.addEventListener('mouseenter', () => {
    if (window.innerWidth <= 768) return;
    if (dropdown.style.display !== 'block') return;
    if (sub.style.display === 'block') return;
    void _openMoveSubmenu(sub, entry, moveItem, dropdown);
  });

  sub.addEventListener('click', (e) => e.stopPropagation());
  document.body.appendChild(sub);
  return sub;
}

function _buildRowActionMenu(entry, rowEl, menuBtn) {
  const dropdown = document.createElement('div');
  dropdown.className = 'dropdown session-dropdown session-dropdown-menu project-tree-action-menu';

  const renameItem = document.createElement('div');
  renameItem.className = 'dropdown-item-compact';
  renameItem.innerHTML = _icon(_renameIcon) + '<span>Rename</span>';
  renameItem.addEventListener('click', (e) => {
    e.stopPropagation();
    dropdown.style.display = 'none';
    if (entry.path !== _selectedPath) _setSelected(entry.path);
    _startInlineRename(entry, rowEl);
  });

  const moveItem = document.createElement('div');
  moveItem.className = 'dropdown-item-compact project-tree-move-item';
  moveItem.style.position = 'relative';
  moveItem.innerHTML = _icon(_moveIcon) + '<span>Move to folder</span><span class="project-tree-move-flyout">›</span>';

  const deleteItem = document.createElement('div');
  deleteItem.className = 'dropdown-item-compact dropdown-item-danger';
  deleteItem.innerHTML = _icon(_deleteIcon) + '<span>Delete</span>';
  deleteItem.addEventListener('click', async (e) => {
    e.stopPropagation();
    dropdown.style.display = 'none';
    try {
      await _deleteEntry(entry);
      await refresh();
    } catch (err) {
      uiModule.showToast?.(err.message || 'Delete failed', 4000);
    }
  });

  dropdown.appendChild(renameItem);
  dropdown.appendChild(moveItem);

  const sep = document.createElement('div');
  sep.className = 'dropdown-divider';
  dropdown.appendChild(sep);
  dropdown.appendChild(deleteItem);

  _buildMoveSubmenu(entry, dropdown, moveItem);

  menuBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('.dropdown, .project-tree-action-menu').forEach((d) => {
      if (d !== dropdown) d.style.display = 'none';
    });
    document.querySelectorAll('.project-tree-move-submenu').forEach((d) => {
      d.style.display = 'none';
    });
    _closeTreeDropdowns();
    if (dropdown.style.display === 'block') {
      dropdown.style.display = 'none';
    } else {
      _setSelected(entry.path);
      if (entry.type === 'file') void _selectFile(entry.path);
      else _onFileSelect?.(null);
      _positionDropdown(dropdown, menuBtn);
    }
  });

  dropdown.addEventListener('click', (e) => e.stopPropagation());
  document.body.appendChild(dropdown);
  rowEl._actionDropdown = dropdown;
  return dropdown;
}

function _selectedRow() {
  if (!_selectedPath) return null;
  return _container?.querySelector(`.project-tree-row[data-path="${CSS.escape(_selectedPath)}"]`);
}

function _defaultNewPathPrefix() {
  if (!_selectedPath) return '';
  const row = _selectedRow();
  if (row?.dataset.type === 'dir') {
    return _selectedPath === '.' ? '' : `${_selectedPath}/`;
  }
  const parent = _parentPath(_selectedPath);
  return parent === '.' ? '' : `${parent}/`;
}

function _prefillNewDropdownInputs() {
  const prefix = _defaultNewPathPrefix();
  const fileInput = _container?.querySelector('#project-tree-new-file-input');
  const folderInput = _container?.querySelector('#project-tree-new-folder-input');
  if (fileInput) fileInput.value = prefix || '';
  if (folderInput) folderInput.value = prefix ? prefix.replace(/\/$/, '') : '';
}

function _positionNewDropdown() {
  const wrap = _container?.querySelector('#project-tree-new-wrap');
  const menu = _container?.querySelector('#project-tree-new-dropdown');
  const btn = wrap?.querySelector('[data-action="new"]');
  if (!menu || !btn) return;
  const rect = btn.getBoundingClientRect();
  menu.style.position = 'fixed';
  menu.style.left = `${Math.max(8, rect.left)}px`;
  menu.style.top = `${rect.bottom + 6}px`;
  menu.style.right = 'auto';
  requestAnimationFrame(() => {
    const menuRect = menu.getBoundingClientRect();
    if (menuRect.right > window.innerWidth - 8) {
      menu.style.left = `${Math.max(8, window.innerWidth - menuRect.width - 8)}px`;
    }
    if (menuRect.bottom > window.innerHeight - 8) {
      menu.style.top = `${Math.max(8, rect.top - menuRect.height - 6)}px`;
    }
  });
}

function _toggleNewDropdown() {
  const wrap = _container?.querySelector('#project-tree-new-wrap');
  const menu = _container?.querySelector('#project-tree-new-dropdown');
  const btn = _container?.querySelector('[data-action="new"]');
  if (!wrap || !menu) return;
  const willOpen = !menu.classList.contains('show');
  _closeTreeDropdowns();
  if (willOpen) {
    menu.classList.add('show');
    wrap.classList.add('is-open');
    btn?.setAttribute('aria-expanded', 'true');
    _prefillNewDropdownInputs();
    _positionNewDropdown();
    requestAnimationFrame(() => _container?.querySelector('#project-tree-new-file-input')?.focus());
  } else {
    btn?.setAttribute('aria-expanded', 'false');
  }
}

async function _submitNewFile(rawPath) {
  const path = (rawPath || '').trim().replace(/\\/g, '/').replace(/\/+$/, '');
  if (!path) {
    uiModule.showToast?.('Enter a file path', 3000);
    return;
  }
  try {
    await _writeFile(path, '');
    _expanded.add(_parentPath(path));
    _closeTreeDropdowns();
    await refresh();
    void _selectFile(path);
    uiModule.showToast?.('File created');
  } catch (err) {
    uiModule.showToast?.(err.message || 'Create failed', 4000);
  }
}

async function _submitNewFolder(rawPath) {
  const path = (rawPath || '').trim().replace(/\\/g, '/').replace(/\/+$/, '');
  if (!path) {
    uiModule.showToast?.('Enter a folder path', 3000);
    return;
  }
  try {
    await _mkdir(path);
    _expanded.add(path);
    _expanded.add(_parentPath(path));
    _closeTreeDropdowns();
    await refresh();
    uiModule.showToast?.('Folder created');
  } catch (err) {
    uiModule.showToast?.(err.message || 'Create failed', 4000);
  }
}

async function _renderTreeBody() {
  const body = _container?.querySelector('#project-file-tree-body');
  if (!body) return;
  body.innerHTML = '<div class="project-tree-empty">Loading…</div>';
  _removeActionMenusFromBody();

  const rows = [];

  async function walk(dirPath, depth) {
    let entries;
    try {
      entries = await _listDir(dirPath);
    } catch (err) {
      rows.push({ kind: 'error', depth, message: err.message || 'List failed' });
      return;
    }
    for (const entry of entries) {
      rows.push({ kind: 'entry', depth, entry });
      if (entry.type === 'dir' && _expanded.has(entry.path)) await walk(entry.path, depth + 1);
    }
  }

  await walk('.', 0);

  if (!rows.length) {
    body.innerHTML = '<div class="project-tree-empty">Empty folder — use New to create a file or folder</div>';
    return;
  }

  body.replaceChildren();
  for (const row of rows) {
    if (row.kind === 'error') {
      const el = document.createElement('div');
      el.className = 'project-tree-empty';
      el.style.paddingLeft = `${8 + row.depth * 14}px`;
      el.textContent = row.message;
      body.appendChild(el);
      continue;
    }

    const { entry, depth } = row;
    const rowEl = document.createElement('div');
    rowEl.className = 'project-tree-row';
    rowEl.dataset.path = entry.path;
    rowEl.dataset.type = entry.type;
    if (entry.path === _selectedPath) rowEl.classList.add('selected');

    const mainBtn = document.createElement('button');
    mainBtn.type = 'button';
    mainBtn.className = 'project-tree-main';
    mainBtn.style.paddingLeft = `${8 + depth * 14}px`;

    const expandChevron = entry.type === 'dir'
      ? (_expanded.has(entry.path) ? '▾' : '▸')
      : ' ';
    const icon = entry.type === 'dir'
      ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg>'
      : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';

    mainBtn.innerHTML =
      `<span class="project-tree-chevron">${expandChevron}</span>` +
      `<span class="project-tree-icon">${icon}</span>` +
      `<span class="project-tree-name grow">${esc(entry.name)}</span>`;

    mainBtn.addEventListener('click', () => {
      if (entry.type === 'dir') {
        _setSelected(entry.path);
        _onFileSelect?.(null);
        _toggleExpanded(entry.path);
        void _renderTreeBody();
        return;
      }
      void _selectFile(entry.path);
    });

    mainBtn.addEventListener('dblclick', (ev) => {
      if (entry.path !== _selectedPath) return;
      ev.preventDefault();
      if (entry.type === 'dir') {
        _toggleExpanded(entry.path);
        void _renderTreeBody();
      } else {
        _startInlineRename(entry, rowEl);
      }
    });

    const menuBtn = document.createElement('button');
    menuBtn.type = 'button';
    menuBtn.className = 'hamburger session-menu-btn project-tree-menu-btn';
    menuBtn.title = 'File actions';
    menuBtn.innerHTML = _menuChevron;

    rowEl.appendChild(mainBtn);
    rowEl.appendChild(menuBtn);
    _buildRowActionMenu(entry, rowEl, menuBtn);
    body.appendChild(rowEl);
  }
}

function _renderChrome() {
  if (!_container) return;
  _container.innerHTML =
    '<div class="project-file-tree-toolbar">' +
      '<button type="button" class="admin-btn-sm project-tree-tool" data-action="refresh" title="Refresh tree">' +
        '<span class="project-tree-tool-icon" aria-hidden="true">↻</span>' +
      '</button>' +
      '<div id="project-tree-new-wrap" class="project-tree-dropdown-wrap">' +
        '<button type="button" class="admin-btn-sm project-tree-tool project-tree-new-btn" data-action="new" aria-expanded="false" aria-haspopup="true">' +
          'New' +
          '<svg class="project-tree-caret" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>' +
        '</button>' +
        '<div id="project-tree-new-dropdown" class="project-tree-dropdown" role="dialog" aria-label="Create file or folder">' +
          '<div class="project-tree-dropdown-section">' +
            '<div class="project-tree-dropdown-label">New file</div>' +
            '<p class="admin-toggle-sub project-tree-dropdown-hint">Path relative to project folder</p>' +
            '<input type="text" id="project-tree-new-file-input" class="styled-prompt-input project-tree-path-input" placeholder="src/analysis.py" spellcheck="false" autocomplete="off" maxlength="4096" />' +
            '<button type="button" class="confirm-btn confirm-btn-primary project-tree-dropdown-submit" data-create="file">Create file</button>' +
          '</div>' +
          '<div class="project-tree-dropdown-divider"></div>' +
          '<div class="project-tree-dropdown-section">' +
            '<div class="project-tree-dropdown-label">New folder</div>' +
            '<p class="admin-toggle-sub project-tree-dropdown-hint">Path relative to project folder</p>' +
            '<input type="text" id="project-tree-new-folder-input" class="styled-prompt-input project-tree-path-input" placeholder="src" spellcheck="false" autocomplete="off" maxlength="4096" />' +
            '<button type="button" class="confirm-btn confirm-btn-primary project-tree-dropdown-submit" data-create="folder">Create folder</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div id="project-file-tree-body" class="project-file-tree-body" role="tree"></div>';

  _container.querySelector('[data-action="refresh"]')?.addEventListener('click', () => void refresh());
  _container.querySelector('[data-action="new"]')?.addEventListener('click', (e) => {
    e.stopPropagation();
    _toggleNewDropdown();
  });

  _container.querySelector('[data-create="file"]')?.addEventListener('click', () => {
    void _submitNewFile(_container.querySelector('#project-tree-new-file-input')?.value || '');
  });
  _container.querySelector('[data-create="folder"]')?.addEventListener('click', () => {
    void _submitNewFolder(_container.querySelector('#project-tree-new-folder-input')?.value || '');
  });

  _container.querySelector('#project-tree-new-file-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      void _submitNewFile(e.target.value || '');
    } else if (e.key === 'Escape') {
      e.preventDefault();
      _closeTreeDropdowns();
    }
  });
  _container.querySelector('#project-tree-new-folder-input')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      void _submitNewFolder(e.target.value || '');
    } else if (e.key === 'Escape') {
      e.preventDefault();
      _closeTreeDropdowns();
    }
  });

  if (!_container.dataset.dropdownBound) {
    _container.dataset.dropdownBound = '1';
    document.addEventListener('click', (e) => {
      if (e.target.closest('#project-tree-new-wrap')) return;
      if (e.target.closest('.project-tree-action-menu')) return;
      if (e.target.closest('.project-tree-move-submenu')) return;
      if (e.target.closest('.project-tree-menu-btn')) return;
      _closeTreeDropdowns();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') _closeTreeDropdowns();
    });
  }
}

export async function refresh() {
  if (!_container || !_projectId || _loading) return;
  _loading = true;
  try {
    await _renderTreeBody();
    if (_onAfterRefresh) await _onAfterRefresh(_selectedPath);
  } finally {
    _loading = false;
  }
}

export function unmount() {
  _closeTreeDropdowns();
  _removeActionMenusFromBody();
  _projectId = null;
  _container = null;
  _onFileSelect = null;
  _onPathChange = null;
  _onAfterRefresh = null;
  _expanded = new Set(['.']);
  _selectedPath = null;
}

export function mount(container, projectId, { onFileSelect, onPathChange, onAfterRefresh, workingDirStatus } = {}) {
  unmount();
  _container = container;
  _projectId = projectId;
  _onFileSelect = onFileSelect || null;
  _onPathChange = onPathChange || null;
  _onAfterRefresh = onAfterRefresh || null;

  if (workingDirStatus && workingDirStatus !== 'ok') {
    container.innerHTML =
      `<div class="project-tree-empty">Working directory ${esc(workingDirStatus)} — fix the folder path before browsing files.</div>`;
    return;
  }

  _renderChrome();
  void refresh();
}

export function getSelectedPath() {
  return _selectedPath;
}

/** Restore a previously open file — expands parent folders then selects. */
export async function openPath(path) {
  if (!path || !_projectId || !_onFileSelect) return false;
  _expandPathChain(path);
  await refresh();
  try {
    await _selectFile(path);
    return true;
  } catch {
    return false;
  }
}

export default {
  mount,
  unmount,
  refresh,
  getSelectedPath,
  openPath,
};
