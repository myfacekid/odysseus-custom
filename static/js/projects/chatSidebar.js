/**
 * Project workspace chat sidebar (Phase D2).
 * Lists / creates / renames project-scoped sessions; docks main chat UI in-region.
 * Rename UX mirrors main Chats + file tree: chevron menu, inline input, no modals.
 */
import uiModule from '../ui.js';
import workspaceState from './workspaceState.js';

const API_BASE = window.API_BASE || window.location.origin;

const _renameIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.83 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>';
const _menuChevron = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';

let _container = null;
let _projectId = null;
let _sessions = [];
let _activeSessionId = null;
let _mounted = false;
let _chatDock = null;

function _icon(svg) {
  return `<span class="dropdown-icon">${svg}</span>`;
}

function _saveActiveSession(id) {
  if (!_projectId) return;
  workspaceState.saveActiveChat(_projectId, id);
}

function _loadSavedSessionId() {
  if (!_projectId) return null;
  return workspaceState.getActiveChat(_projectId);
}

function _els() {
  return {
    list: _container?.querySelector('#project-chat-list'),
    empty: _container?.querySelector('#project-chat-empty'),
    main: _container?.querySelector('#project-chat-main'),
  };
}

function _closeActionMenus() {
  document.querySelectorAll('.project-chat-action-menu').forEach((el) => {
    el.style.display = 'none';
  });
}

function _removeActionMenusFromBody() {
  document.querySelectorAll('.project-chat-action-menu').forEach((el) => el.remove());
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

function _dockChatUi() {
  const { main } = _els();
  const history = document.getElementById('chat-history');
  const container = document.getElementById('chat-container');
  if (!main || !history) return;

  if (history.parentElement === main) {
    if (!_chatDock) {
      _chatDock = {
        history,
        parent: container,
        anchor: document.getElementById('project-workspace-panel'),
      };
    }
    container?.classList.add('project-chat-docked');
    _ensureChatVisible();
    return;
  }

  if (_chatDock) return;

  _chatDock = {
    history,
    parent: history.parentElement,
    anchor: history.nextElementSibling,
  };
  main.appendChild(history);
  container?.classList.add('project-chat-docked');
  _ensureChatVisible();
}

function _undockChatUi() {
  if (!_chatDock) return;
  const { history, parent, anchor } = _chatDock;
  const container = document.getElementById('chat-container');
  container?.classList.remove('project-chat-docked');

  if (parent && history) {
    if (anchor && anchor.parentElement === parent) {
      parent.insertBefore(history, anchor);
    } else {
      const panel = document.getElementById('project-workspace-panel');
      if (panel && panel.parentElement === parent) {
        parent.insertBefore(history, panel);
      } else {
        parent.appendChild(history);
      }
    }
  }
  _chatDock = null;
}

function _ensureChatVisible() {
  const history = document.getElementById('chat-history');
  if (history) {
    history.style.opacity = '1';
    history.style.transition = '';
  }
  document.getElementById('welcome-screen')?.classList.add('hidden');
  window.chatModule?.hideWelcomeScreen?.();
}

function _startInlineRename(session, rowEl) {
  _closeActionMenus();
  const nameEl = rowEl.querySelector('.project-chat-item-name');
  if (!nameEl || rowEl.querySelector('.session-rename-input')) return;

  const input = document.createElement('input');
  input.type = 'text';
  input.value = session.name || '';
  input.className = 'session-rename-input project-chat-rename-input';
  nameEl.replaceWith(input);
  input.focus();
  input.select();

  const commit = async () => {
    const newName = input.value.trim();
    if (newName && newName !== session.name) {
      const fd = new FormData();
      fd.append('name', newName);
      const res = await fetch(`${API_BASE}/api/session/${encodeURIComponent(session.id)}`, {
        method: 'PATCH',
        credentials: 'same-origin',
        body: fd,
      });
      if (!res.ok) {
        uiModule.showToast?.('Rename failed', 3000);
        _renderList();
        return;
      }
      session.name = newName;
      if (_activeSessionId === session.id) {
        const metaEl = uiModule.el('current-meta');
        if (metaEl) metaEl.textContent = newName;
      }
      uiModule.showToast?.('Renamed');
    }
    _renderList();
  };

  input.addEventListener('blur', commit);
  input.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter') {
      ev.preventDefault();
      input.blur();
    }
    if (ev.key === 'Escape') {
      input.removeEventListener('blur', commit);
      _renderList();
    }
  });
}

function _buildRowActionMenu(session, rowEl, menuBtn) {
  const dropdown = document.createElement('div');
  dropdown.className = 'dropdown session-dropdown session-dropdown-menu project-chat-action-menu';

  const renameItem = document.createElement('div');
  renameItem.className = 'dropdown-item-compact';
  renameItem.innerHTML = _icon(_renameIcon) + '<span>Rename</span>';
  renameItem.addEventListener('click', (e) => {
    e.stopPropagation();
    dropdown.style.display = 'none';
    if (_activeSessionId !== session.id) {
      void _selectSession(session.id).then(() => {
        const activeRow = _container?.querySelector(`.project-chat-row[data-session-id="${CSS.escape(session.id)}"]`);
        if (activeRow) _startInlineRename(session, activeRow);
      });
      return;
    }
    _startInlineRename(session, rowEl);
  });

  dropdown.appendChild(renameItem);

  menuBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    document.querySelectorAll('.project-chat-action-menu').forEach((d) => {
      if (d !== dropdown) d.style.display = 'none';
    });
    if (dropdown.style.display === 'block') {
      dropdown.style.display = 'none';
    } else {
      if (_activeSessionId !== session.id) void _selectSession(session.id);
      _positionDropdown(dropdown, menuBtn);
    }
  });

  document.body.appendChild(dropdown);
}

function _renderList() {
  const { list, empty } = _els();
  if (!list) return;

  _closeActionMenus();
  _removeActionMenusFromBody();

  if (!_sessions.length) {
    list.replaceChildren();
    empty?.classList.remove('hidden');
    return;
  }
  empty?.classList.add('hidden');

  const frag = document.createDocumentFragment();
  for (const s of _sessions) {
    const rowEl = document.createElement('div');
    rowEl.className = 'project-chat-row';
    if (s.id === _activeSessionId) rowEl.classList.add('active');
    rowEl.dataset.sessionId = s.id;

    const mainBtn = document.createElement('button');
    mainBtn.type = 'button';
    mainBtn.className = 'project-chat-row-main';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'project-chat-item-name grow text-ellipsis';
    nameSpan.textContent = s.name || 'Untitled';
    nameSpan.title = s.name || s.id;
    mainBtn.appendChild(nameSpan);

    if (s.message_count) {
      const meta = document.createElement('span');
      meta.className = 'project-chat-item-meta';
      meta.textContent = String(s.message_count);
      mainBtn.appendChild(meta);
    }

    mainBtn.addEventListener('click', () => {
      void _selectSession(s.id);
    });

    nameSpan.addEventListener('dblclick', (e) => {
      if (_activeSessionId !== s.id) return;
      e.stopPropagation();
      _startInlineRename(s, rowEl);
    });

    const menuBtn = document.createElement('button');
    menuBtn.type = 'button';
    menuBtn.className = 'hamburger session-menu-btn project-chat-menu-btn';
    menuBtn.title = 'Chat actions';
    menuBtn.innerHTML = _menuChevron;

    rowEl.appendChild(mainBtn);
    rowEl.appendChild(menuBtn);
    _buildRowActionMenu(s, rowEl, menuBtn);
    frag.appendChild(rowEl);
  }
  list.replaceChildren(frag);
}

async function _fetchSessions() {
  const res = await fetch(
    `${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/sessions`,
    { credentials: 'same-origin' },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to load project chats');
  _sessions = data.sessions || [];
  _renderList();
  return _sessions;
}

function _sessionMeta(id) {
  return _sessions.find((s) => s.id === id) || null;
}

async function _selectSession(id, { force = false } = {}) {
  if (!id) return;
  if (!force && id === _activeSessionId) {
    _dockChatUi();
    _ensureChatVisible();
    return;
  }
  _activeSessionId = id;
  _saveActiveSession(id);
  _renderList();
  _dockChatUi();

  const selectFn = window.sessionModule?.selectSession;
  if (!selectFn) {
    uiModule.showToast?.('Session module unavailable', 3000);
    return;
  }
  try {
    await selectFn(id, {
      keepSidebar: true,
      inProjectWorkspace: true,
      sessionMeta: _sessionMeta(id),
    });
  } finally {
    _ensureChatVisible();
  }
}

async function _createSession(name) {
  const model = window.sessionModule?.getCurrentModel?.() || '';
  const endpoint = window.sessionModule?.getCurrentEndpointUrl?.() || '';
  const res = await fetch(
    `${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/sessions`,
    {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: (name || '').trim() || `Chat ${_sessions.length + 1}`,
        model,
        endpoint_url: endpoint,
      }),
    },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Could not create chat');
  await _fetchSessions();
  if (data.session?.id) await _selectSession(data.session.id);
  return data.session;
}

function _bindEvents() {
  _container?.querySelector('#project-chat-new-btn')?.addEventListener('click', () => {
    void _createSession().catch((e) => uiModule.showToast?.(e.message || 'Create failed', 4000));
  });

  document.addEventListener('click', _onDocumentClick);
}

function _onDocumentClick(e) {
  if (!_mounted) return;
  if (e.target.closest('.project-chat-menu-btn, .project-chat-action-menu')) return;
  _closeActionMenus();
}

function _renderChrome() {
  if (!_container) return;
  _container.innerHTML =
    '<div class="project-chat-sidebar">' +
      '<div class="project-chat-sidebar-head">' +
        '<span class="project-chat-sidebar-title">Chats</span>' +
        '<button type="button" id="project-chat-new-btn" class="admin-btn-sm" title="New project chat">+ New</button>' +
      '</div>' +
      '<div id="project-chat-empty" class="project-chat-empty">' +
        'No chats yet — start one to use cwd + graph tools here.' +
      '</div>' +
      '<div id="project-chat-list" class="project-chat-list"></div>' +
    '</div>' +
    '<div id="project-chat-main" class="project-chat-main">' +
      '<div class="project-chat-main-placeholder">Select or create a chat</div>' +
    '</div>';
  _bindEvents();
}

async function _restoreSelection() {
  await _fetchSessions();
  const saved = _loadSavedSessionId();
  const pick = (saved && _sessions.some((s) => s.id === saved))
    ? saved
    : (_sessions[0]?.id || null);
  if (pick) {
    await _selectSession(pick);
    return;
  }
  _activeSessionId = null;
  _renderList();
}

function _renderChromeAndRestore() {
  _renderChrome();
  void _restoreSelection().catch((e) => {
    uiModule.showToast?.(e.message || 'Project chats failed to load', 4000);
  });
}

export function mount(container, projectId) {
  if (!container || !projectId) return;
  _container = container;
  _projectId = projectId;
  _mounted = true;
  _activeSessionId = null;
  _sessions = [];
  _renderChromeAndRestore();
}

export function unmount() {
  document.removeEventListener('click', _onDocumentClick);
  _closeActionMenus();
  _removeActionMenusFromBody();
  _undockChatUi();
  _activeSessionId = null;
  _sessions = [];
  _projectId = null;
  if (_container) _container.innerHTML = '';
  _container = null;
  _mounted = false;
}

export async function refresh() {
  if (!_mounted || !_projectId) return;
  await _fetchSessions();
  _renderList();
}

export function getActiveSessionId() {
  return _activeSessionId;
}

export default {
  mount,
  unmount,
  refresh,
  getActiveSessionId,
};
