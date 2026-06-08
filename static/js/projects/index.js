/**
 * Projects section — list, create, and workspace shell (Phase A).
 *
 * Mission: two boundaries, one experience.
 * - Depth: user-chosen working directory (code + outputs) — Phase B+.
 * - Breadth: explicit graph links to papers, research, documents — active now.
 */
import uiModule, { styledPrompt } from '../ui.js';
import knowledgeModule from '../knowledge.js';
import fileTreeModule from './fileTree.js';
import editorModule from './editor.js';
import runPanelModule from './runPanel.js';
import chatSidebarModule from './chatSidebar.js';
import workspaceState from './workspaceState.js';

const API_BASE = window.API_BASE || window.location.origin;
const esc = uiModule.esc;

let _projects = [];
let _openProjectId = null;
let _openProjectFile = null;

function _projectNodeId(projectId) {
  return `project:${projectId}`;
}

function _workspaceRoot() {
  return document.getElementById('project-workspace-panel');
}

function _onProjectFileSelect(payload) {
  if (payload?.path) {
    void editorModule.openFile(payload);
    _openProjectFile = payload.path;
    if (_openProjectId) workspaceState.saveOpenFile(_openProjectId, payload.path);
  } else {
    editorModule.closeFile();
    _openProjectFile = null;
    if (_openProjectId) workspaceState.saveOpenFile(_openProjectId, null);
  }
  runPanelModule.syncPath(payload?.path || null);
}

function _mountEditor(project) {
  const pane = document.getElementById('project-editor-pane');
  if (!pane || !project?.id) return;
  editorModule.mount(pane, project.id, {
    onRun: () => runPanelModule.runCurrent(),
  });
}

function _mountChatSidebar(project) {
  const pane = document.getElementById('project-chat-pane');
  if (!pane || !project?.id) return;
  chatSidebarModule.mount(pane, project.id);
}

function _mountRunPanel(project) {
  const pane = document.getElementById('project-run-pane');
  if (!pane || !project?.id) return;
  runPanelModule.mount(pane, project.id, {
    getOpenPath: () => editorModule.getOpenPath(),
    isDirty: () => editorModule.isDirty(),
    save: (opts) => editorModule.save(opts),
    onRunComplete: () => void fileTreeModule.refresh(),
  });
}

function _mountFileTree(project) {
  const container = document.getElementById('project-file-tree');
  if (!container || !project?.id) return;
  fileTreeModule.mount(container, project.id, {
    workingDirStatus: project.working_dir_status,
    onFileSelect: _onProjectFileSelect,
    onPathChange: (from, to) => {
      editorModule.handlePathChange(from, to);
      if (_openProjectId) {
        const saved = workspaceState.getOpenFile(_openProjectId);
        if (saved === from && to) workspaceState.saveOpenFile(_openProjectId, to);
        else if (saved === from && !to) workspaceState.saveOpenFile(_openProjectId, null);
        if (_openProjectFile === from) _openProjectFile = to || null;
      }
    },
    onAfterRefresh: () => {
      const openPath = editorModule.getOpenPath();
      if (openPath) return editorModule.reconcileWithDisk({ quiet: true });
      return undefined;
    },
  });
}

function _statusBadge(project) {
  const status = project?.working_dir_status || '';
  if (status === 'ok') return '';
  return `<span class="project-status project-status-${esc(status)}">${esc(status)}</span>`;
}

async function _fetchProject(projectId) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectId)}`, {
    credentials: 'same-origin',
  });
  if (!res.ok) throw new Error('Project not found');
  const data = await res.json();
  return data.project;
}

async function _fetchProjects() {
  const res = await fetch(`${API_BASE}/api/projects`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error('Failed to load projects');
  const data = await res.json();
  _projects = data.projects || [];
  return _projects;
}

function _upsertProjectCache(project) {
  if (!project?.id) return;
  const idx = _projects.findIndex((p) => p.id === project.id);
  if (idx >= 0) _projects[idx] = project;
  else _projects.unshift(project);
}

function _renderProjectList() {
  const list = document.getElementById('project-list');
  if (!list) return;
  if (!_projects.length) {
    list.innerHTML = '<div class="project-list-empty">No projects yet</div>';
    return;
  }
  list.innerHTML = _projects.map((p) => {
    const warn = p.working_dir_warning
      ? `<span class="project-warn-dot" title="${esc(p.working_dir_warning)}">!</span>`
      : '';
    return `<button type="button" class="list-item project-list-item${p.id === _openProjectId ? ' active' : ''}" data-project-id="${esc(p.id)}">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;opacity:0.55;"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg>
      <span class="grow project-list-title">${esc(p.title || p.id)}${warn}${_statusBadge(p)}</span>
    </button>`;
  }).join('');
}

async function _validateDir(path) {
  const res = await fetch(`${API_BASE}/api/projects/validate-dir`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ working_dir: path }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Validation failed');
  return data;
}

async function _browseDir(path) {
  const q = path ? `?path=${encodeURIComponent(path)}` : '';
  const res = await fetch(`${API_BASE}/api/projects/browse-dir${q}`, {
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Browse failed');
  return data;
}

async function _resolveNativeDir(folderName, relativeHint = '') {
  const res = await fetch(`${API_BASE}/api/projects/resolve-dir`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      folder_name: folderName,
      relative_hint: relativeHint,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Could not resolve folder');
  return data;
}

function _folderNameFromWebkitFiles(files) {
  const relPaths = [...files]
    .map((file) => file.webkitRelativePath || file.name || '')
    .filter(Boolean);
  if (!relPaths.length) return null;
  const parts = relPaths[0].split('/').filter(Boolean);
  if (!parts.length) return null;
  return {
    folderName: parts[0],
    relativeHint: parts.length > 1 ? parts.slice(0, -1).join('/') : parts[0],
  };
}

function _startWebkitDirPick() {
  return new Promise((resolve) => {
    const picker = document.createElement('input');
    picker.type = 'file';
    picker.webkitdirectory = true;
    picker.style.display = 'none';
    picker.addEventListener('change', () => {
      const files = [...(picker.files || [])];
      picker.remove();
      if (!files.length) {
        resolve(null);
        return;
      }
      resolve(_folderNameFromWebkitFiles(files));
    });
    document.body.appendChild(picker);
    picker.click();
  });
}

/** Start the OS folder picker synchronously (must run inside the click handler). */
function _beginNativeFolderPick() {
  if (window.showDirectoryPicker) {
    return window.showDirectoryPicker({ mode: 'read' })
      .then((handle) => (handle?.name ? { folderName: handle.name, relativeHint: '' } : null))
      .catch((err) => {
        if (err?.name === 'AbortError') return null;
        throw err;
      });
  }
  return _startWebkitDirPick();
}

function _setPathInput(input, value) {
  if (!input || !value) return;
  input.value = value;
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

async function _pickResolvedCandidate(candidates, title = 'Multiple folders found') {
  if (!candidates?.length) return null;
  if (candidates.length === 1) return candidates[0];
  return new Promise((resolve) => {
    let overlay = document.getElementById('project-dir-candidate-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'project-dir-candidate-overlay';
      overlay.className = 'modal project-dir-browse-overlay';
      overlay.innerHTML =
        '<div class="modal-content styled-confirm-box" role="dialog" aria-modal="true">' +
          '<div class="modal-header"><h4 id="project-dir-candidate-title"></h4></div>' +
          '<div class="modal-body">' +
            '<p class="admin-toggle-sub">Pick the folder on the server that matches your selection.</p>' +
            '<div id="project-dir-candidate-list" class="project-dir-browse-list"></div>' +
          '</div>' +
          '<div class="modal-footer">' +
            '<button type="button" id="project-dir-candidate-cancel" class="confirm-btn confirm-btn-secondary">Cancel</button>' +
          '</div>' +
        '</div>';
      document.body.appendChild(overlay);
    }

    const titleEl = overlay.querySelector('#project-dir-candidate-title');
    const listEl = overlay.querySelector('#project-dir-candidate-list');
    const cancelBtn = overlay.querySelector('#project-dir-candidate-cancel');
    titleEl.textContent = title;
    listEl.replaceChildren();
    for (const candidate of candidates) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'project-dir-browse-row';
      btn.dataset.path = candidate;
      btn.textContent = candidate;
      btn.title = candidate;
      listEl.appendChild(btn);
    }

    function cleanup(result) {
      overlay.classList.add('hidden');
      overlay.style.display = 'none';
      cancelBtn.removeEventListener('click', onCancel);
      listEl.removeEventListener('click', onPick);
      overlay.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      resolve(result);
    }
    function onCancel() { cleanup(null); }
    function onBackdrop(e) { if (e.target === overlay) cleanup(null); }
    function onKey(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        cleanup(null);
      }
    }
    function onPick(e) {
      const btn = e.target.closest('[data-path]');
      if (!btn?.dataset.path) return;
      cleanup(btn.dataset.path);
    }

    cancelBtn.addEventListener('click', onCancel);
    listEl.addEventListener('click', onPick);
    overlay.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
    overlay.classList.remove('hidden');
    overlay.style.display = '';
  });
}

async function _applyNativeFolderSelection(input, pickPromise) {
  let picked;
  try {
    picked = await pickPromise;
  } catch (err) {
    uiModule.showToast?.(err.message || 'Folder picker unavailable', 4000);
    return false;
  }
  if (!picked?.folderName) return false;

  const provisional = picked.folderName.includes('/')
    ? picked.folderName
    : `~/${picked.folderName}`;
  _setPathInput(input, provisional);

  try {
    const resolved = await _resolveNativeDir(picked.folderName, picked.relativeHint || '');
    if (resolved.path) {
      _setPathInput(input, resolved.path);
      uiModule.showToast?.('Folder linked to server path', 3000);
      return true;
    }
    if (resolved.candidates?.length) {
      const chosen = await _pickResolvedCandidate(resolved.candidates);
      if (chosen) {
        _setPathInput(input, chosen);
        uiModule.showToast?.('Folder linked to server path', 3000);
        return true;
      }
      if (resolved.guess) _setPathInput(input, resolved.guess);
      else _setPathInput(input, provisional);
      uiModule.showToast?.('Using best guess — confirm the path or use Browse server folders', 5000);
      return true;
    }
    if (resolved.guess) {
      _setPathInput(input, resolved.guess);
    }
    uiModule.showToast?.(
      resolved.guess
        ? 'Confirm the resolved path below, or use Browse server folders to adjust'
        : 'Folder name captured — confirm the full server path below',
      5000,
    );
    return true;
  } catch (err) {
    uiModule.showToast?.(err.message || 'Could not resolve folder on server — edit path if needed', 4000);
    return true;
  }
}

async function _browseServerDirectory(initialPath = '', onReady = null) {
  const overlay = _ensureDirPromptOverlay();
  const mainPanel = overlay.querySelector('#project-dir-prompt-main');
  const browsePanel = overlay.querySelector('#project-dir-inline-browse');
  const pathEl = overlay.querySelector('#project-dir-browse-path');
  const listEl = overlay.querySelector('#project-dir-browse-list');
  const noteEl = overlay.querySelector('#project-dir-browse-note');
  const upBtn = overlay.querySelector('#project-dir-browse-up');
  const backBtn = overlay.querySelector('#project-dir-browse-back');
  const selectBtn = overlay.querySelector('#project-dir-browse-select');
  const footerEl = overlay.querySelector('.modal-footer');
  if (!browsePanel || !listEl) return null;

  let current = { path: '', parent: null, entries: [], truncated: false };
  let settled = false;

  return new Promise((resolve) => {
    async function loadBrowse(path) {
      listEl.innerHTML = '<div class="project-list-empty">Loading…</div>';
      if (noteEl) noteEl.textContent = '';
      try {
        current = await _browseDir(path);
      } catch (err) {
        listEl.innerHTML = `<div class="project-list-empty">${esc(err.message || 'Browse failed')}</div>`;
        return;
      }
      if (pathEl) pathEl.textContent = current.path || '';
      if (upBtn) upBtn.disabled = !current.parent;
      if (noteEl) {
        noteEl.textContent = current.truncated
          ? 'Showing first 300 folders — narrow down with Up or type a path.'
          : 'Click a folder to open it. Select this folder uses the path shown above.';
      }
      if (!current.entries?.length) {
        listEl.innerHTML = '<div class="project-list-empty">No subfolders — use Select this folder</div>';
        return;
      }
      const frag = document.createDocumentFragment();
      for (const entry of current.entries) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'project-dir-browse-row';
        btn.dataset.path = entry.path;
        btn.textContent = entry.name;
        btn.title = entry.path;
        frag.appendChild(btn);
      }
      listEl.replaceChildren(frag);
    }

    function finish(result) {
      if (settled) return;
      settled = true;
      browsePanel.classList.add('hidden');
      mainPanel?.classList.remove('hidden');
      footerEl?.classList.remove('hidden');
      upBtn?.removeEventListener('click', onUp);
      backBtn?.removeEventListener('click', onBack);
      selectBtn?.removeEventListener('click', onSelect);
      listEl?.removeEventListener('click', onListClick);
      resolve(result);
    }

    function onUp() {
      if (current.parent) void loadBrowse(current.parent);
    }
    function onBack() { finish(null); }
    function onSelect() { finish(current.path || null); }
    function onListClick(e) {
      const btn = e.target.closest('[data-path]');
      if (!btn?.dataset.path) return;
      void loadBrowse(btn.dataset.path);
    }

    onReady?.(onBack);

    mainPanel?.classList.add('hidden');
    footerEl?.classList.add('hidden');
    browsePanel.classList.remove('hidden');
    upBtn?.addEventListener('click', onUp);
    backBtn?.addEventListener('click', onBack);
    selectBtn?.addEventListener('click', onSelect);
    listEl.addEventListener('click', onListClick);
    void loadBrowse(initialPath);
  });
}

function _ensureDirPromptOverlay() {
  document.getElementById('project-dir-browse-overlay')?.remove();
  let overlay = document.getElementById('project-dir-prompt-overlay');
  if (overlay && overlay.querySelector('#project-dir-inline-browse')) return overlay;
  overlay?.remove();

  overlay = document.createElement('div');
  overlay.id = 'project-dir-prompt-overlay';
  overlay.className = 'modal project-dir-prompt-overlay';
  overlay.innerHTML =
    '<div class="modal-content styled-confirm-box styled-prompt-box" role="dialog" aria-modal="true" aria-labelledby="project-dir-prompt-title">' +
      '<div class="modal-header"><h4 id="project-dir-prompt-title"></h4></div>' +
      '<div class="modal-body">' +
        '<div id="project-dir-prompt-main">' +
          '<p id="project-dir-prompt-msg"></p>' +
          '<input type="text" id="project-dir-prompt-input" class="styled-prompt-input" spellcheck="false" autocomplete="off" />' +
          '<div class="project-dir-prompt-actions">' +
            '<button type="button" id="project-dir-prompt-native" class="admin-btn-sm">System folder picker…</button>' +
            '<button type="button" id="project-dir-prompt-browse" class="admin-btn-sm">Browse server folders…</button>' +
          '</div>' +
        '</div>' +
        '<div id="project-dir-inline-browse" class="project-dir-inline-browse hidden">' +
          '<div id="project-dir-browse-path" class="project-dir-browse-path"></div>' +
          '<div id="project-dir-browse-note" class="admin-toggle-sub project-dir-browse-note"></div>' +
          '<div id="project-dir-browse-list" class="project-dir-browse-list"></div>' +
          '<div class="project-dir-inline-browse-actions">' +
            '<button type="button" id="project-dir-browse-up" class="confirm-btn confirm-btn-secondary">Up</button>' +
            '<button type="button" id="project-dir-browse-back" class="confirm-btn confirm-btn-secondary">Back</button>' +
            '<button type="button" id="project-dir-browse-select" class="confirm-btn confirm-btn-primary">Select this folder</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="modal-footer">' +
        '<button type="button" id="project-dir-prompt-cancel" class="confirm-btn confirm-btn-secondary">Cancel</button>' +
        '<button type="button" id="project-dir-prompt-ok" class="confirm-btn confirm-btn-primary"></button>' +
      '</div>' +
    '</div>';
  document.body.appendChild(overlay);
  return overlay;
}

async function promptWorkingDir({
  title = 'Project folder',
  message = 'Working directory on the machine where Nobody runs:',
  defaultValue = '',
  confirmText = 'Continue',
} = {}) {
  const overlay = _ensureDirPromptOverlay();
  const titleEl = overlay.querySelector('#project-dir-prompt-title');
  const msgEl = overlay.querySelector('#project-dir-prompt-msg');
  const input = overlay.querySelector('#project-dir-prompt-input');
  const okBtn = overlay.querySelector('#project-dir-prompt-ok');
  const cancelBtn = overlay.querySelector('#project-dir-prompt-cancel');
  const nativeBtn = overlay.querySelector('#project-dir-prompt-native');
  const browseBtn = overlay.querySelector('#project-dir-prompt-browse');
  const mainPanel = overlay.querySelector('#project-dir-prompt-main');
  const browsePanel = overlay.querySelector('#project-dir-inline-browse');
  const footerEl = overlay.querySelector('.modal-footer');
  const _prevFocus = document.activeElement;

  titleEl.textContent = title;
  msgEl.textContent = message || '';
  msgEl.style.display = message ? '' : 'none';
  input.value = defaultValue || '';
  input.placeholder = '/home/you/experiments/my-project';
  okBtn.textContent = confirmText;
  mainPanel?.classList.remove('hidden');
  browsePanel?.classList.add('hidden');
  footerEl?.classList.remove('hidden');

  return new Promise((resolve) => {
    let settled = false;
    let browseBack = null;

    function cleanup(result) {
      if (settled) return;
      settled = true;
      overlay.classList.add('hidden');
      overlay.style.display = 'none';
      mainPanel?.classList.remove('hidden');
      browsePanel?.classList.add('hidden');
      footerEl?.classList.remove('hidden');
      okBtn.removeEventListener('click', onOk);
      cancelBtn.removeEventListener('click', onCancel);
      nativeBtn.removeEventListener('click', onNativeClick);
      browseBtn.removeEventListener('click', onBrowseClick);
      overlay.removeEventListener('click', onBackdrop);
      document.removeEventListener('keydown', onKey);
      input.removeEventListener('keydown', onInputKey);
      browseBtn.disabled = false;
      browseBack = null;
      try { _prevFocus?.focus?.(); } catch {}
      resolve(result);
    }
    function onOk() { cleanup((input.value || '').trim() || null); }
    function onCancel() { cleanup(null); }
    function onBackdrop(e) { if (e.target === overlay) cleanup(null); }
    function onKey(e) {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      if (browsePanel && !browsePanel.classList.contains('hidden')) {
        browseBack?.();
        return;
      }
      cleanup(null);
    }
    function onInputKey(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        onOk();
      }
    }
    function onNativeClick() {
      let pickPromise;
      try {
        pickPromise = _beginNativeFolderPick();
      } catch (err) {
        uiModule.showToast?.(err.message || 'Folder picker unavailable', 4000);
        return;
      }
      void _applyNativeFolderSelection(input, pickPromise).then((applied) => {
        if (!applied) return;
        input.focus();
        input.select();
      });
    }
    async function onBrowseClick() {
      if (browseBtn.disabled) return;
      browseBtn.disabled = true;
      try {
        browseBack = null;
        const picked = await _browseServerDirectory(input.value.trim(), (backFn) => {
          browseBack = backFn;
        });
        browseBack = null;
        if (picked) {
          input.value = picked;
          input.focus();
          input.select();
        }
      } finally {
        browseBtn.disabled = false;
      }
    }

    okBtn.addEventListener('click', onOk);
    cancelBtn.addEventListener('click', onCancel);
    nativeBtn.addEventListener('click', onNativeClick);
    browseBtn.addEventListener('click', onBrowseClick);
    overlay.addEventListener('click', onBackdrop);
    document.addEventListener('keydown', onKey);
    input.addEventListener('keydown', onInputKey);

    overlay.classList.remove('hidden');
    overlay.style.display = '';
    requestAnimationFrame(() => {
      input.focus();
      input.select();
    });
  });
}

async function createProjectDialog() {
  const title = await styledPrompt('Project name:', {
    title: 'New project',
    placeholder: 'e.g. AlphaFold comparison',
    confirmText: 'Next',
  });
  if (!title?.trim()) return;

  const workingDir = await promptWorkingDir({
    title: 'Project folder (depth boundary)',
    confirmText: 'Create',
  });
  if (!workingDir) return;

  let validation;
  try {
    validation = await _validateDir(workingDir);
  } catch (e) {
    uiModule.showToast?.(e.message || 'Could not validate path', 4000);
    return;
  }
  if (validation.working_dir_status !== 'ok') {
    uiModule.showToast?.(`Folder status: ${validation.working_dir_status}`, 5000);
    return;
  }
  if (validation.working_dir_warning) {
    uiModule.showToast?.(validation.working_dir_warning, 6000);
  }

  const res = await fetch(`${API_BASE}/api/projects`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      title: title.trim(),
      working_dir: validation.working_dir || workingDir,
    }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    uiModule.showToast?.(data.detail || 'Create failed', 4000);
    return;
  }
  if (data.project) _upsertProjectCache(data.project);
  await refreshProjectList();
  uiModule.showToast?.('Project created');
  if (data.project?.id) openProjectWorkspace(data.project.id);
}

export async function refreshProjectList() {
  try {
    await _fetchProjects();
    _renderProjectList();
  } catch (e) {
    uiModule.showToast?.(e.message || 'Projects load failed', 4000);
  }
}

const LINK_TYPE_LABELS = {
  paper: 'Paper',
  research: 'Research',
  document: 'Document',
  collection: 'Collection',
  task: 'Task',
  project: 'Project',
  note: 'Note',
  memory: 'Memory',
  skill: 'Skill',
};

const LINK_TYPE_ORDER = {
  research: 0,
  paper: 1,
  document: 2,
  collection: 3,
  task: 4,
  memory: 5,
  skill: 6,
  note: 7,
  project: 8,
};

function _projectTypeBadge(node) {
  const type = (node?.type || 'document').toLowerCase();
  return `<span class="kg-type kg-type-${esc(type)}">${esc(LINK_TYPE_LABELS[type] || type)}</span>`;
}

function _projectLinkTitle(node, nodeId) {
  if (node?.title) return node.title;
  if (nodeId) return nodeId.replace(/^[^:]+:/, '');
  return 'Untitled';
}

function _projectLinkRows(fromId, linksData) {
  const rows = [];
  const seen = new Set();

  const push = (row, linkedId, direction) => {
    if (!linkedId || linkedId === fromId || seen.has(linkedId)) return;
    seen.add(linkedId);
    rows.push({ row, linkedId, direction });
  };

  for (const row of linksData?.outgoing || []) {
    const edge = row.edge || {};
    const linkedId = row.node?.id || edge.to || '';
    push(row, linkedId, 'out');
  }
  for (const row of linksData?.incoming || []) {
    const edge = row.edge || {};
    const linkedId = row.node?.id || edge.from || '';
    push(row, linkedId, 'in');
  }

  rows.sort((a, b) => {
    const ta = (a.row.node?.type || a.linkedId.split(':')[0] || 'zzz').toLowerCase();
    const tb = (b.row.node?.type || b.linkedId.split(':')[0] || 'zzz').toLowerCase();
    const oa = LINK_TYPE_ORDER[ta] ?? 99;
    const ob = LINK_TYPE_ORDER[tb] ?? 99;
    if (oa !== ob) return oa - ob;
    return _projectLinkTitle(a.row.node, a.linkedId).localeCompare(
      _projectLinkTitle(b.row.node, b.linkedId),
    );
  });
  return rows;
}

function _renderLinksRail(project, linksData) {
  const mount = document.getElementById('project-links-mount');
  if (!mount || !project?.id) return;

  const fromId = _projectNodeId(project.id);
  const linkRows = _projectLinkRows(fromId, linksData);
  const staleRows = linkRows.filter(({ row }) => !row.node);
  const staleCount = staleRows.length;
  const rows = linkRows.map(({ row, linkedId, direction }) => {
    const n = row.node;
    const edge = row.edge || {};
    const kind = edge.kind || 'related';
    const stale = !n;
    const removeFrom = direction === 'out' ? fromId : linkedId;
    const removeTo = direction === 'out' ? linkedId : fromId;
    const manual = (edge.source || 'manual') === 'manual';
    const title = _projectLinkTitle(n, linkedId);
    const badge = n ? _projectTypeBadge(n) : `<span class="kg-type kg-type-research">?</span>`;
    return `<div class="kg-link-row-wrap project-link-row-wrap${stale ? ' project-link-row-stale' : ''}">
      <button type="button" class="kg-link-row project-link-row" data-node-id="${esc(linkedId)}">
        <span class="kg-link-kind">${esc(kind)}</span>
        ${badge}
        <span class="kg-node-title">${esc(title)}</span>
        ${stale ? '<span class="project-link-stale">missing</span>' : ''}
      </button>
      ${manual ? `<button type="button" class="kg-link-remove project-link-remove" data-from="${esc(removeFrom)}" data-to="${esc(removeTo)}" data-kind="${esc(kind)}" title="Remove link" aria-label="Remove link">×</button>` : ''}
    </div>`;
  }).join('');

  mount.innerHTML = `
    <div class="project-links-head">
      <div class="project-links-head-row">
        <div class="project-links-head-text">
          <div class="project-links-title">Linked knowledge</div>
          <div class="project-links-sub">Breadth boundary — explicit links only (not bulk Zotero import)</div>
          ${staleCount ? `<div class="project-links-stale-hint">${staleCount} stale link${staleCount === 1 ? '' : 's'} — node missing from graph</div>` : ''}
        </div>
        <div class="project-links-head-actions">
          <button type="button" class="admin-btn-sm" id="project-links-browse-btn" title="Open this project in Links">Browse in Links</button>
          ${staleCount ? `<button type="button" class="admin-btn-sm project-links-stale-btn" id="project-links-remove-stale-btn">Remove stale (${staleCount})</button>` : ''}
        </div>
      </div>
    </div>
    <div class="project-links-list">${rows || '<div class="kg-link-empty">No links yet — search below to add</div>'}</div>
    <div id="project-link-picker" class="project-link-picker"></div>`;

  const picker = mount.querySelector('#project-link-picker');
  if (picker) {
    void knowledgeModule.mountGraphLinkPicker(picker, fromId, {
      onUpdate: () => _reloadWorkspaceLinks(project.id),
    });
  }

  mount.querySelector('#project-links-browse-btn')?.addEventListener('click', () => {
    void knowledgeModule.openKnowledgeAtNode(fromId);
  });

  mount.querySelector('#project-links-remove-stale-btn')?.addEventListener('click', () => {
    void (async () => {
      const btn = mount.querySelector('#project-links-remove-stale-btn');
      if (btn) btn.disabled = true;
      let removed = 0;
      try {
        for (const { row, linkedId, direction } of staleRows) {
          const edge = row.edge || {};
          const removeFrom = direction === 'out' ? fromId : linkedId;
          const removeTo = direction === 'out' ? linkedId : fromId;
          await knowledgeModule.removeGraphLink(removeFrom, removeTo, edge.kind || 'related');
          removed += 1;
        }
        uiModule.showToast?.(removed ? `Removed ${removed} stale link${removed === 1 ? '' : 's'}` : 'No stale links');
        await _reloadWorkspaceLinks(project.id);
      } catch (e) {
        uiModule.showToast?.(e.message || 'Could not remove stale links', 4000);
      } finally {
        if (btn) btn.disabled = false;
      }
    })();
  });

  mount.querySelectorAll('.project-link-row').forEach((btn) => {
    btn.addEventListener('click', () => {
      const id = btn.dataset.nodeId;
      if (!id) return;
      if (btn.closest('.project-link-row-stale')) {
        uiModule.showToast?.('Graph node missing — remove this stale link or rebuild Links.', 4000);
        return;
      }
      void knowledgeModule.openKnowledgeAtNode(id);
    });
  });

  mount.querySelectorAll('.project-link-remove').forEach((btn) => {
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      if (!btn.dataset.from || !btn.dataset.to) return;
      btn.disabled = true;
      try {
        await knowledgeModule.removeGraphLink(btn.dataset.from, btn.dataset.to, btn.dataset.kind);
        uiModule.showToast?.('Link removed');
        await _reloadWorkspaceLinks(project.id);
      } catch (e) {
        uiModule.showToast?.(e.message || 'Remove failed', 4000);
      } finally {
        btn.disabled = false;
      }
    });
  });
}

export async function refreshProjectWorkspaceLinks(projectId) {
  if (!_openProjectId || _openProjectId !== projectId) return;
  await _reloadWorkspaceLinks(projectId);
}

async function _reloadWorkspaceLinks(projectId) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectId)}/links`, {
    credentials: 'same-origin',
  });
  if (!res.ok) return;
  const links = await res.json();
  const project = _projects.find((p) => p.id === projectId) || await _fetchProject(projectId);
  _renderLinksRail(project, links);
}

function _setProjectMainVisible(show) {
  const panel = _workspaceRoot();
  const container = document.getElementById('chat-container');
  if (!panel || !container) return;
  if (show) {
    container.classList.add('project-active');
    container.classList.remove('welcome-active');
    panel.classList.remove('hidden');
    panel.setAttribute('aria-hidden', 'false');
    if (window.chatModule?.hideWelcomeScreen) window.chatModule.hideWelcomeScreen();
  } else {
    container.classList.remove('project-active');
    panel.classList.add('hidden');
    panel.setAttribute('aria-hidden', 'true');
  }
}

function _renderWorkspaceShell(project) {
  const root = _workspaceRoot();
  if (!root || !project) return;

  const currentMetaEl = uiModule.el('current-meta');
  if (currentMetaEl) currentMetaEl.textContent = project.title || project.id;

  const meta = root.querySelector('#project-workspace-meta');
  if (meta) {
    const bits = [
      project.working_dir ? `Depth · ${project.working_dir}` : '',
      project.working_dir_status && project.working_dir_status !== 'ok'
        ? `status: ${project.working_dir_status}`
        : '',
    ].filter(Boolean);
    meta.textContent = bits.join(' · ');
    meta.title = [project.working_dir_warning, project.working_dir].filter(Boolean).join('\n');
  }

  const warnEl = root.querySelector('#project-workspace-warning');
  if (warnEl) {
    if (project.working_dir_warning) {
      warnEl.textContent = project.working_dir_warning;
      warnEl.classList.remove('hidden');
    } else {
      warnEl.textContent = '';
      warnEl.classList.add('hidden');
    }
  }

  const statusEl = root.querySelector('#project-workspace-status');
  if (statusEl) {
    if (project.working_dir_status === 'ok') {
      statusEl.textContent = 'Working directory OK — edit files in the tree; saves to disk automatically';
      statusEl.className = 'project-workspace-status ok';
    } else {
      statusEl.textContent = `Working directory ${project.working_dir_status || 'unknown'} — fix path before running code`;
      statusEl.className = 'project-workspace-status bad';
    }
  }
}

async function _restoreWorkspaceState(projectId) {
  const openPath = workspaceState.getOpenFile(projectId);
  if (!openPath) return;
  const ok = await fileTreeModule.openPath(openPath);
  if (!ok) workspaceState.saveOpenFile(projectId, null);
}

export async function openProjectWorkspace(projectId) {
  if (!projectId) return;
  const panel = _workspaceRoot();
  if (!panel) return;

  if (_openProjectId && _openProjectId !== projectId && editorModule.isDirty()) {
    const ok = await editorModule.confirmCloseIfDirty();
    if (!ok) return;
  }

  let project;
  try {
    project = await _fetchProject(projectId);
  } catch {
    uiModule.showToast?.('Project not found', 3000);
    return;
  }

  document.querySelectorAll('.list-item.active-session').forEach((el) => el.classList.remove('active-session'));

  _upsertProjectCache(project);
  _openProjectId = projectId;
  workspaceState.saveLastOpenProject(projectId);
  _renderProjectList();
  _renderWorkspaceShell(project);
  _setProjectMainVisible(true);
  _mountEditor(project);
  _mountFileTree(project);
  _mountRunPanel(project);
  _mountChatSidebar(project);
  await _restoreWorkspaceState(projectId);
  await _reloadWorkspaceLinks(projectId);
}

export async function closeProjectWorkspace({ restoreChat = true } = {}) {
  const wasOpen = !!_openProjectId;
  if (!wasOpen) return true;
  if (editorModule.isDirty()) {
    const ok = await editorModule.confirmCloseIfDirty();
    if (!ok) return false;
  }
  _doCloseProjectWorkspace({ restoreChat, wasOpen });
  return true;
}

function _doCloseProjectWorkspace({ restoreChat = true, wasOpen = false } = {}) {
  chatSidebarModule.unmount();
  fileTreeModule.unmount();
  editorModule.unmount();
  runPanelModule.unmount();
  _openProjectFile = null;
  _setProjectMainVisible(false);
  _openProjectId = null;
  _renderProjectList();
  if (!restoreChat || !wasOpen) return;
  const sessionId = window.sessionModule?.getCurrentSessionId?.() || window.currentSessionId;
  if (sessionId && window.sessionModule?.selectSession) {
    void window.sessionModule.selectSession(sessionId, { keepSidebar: true });
    return;
  }
  const currentMetaEl = uiModule.el('current-meta');
  if (currentMetaEl) currentMetaEl.textContent = 'Nobody Chat';
  window.chatModule?.showWelcomeScreen?.();
}

async function _editWorkingDir() {
  if (!_openProjectId) return;
  if (editorModule.isDirty()) {
    const ok = await editorModule.confirmCloseIfDirty();
    if (!ok) return;
  }
  const project = _projects.find((p) => p.id === _openProjectId);
  const next = await promptWorkingDir({
    title: 'Change project folder',
    defaultValue: project?.working_dir || '',
    confirmText: 'Validate & save',
  });
  if (!next) return;

  let validation;
  try {
    validation = await _validateDir(next);
  } catch (e) {
    uiModule.showToast?.(e.message || 'Validation failed', 4000);
    return;
  }
  if (validation.working_dir_status !== 'ok') {
    uiModule.showToast?.(`Folder status: ${validation.working_dir_status}`, 5000);
    return;
  }
  if (validation.working_dir_warning) {
    uiModule.showToast?.(validation.working_dir_warning, 6000);
  }

  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_openProjectId)}`, {
    method: 'PATCH',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ working_dir: validation.working_dir || next }),
  });
  if (!res.ok) {
    uiModule.showToast?.('Update failed', 3000);
    return;
  }
  const updated = (await res.json()).project;
  _upsertProjectCache(updated);
  _renderWorkspaceShell(updated);
  _mountEditor(updated);
  _mountFileTree(updated);
  _mountRunPanel(updated);
  _mountChatSidebar(updated);
  await refreshProjectList();
  uiModule.showToast?.('Working directory updated');
}

export function initProjects() {
  const createBtn = document.getElementById('project-create-btn');
  createBtn?.addEventListener('click', (e) => {
    e.stopPropagation();
    void createProjectDialog();
  });

  const list = document.getElementById('project-list');
  list?.addEventListener('click', (e) => {
    const row = e.target.closest('[data-project-id]');
    if (!row?.dataset.projectId) return;
    void openProjectWorkspace(row.dataset.projectId);
  });

  document.getElementById('project-edit-dir-btn')?.addEventListener('click', () => void _editWorkingDir());

  document.getElementById('project-rename-btn')?.addEventListener('click', async () => {
    if (!_openProjectId) return;
    const project = _projects.find((p) => p.id === _openProjectId);
    const name = await styledPrompt('Rename project:', {
      title: 'Rename',
      defaultValue: project?.title || '',
      confirmText: 'Save',
    });
    if (!name?.trim()) return;
    const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_openProjectId)}`, {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: name.trim() }),
    });
    if (!res.ok) {
      uiModule.showToast?.('Rename failed', 3000);
      return;
    }
    const updated = (await res.json()).project;
    _upsertProjectCache(updated);
    await refreshProjectList();
    _renderWorkspaceShell(updated);
    uiModule.showToast?.('Renamed');
  });

  document.getElementById('project-archive-btn')?.addEventListener('click', async () => {
    if (!_openProjectId) return;
    if (editorModule.isDirty()) {
      const ok = await editorModule.confirmCloseIfDirty();
      if (!ok) return;
    }
    if (!await uiModule.styledConfirm('Archive this project? It will be hidden from the list.', { confirmText: 'Archive', danger: true })) return;
    const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_openProjectId)}`, {
      method: 'DELETE',
      credentials: 'same-origin',
    });
    if (!res.ok) {
      uiModule.showToast?.('Archive failed', 3000);
      return;
    }
    await closeProjectWorkspace({ restoreChat: true });
    await refreshProjectList();
    uiModule.showToast?.('Project archived');
  });

  void refreshProjectList();
}

export default {
  initProjects,
  refreshProjectList,
  openProjectWorkspace,
  closeProjectWorkspace,
  createProjectDialog,
  refreshProjectWorkspaceLinks,
};

if (typeof window !== 'undefined') {
  window.openProjectWorkspace = openProjectWorkspace;
  window.closeProjectWorkspace = closeProjectWorkspace;
  window.refreshProjectWorkspaceLinks = refreshProjectWorkspaceLinks;
  window.getActiveProjectFile = () => editorModule.getOpenPath?.() || _openProjectFile || null;
  window.saveActiveProjectFile = (opts) => editorModule.save?.(opts || { silent: true });
}
