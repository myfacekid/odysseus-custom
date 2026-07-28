/**
 * Active project chip — L1 harness chrome for Projects-as-context-layer.
 * Switch / create / clear without opening the IDE workspace shell.
 */
import uiModule from '../ui.js';
import { isProjectsContextLayerEnabled } from './featureFlag.js';
import {
  ACTIVE_PROJECT_EVENT,
  getActiveProjectId,
  setActiveProjectId,
  clearActiveProjectId,
  migrateLastOpenToActive,
} from './activeState.js';

const API_BASE = window.API_BASE || window.location.origin;
const SLATE_MS = 260;

let _projects = [];
let _activeMeta = null;
let _menuOpen = false;
let _closeTimer = null;
let _menuHome = null;

const FOLDER_ICON = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg>`;

function _esc(s) {
  return uiModule.esc ? uiModule.esc(s) : String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _prefersReducedMotion() {
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  } catch {
    return false;
  }
}

async function _fetchProjects() {
  const res = await fetch(`${API_BASE}/api/projects`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error('Could not load projects');
  const data = await res.json();
  _projects = (data.projects || []).filter((p) => !p.archived);
  return _projects;
}

function _find(id) {
  return _projects.find((p) => p.id === id) || null;
}

function _root() {
  return document.getElementById('project-active-chip');
}

function _btn() {
  return document.getElementById('project-active-chip-btn');
}

function _menu() {
  return document.getElementById('project-active-chip-menu');
}

/** Position the slate at the sidebar header edge so it can slide into chat. */
function _positionSlate(menu) {
  const sidebar = document.getElementById('sidebar');
  const header = sidebar?.querySelector('.sidebar-header');
  if (!sidebar || !header || !menu) return;

  const sideRect = sidebar.getBoundingClientRect();
  const headRect = header.getBoundingClientRect();
  const isRight = sidebar.classList.contains('right-side');
  const width = Math.min(320, Math.max(260, Math.min(window.innerWidth * 0.92, 360)));
  // Align with the toolbar band so the sidebar/header covers the tuck;
  // the panel emerges from under that row into the chat.
  const top = Math.round(headRect.top);
  const maxH = Math.max(160, Math.min(420, window.innerHeight - top - 12));

  menu.classList.add('is-slate');
  menu.classList.toggle('slate-from-left', !isRight);
  menu.classList.toggle('slate-from-right', isRight);
  menu.classList.toggle('is-active-surface', !!_root()?.classList.contains('is-active'));
  menu.style.top = `${top}px`;
  menu.style.width = `${width}px`;
  menu.style.maxHeight = `${maxH}px`;

  if (!isRight) {
    // Anchor at the sidebar’s chat edge; translateX(-100%) tucks fully under it.
    menu.style.left = `${Math.round(sideRect.right)}px`;
    menu.style.right = 'auto';
  } else {
    menu.style.left = 'auto';
    menu.style.right = `${Math.round(window.innerWidth - sideRect.left)}px`;
  }
}

function _clearSlateInline(menu) {
  if (!menu) return;
  menu.classList.remove('is-slate', 'slate-from-left', 'slate-from-right', 'open', 'closing', 'is-active-surface');
  menu.style.top = '';
  menu.style.left = '';
  menu.style.right = '';
  menu.style.width = '';
  menu.style.maxHeight = '';
}

function _restoreMenuHome(menu) {
  if (!menu) return;
  const home = _menuHome || _root();
  if (home && menu.parentElement !== home) {
    home.appendChild(menu);
  }
}

function _closeMenu() {
  const menu = _menu();
  const btn = _btn();
  if (!menu) return;

  btn?.setAttribute('aria-expanded', 'false');
  _menuOpen = false;
  window.removeEventListener('resize', _onViewportChange);
  window.removeEventListener('scroll', _onViewportChange, true);

  if (!menu.classList.contains('is-slate') && !menu.classList.contains('open')) {
    menu.setAttribute('aria-hidden', 'true');
    return;
  }

  const finish = () => {
    _clearSlateInline(menu);
    menu.setAttribute('aria-hidden', 'true');
    _restoreMenuHome(menu);
  };

  if (_prefersReducedMotion()) {
    clearTimeout(_closeTimer);
    finish();
    return;
  }

  menu.classList.remove('open');
  menu.classList.add('closing');
  clearTimeout(_closeTimer);
  _closeTimer = setTimeout(finish, SLATE_MS);
}

function _openMenu() {
  const menu = _menu();
  const btn = _btn();
  const root = _root();
  if (!menu || !btn) return;

  clearTimeout(_closeTimer);
  menu.classList.remove('closing');
  if (!_menuHome && root) _menuHome = root;

  // Port to body so overflow/transform on the sidebar cannot clip the slate.
  if (menu.parentElement !== document.body) {
    document.body.appendChild(menu);
  }

  _positionSlate(menu);
  menu.setAttribute('aria-hidden', 'false');
  btn.setAttribute('aria-expanded', 'true');
  _menuOpen = true;

  // Double rAF so the tucked transform paints before sliding open.
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (!_menuOpen) return;
      menu.classList.add('open');
    });
  });

  window.addEventListener('resize', _onViewportChange);
  window.addEventListener('scroll', _onViewportChange, true);
  void _renderMenu();
}

function _onViewportChange() {
  if (!_menuOpen) return;
  const menu = _menu();
  if (menu) _positionSlate(menu);
}

function _paintChip() {
  const root = _root();
  const btn = _btn();
  const label = document.getElementById('project-active-chip-label');
  if (!root || !btn || !label) return;

  const id = getActiveProjectId();
  _activeMeta = id ? (_find(id) || _activeMeta) : null;
  const active = !!(id && _activeMeta);

  root.classList.toggle('is-active', active);
  root.classList.toggle('is-empty', !active);
  document.body.classList.toggle('project-context-active', active);
  document.getElementById('chat-container')?.classList.toggle('project-context-active', active);

  if (active) {
    label.textContent = _activeMeta.title || 'Project';
    btn.title = `Project: ${_activeMeta.title || id} — tools use this folder`;
    btn.setAttribute('aria-label', `Active project ${_activeMeta.title || id}`);
  } else {
    label.textContent = 'No project';
    btn.title = 'No project — chats and tools are unscoped';
    btn.setAttribute('aria-label', 'Set active project');
  }

  // Activity strip optional badge via custom event consumers
  try {
    window.dispatchEvent(new CustomEvent('odysseus-project-chip-painted', {
      detail: { projectId: id, title: _activeMeta?.title || null },
    }));
  } catch { /* ignore */ }
}

/** Toast when the user scopes to a project (not on cold restore). */
function _toastProjectScoped(title) {
  const name = title || 'this project';
  uiModule.showToast?.(
    `Tools run in “${name}”’s folder. Switch projects anytime next to Nobody.`,
    { duration: 4500, leadingIcon: 'check' },
  );
}

async function _renderMenu() {
  const menu = _menu();
  if (!menu) return;
  try {
    await _fetchProjects();
  } catch (e) {
    menu.innerHTML = `<div class="project-chip-menu-empty">${_esc(e.message || 'Failed to load')}</div>`;
    return;
  }

  const activeId = getActiveProjectId();
  const rows = [];
  rows.push(`<div class="project-chip-menu-section">Active project</div>`);

  if (!_projects.length) {
    rows.push(`<div class="project-chip-menu-empty">No projects yet — create one to scope chats and cwd tools.</div>`);
  } else {
    for (const p of _projects) {
      const isOn = p.id === activeId;
      const dir = p.working_dir || '';
      rows.push(`
        <button type="button" class="project-chip-menu-item${isOn ? ' is-selected' : ''}" data-action="select" data-id="${_esc(p.id)}">
          <span class="project-chip-menu-icon">${FOLDER_ICON}</span>
          <span class="project-chip-menu-text">
            <span class="project-chip-menu-title" title="${_esc(p.title || 'Untitled')}">${_esc(p.title || 'Untitled')}</span>
            <span class="project-chip-menu-meta" title="${_esc(dir)}">${_esc(dir)}</span>
          </span>
          ${isOn ? '<span class="project-chip-menu-check" aria-hidden="true">✓</span>' : ''}
        </button>`);
    }
  }

  rows.push(`<div class="project-chip-menu-sep" role="separator"></div>`);
  rows.push(`
    <button type="button" class="project-chip-menu-item" data-action="create">
      <span class="project-chip-menu-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg></span>
      <span class="project-chip-menu-text"><span class="project-chip-menu-title">New project…</span></span>
    </button>`);
  if (activeId) {
    rows.push(`
      <button type="button" class="project-chip-menu-item project-chip-menu-danger" data-action="clear">
        <span class="project-chip-menu-icon"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg></span>
        <span class="project-chip-menu-text"><span class="project-chip-menu-title">Clear project</span></span>
      </button>`);
  }

  menu.innerHTML = rows.join('');
}

async function _createProject() {
  const mod = await import('./index.js');
  const create = mod.createProjectDialog || mod.default?.createProjectDialog;
  if (!create) {
    uiModule.showToast?.('Create project unavailable', 3000);
    return;
  }
  const project = await create({ openWorkspace: false, setActive: true });
  if (project?.id) {
    _activeMeta = project;
    _projects = [project, ..._projects.filter((p) => p.id !== project.id)];
    setActiveProjectId(project.id);
    _paintChip();
    _toastProjectScoped(project.title);
  }
}

async function _onMenuClick(e) {
  const item = e.target.closest('[data-action]');
  if (!item || item.disabled) return;
  const action = item.dataset.action;
  _closeMenu();

  if (action === 'create') {
    await _createProject();
    return;
  }
  if (action === 'clear') {
    const ok = await uiModule.styledConfirm?.(
      'Clear the active project? New chats will be unscoped again.',
      { title: 'Clear project', confirmText: 'Clear', danger: true },
    );
    if (!ok) return;
    clearActiveProjectId();
    _activeMeta = null;
    _paintChip();
    uiModule.showToast?.('Project cleared — chats and tools unscoped', 2800);
    return;
  }
  if (action === 'select') {
    const id = item.dataset.id;
    const project = _find(id);
    if (!project) return;
    setActiveProjectId(id);
    _activeMeta = project;
    _paintChip();
    _toastProjectScoped(project.title);
  }
}

function _onDocClick(e) {
  if (!_menuOpen) return;
  const root = _root();
  const menu = _menu();
  const btn = _btn();
  if (menu?.contains(e.target) || btn?.contains(e.target) || root?.contains(e.target)) return;
  _closeMenu();
}

function _onKey(e) {
  if (e.key === 'Escape' && _menuOpen) {
    e.preventDefault();
    _closeMenu();
  }
}

export async function refreshActiveProjectChip() {
  if (!isProjectsContextLayerEnabled()) return;
  try {
    await _fetchProjects();
  } catch { /* keep prior meta */ }
  const id = getActiveProjectId();
  if (id && !_find(id)) {
    // Archived / deleted — clear quietly
    clearActiveProjectId();
    _activeMeta = null;
  } else if (id) {
    _activeMeta = _find(id);
  }
  _paintChip();
}

export function initActiveProjectChip() {
  if (!isProjectsContextLayerEnabled()) {
    const root = _root();
    if (root) {
      root.hidden = true;
      root.setAttribute('aria-hidden', 'true');
    }
    return;
  }

  migrateLastOpenToActive();

  const root = _root();
  const btn = _btn();
  const menu = _menu();
  if (!root || !btn || !menu) return;

  _menuHome = root;
  root.hidden = false;
  root.removeAttribute('aria-hidden');

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (_menuOpen) _closeMenu();
    else _openMenu();
  });
  menu.addEventListener('click', (e) => { void _onMenuClick(e); });
  document.addEventListener('click', _onDocClick);
  document.addEventListener('keydown', _onKey);
  window.addEventListener(ACTIVE_PROJECT_EVENT, () => { void refreshActiveProjectChip(); });

  void refreshActiveProjectChip();
}

/** External callers — set active from Knowledge graph etc. */
export async function setActiveProjectFromId(projectId, { toast = true } = {}) {
  if (!projectId) return null;
  try {
    await _fetchProjects();
  } catch { /* ignore */ }
  const project = _find(projectId);
  if (!project) {
    uiModule.showToast?.('Project not found', 3000);
    return null;
  }
  setActiveProjectId(projectId);
  _activeMeta = project;
  _paintChip();
  if (toast) _toastProjectScoped(project.title);
  return project;
}

export function getCachedActiveProject() {
  const id = getActiveProjectId();
  return id ? (_find(id) || _activeMeta) : null;
}

export default {
  initActiveProjectChip,
  refreshActiveProjectChip,
  setActiveProjectFromId,
  getCachedActiveProject,
};
