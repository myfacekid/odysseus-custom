/**
 * Project files pop-out sheet (context layer F1–F4).
 *
 * Dedicated modal: read-only file tree (left) + Documents-style reader (right).
 * Promote copies into Library — never edits cwd from this surface.
 */
import uiModule from '../ui.js';
import contentViewer from '../ui/contentViewer.js';
import { getActiveProjectId } from './activeState.js';

const API_BASE = window.API_BASE || window.location.origin;

const FOLDER_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg>`;
const FILE_ICON = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`;
const CHEVRON = `<svg class="project-files-tree-chevron" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>`;

const CODE_EXTS = new Set([
  'py', 'js', 'ts', 'tsx', 'jsx', 'json', 'css', 'html', 'htm', 'rs', 'go', 'java',
  'c', 'cpp', 'h', 'hpp', 'sh', 'bash', 'zsh', 'yml', 'yaml', 'toml', 'sql', 'r',
  'rb', 'php', 'swift', 'kt', 'scala', 'lua', 'vim',
]);
const MD_EXTS = new Set(['md', 'markdown', 'mdx']);

function _esc(s) {
  return uiModule.esc ? uiModule.esc(s) : String(s || '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _ext(path) {
  const base = (path || '').split('/').pop() || '';
  const i = base.lastIndexOf('.');
  return i >= 0 ? base.slice(i + 1).toLowerCase() : '';
}

function _langForPath(path) {
  const e = _ext(path);
  const map = {
    py: 'python', js: 'javascript', ts: 'typescript', tsx: 'typescript', jsx: 'javascript',
    json: 'json', css: 'css', html: 'html', htm: 'html', rs: 'rust', go: 'go',
    sh: 'bash', bash: 'bash', yml: 'yaml', yaml: 'yaml', toml: 'toml', sql: 'sql',
    md: 'markdown', markdown: 'markdown', r: 'r',
  };
  return map[e] || 'text';
}

function _viewerKind(path) {
  const e = _ext(path);
  if (MD_EXTS.has(e)) return 'markdown';
  if (CODE_EXTS.has(e)) return 'code';
  return 'text';
}

async function _listDir(projectId, path) {
  const q = encodeURIComponent(path || '.');
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectId)}/files?path=${q}`, {
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Could not list files');
  return data;
}

async function _readFile(projectId, path) {
  const q = encodeURIComponent(path || '');
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(projectId)}/file?path=${q}`, {
    credentials: 'same-origin',
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Could not read file');
  return data;
}

function _ensureOverlay() {
  let el = document.getElementById('project-files-sheet');
  if (el) return el;
  el = document.createElement('div');
  el.id = 'project-files-sheet';
  el.className = 'modal project-files-sheet hidden';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-modal', 'true');
  el.setAttribute('aria-labelledby', 'project-files-sheet-title');
  el.innerHTML = `
    <div class="modal-content project-files-sheet-content">
      <div class="modal-header project-files-sheet-header">
        <div class="project-files-sheet-header-text">
          <h3 id="project-files-sheet-title">Project files</h3>
          <p class="project-files-sheet-cwd" id="project-files-sheet-cwd" hidden></p>
        </div>
        <button type="button" class="modal-close" id="project-files-sheet-close" aria-label="Close">&times;</button>
      </div>
      <p class="project-files-sheet-sub">Browse the project folder (read-only). Add to Library copies a file into Documents / Notes — it does not move or sync the tree.</p>
      <div class="project-files-sheet-body">
        <aside class="project-files-tree-pane" aria-label="Project file tree">
          <div class="project-files-tree" id="project-files-tree" role="tree"></div>
        </aside>
        <section class="project-files-reader-pane" aria-label="File preview">
          <div class="project-files-reader" id="project-files-reader">
            <div class="project-files-reader-empty" id="project-files-reader-empty">
              <span class="project-files-reader-empty-icon" aria-hidden="true">${FOLDER_ICON}</span>
              <span class="project-files-reader-empty-title">Select a file</span>
              <span class="project-files-reader-empty-msg">Preview opens here — same reading chrome as Documents. Promote when you want an editable Library copy.</span>
            </div>
            <div class="project-files-reader-active hidden" id="project-files-reader-active">
              <div class="project-files-reader-chrome">
                <div class="project-files-reader-chrome-main">
                  <span class="project-files-cwd-badge" title="File on disk in the project working directory">
                    ${FILE_ICON}
                    <span>Project file</span>
                  </span>
                  <span class="project-files-reader-name" id="project-files-reader-name"></span>
                </div>
                <div class="project-files-reader-chrome-meta">
                  <span class="project-files-reader-path" id="project-files-reader-path"></span>
                  <button type="button" class="confirm-btn-primary project-files-promote-open-btn" id="project-files-promote-open-btn">Add to Library…</button>
                </div>
              </div>
              <div class="project-files-reader-body content-view-host" id="project-files-reader-body"></div>
            </div>
          </div>
          <div class="project-files-promote-panel hidden" id="project-files-promote-panel">
            <div class="project-files-promote-title">Add to Library</div>
            <p class="project-files-promote-hint">Creates a Library copy. The project folder file stays put.</p>
            <div class="project-files-promote-path" id="project-files-promote-path"></div>
            <label class="project-files-field">
              <span>Title</span>
              <input type="text" id="project-files-promote-title" maxlength="200" />
            </label>
            <label class="project-files-field">
              <span>Destination</span>
              <select id="project-files-promote-type">
                <option value="document">Document</option>
                <option value="note">Note</option>
                <option value="ingest">Library ingest (corpus)</option>
              </select>
            </label>
            <label class="project-files-check">
              <input type="checkbox" id="project-files-promote-link" checked />
              <span>Also link to this project in Links</span>
            </label>
            <div class="project-files-promote-actions">
              <button type="button" class="confirm-btn-secondary" id="project-files-promote-cancel">Back</button>
              <button type="button" class="confirm-btn-primary" id="project-files-promote-do">Add to Library</button>
            </div>
          </div>
        </section>
      </div>
    </div>`;
  document.body.appendChild(el);
  return el;
}

function _sortEntries(entries) {
  return [...(entries || [])].sort((a, b) => {
    if (a.type !== b.type) return a.type === 'dir' ? -1 : 1;
    return (a.name || '').localeCompare(b.name || '', undefined, { sensitivity: 'base' });
  });
}

/**
 * @param {object} opts
 * @param {string} opts.projectId
 * @param {string} [opts.title]
 * @param {string} [opts.workingDir]
 */
export async function openProjectFilePicker(projectId, { title, workingDir } = {}) {
  const pid = projectId || getActiveProjectId();
  if (!pid) {
    uiModule.showToast?.('Set an active project first', 3000);
    return;
  }

  const overlay = _ensureOverlay();
  const treeEl = overlay.querySelector('#project-files-tree');
  const titleEl = overlay.querySelector('#project-files-sheet-title');
  const cwdEl = overlay.querySelector('#project-files-sheet-cwd');
  const emptyEl = overlay.querySelector('#project-files-reader-empty');
  const activeEl = overlay.querySelector('#project-files-reader-active');
  const readerBody = overlay.querySelector('#project-files-reader-body');
  const readerName = overlay.querySelector('#project-files-reader-name');
  const readerPath = overlay.querySelector('#project-files-reader-path');
  const promotePanel = overlay.querySelector('#project-files-promote-panel');
  const promotePathEl = overlay.querySelector('#project-files-promote-path');
  const promoteTitle = overlay.querySelector('#project-files-promote-title');
  const promoteType = overlay.querySelector('#project-files-promote-type');
  const promoteLink = overlay.querySelector('#project-files-promote-link');
  const promoteOpenBtn = overlay.querySelector('#project-files-promote-open-btn');

  titleEl.textContent = title ? `Files · ${title}` : 'Project files';
  if (workingDir) {
    cwdEl.hidden = false;
    cwdEl.textContent = workingDir;
  } else {
    cwdEl.hidden = true;
    cwdEl.textContent = '';
    // Best-effort: fetch project meta for cwd hint
    void fetch(`${API_BASE}/api/projects/${encodeURIComponent(pid)}`, { credentials: 'same-origin' })
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        const wd = data?.project?.working_dir || data?.working_dir;
        if (wd && !overlay.classList.contains('hidden')) {
          cwdEl.hidden = false;
          cwdEl.textContent = wd;
        }
      })
      .catch(() => {});
  }

  let selectedPath = null;
  let settled = false;
  const _prevFocus = document.activeElement;
  /** @type {Map<string, HTMLElement>} */
  const loadedDirs = new Map();

  function cleanup() {
    if (settled) return;
    settled = true;
    overlay.classList.add('hidden');
    overlay.classList.remove('project-files-sheet-enter');
    document.removeEventListener('keydown', onKey);
    treeEl.onclick = null;
    readerBody.innerHTML = '';
    selectedPath = null;
    loadedDirs.clear();
    try { _prevFocus?.focus?.(); } catch { /* ignore */ }
  }

  function hidePromote() {
    promotePanel.classList.add('hidden');
    overlay.querySelector('.project-files-sheet-body')?.classList.remove('promote-open');
  }

  function showPromote() {
    if (!selectedPath) return;
    const name = selectedPath.split('/').pop() || selectedPath;
    promotePathEl.textContent = selectedPath;
    promoteTitle.value = name;
    promoteType.value = 'document';
    promoteLink.checked = true;
    promotePanel.classList.remove('hidden');
    overlay.querySelector('.project-files-sheet-body')?.classList.add('promote-open');
    promotePanel.classList.remove('project-files-promote-enter');
    void promotePanel.offsetWidth;
    promotePanel.classList.add('project-files-promote-enter');
    promoteTitle.focus();
    promoteTitle.select();
  }

  function onKey(e) {
    if (e.key !== 'Escape') return;
    e.preventDefault();
    if (!promotePanel.classList.contains('hidden')) {
      hidePromote();
      return;
    }
    cleanup();
  }

  function clearReader() {
    selectedPath = null;
    emptyEl.classList.remove('hidden');
    activeEl.classList.add('hidden');
    readerBody.innerHTML = '';
    treeEl.querySelectorAll('.project-files-tree-row.is-selected').forEach((n) => {
      n.classList.remove('is-selected');
    });
    hidePromote();
  }

  async function showFile(path) {
    selectedPath = path;
    hidePromote();
    treeEl.querySelectorAll('.project-files-tree-row.is-selected').forEach((n) => {
      n.classList.remove('is-selected');
    });
    for (const row of treeEl.querySelectorAll('.project-files-tree-row.is-file')) {
      if (row.dataset.path === path) {
        row.classList.add('is-selected');
        break;
      }
    }

    emptyEl.classList.add('hidden');
    activeEl.classList.remove('hidden');
    readerName.textContent = path.split('/').pop() || path;
    readerPath.textContent = path;
    readerBody.innerHTML = `<div class="project-files-reader-loading">Loading…</div>`;
    readerBody.classList.remove('project-files-reader-fade');
    void readerBody.offsetWidth;
    readerBody.classList.add('project-files-reader-fade');

    try {
      const data = await _readFile(pid, path);
      const content = data.content ?? '';
      const kind = _viewerKind(path);
      let body;
      if (kind === 'markdown') {
        body = contentViewer.createMarkdown({ content, className: 'doc-md-preview content-view-md project-files-view-md' });
      } else if (kind === 'code') {
        body = contentViewer.createCode({
          content,
          language: _langForPath(path),
          className: 'project-files-view-code',
        });
      } else {
        body = contentViewer.createCode({ content, language: 'text', className: 'project-files-view-code' });
      }
      readerBody.innerHTML = '';
      contentViewer.mountBody(readerBody, body);
    } catch (e) {
      readerBody.innerHTML = `
        <div class="project-files-reader-error">
          <strong>Can't preview this file</strong>
          <span>${_esc(e.message || 'Text preview only — binary or unreadable files are not supported here.')}</span>
        </div>`;
    }
  }

  function buildRow(entry, depth) {
    const isDir = entry.type === 'dir';
    const row = document.createElement('div');
    row.className = `project-files-tree-row ${isDir ? 'is-dir' : 'is-file'}`;
    row.setAttribute('role', 'treeitem');
    row.dataset.path = entry.path;
    row.dataset.type = isDir ? 'dir' : 'file';
    row.dataset.depth = String(depth);
    row.style.setProperty('--tree-depth', String(depth));
    if (isDir) row.setAttribute('aria-expanded', 'false');
    else row.setAttribute('aria-selected', 'false');
    row.innerHTML = `
      <span class="project-files-tree-indent" aria-hidden="true"></span>
      ${isDir ? `<button type="button" class="project-files-tree-toggle" data-toggle="${_esc(entry.path)}" aria-label="Expand folder">${CHEVRON}</button>` : '<span class="project-files-tree-toggle-spacer" aria-hidden="true"></span>'}
      <button type="button" class="project-files-tree-label" data-select="${_esc(entry.path)}" data-type="${isDir ? 'dir' : 'file'}">
        <span class="project-files-tree-icon">${isDir ? FOLDER_ICON : FILE_ICON}</span>
        <span class="project-files-tree-name">${_esc(entry.name)}</span>
      </button>`;
    return row;
  }

  async function expandDir(path, parentRow) {
    if (loadedDirs.has(path)) {
      const children = loadedDirs.get(path);
      const open = children.classList.toggle('is-collapsed') === false;
      parentRow?.setAttribute('aria-expanded', open ? 'true' : 'false');
      parentRow?.classList.toggle('is-expanded', open);
      return;
    }
    const depth = parentRow ? (Number(parentRow.dataset.depth) || 0) + 1 : 0;
    const children = document.createElement('div');
    children.className = 'project-files-tree-children';
    children.setAttribute('role', 'group');
    children.innerHTML = `<div class="project-files-tree-loading">Loading…</div>`;
    if (parentRow) {
      parentRow.insertAdjacentElement('afterend', children);
    } else {
      treeEl.appendChild(children);
    }
    loadedDirs.set(path, children);
    parentRow?.setAttribute('aria-expanded', 'true');
    parentRow?.classList.add('is-expanded');

    try {
      const data = await _listDir(pid, path === '' ? '.' : path);
      const entries = _sortEntries(data.entries);
      children.innerHTML = '';
      if (!entries.length) {
        children.innerHTML = `<div class="project-files-tree-empty">Empty folder</div>`;
        return;
      }
      for (const ent of entries) {
        children.appendChild(buildRow(ent, depth));
      }
    } catch (e) {
      children.innerHTML = `<div class="project-files-tree-empty">${_esc(e.message || 'Failed')}</div>`;
    }
  }

  async function loadRoot() {
    treeEl.innerHTML = `<div class="project-files-tree-loading">Loading…</div>`;
    loadedDirs.clear();
    clearReader();
    try {
      const data = await _listDir(pid, '.');
      const entries = _sortEntries(data.entries);
      treeEl.innerHTML = '';
      if (!entries.length) {
        treeEl.innerHTML = `<div class="project-files-tree-empty">This project folder is empty.</div>`;
        return;
      }
      const rootChildren = document.createElement('div');
      rootChildren.className = 'project-files-tree-children is-root';
      rootChildren.setAttribute('role', 'group');
      for (const ent of entries) {
        rootChildren.appendChild(buildRow(ent, 0));
      }
      treeEl.appendChild(rootChildren);
      loadedDirs.set('.', rootChildren);
    } catch (e) {
      treeEl.innerHTML = `<div class="project-files-tree-empty">${_esc(e.message || 'Failed to load')}</div>`;
    }
  }

  treeEl.onclick = (e) => {
    const toggle = e.target.closest('[data-toggle]');
    if (toggle) {
      e.preventDefault();
      e.stopPropagation();
      const path = toggle.dataset.toggle;
      const row = toggle.closest('.project-files-tree-row');
      void expandDir(path, row);
      return;
    }
    const select = e.target.closest('[data-select]');
    if (!select) return;
    e.preventDefault();
    const path = select.dataset.select;
    const type = select.dataset.type;
    if (type === 'dir') {
      const row = select.closest('.project-files-tree-row');
      void expandDir(path, row);
      return;
    }
    void showFile(path);
  };

  async function doPromote() {
    if (!selectedPath) return;
    const btn = overlay.querySelector('#project-files-promote-do');
    btn.disabled = true;
    try {
      const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(pid)}/promote`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          path: selectedPath,
          library_type: promoteType.value || 'document',
          title: (promoteTitle.value || '').trim() || undefined,
          link: !!promoteLink.checked,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || 'Promote failed');
      const art = data.artifact || {};
      const kind = art.library_type || promoteType.value;
      const label = art.title || 'Library item';
      const docId = art.id;
      cleanup();
      uiModule.showToast?.(`Added “${label}” to Library`, {
        duration: 5000,
        leadingIcon: 'check',
        action: kind === 'note' ? 'Open Notes' : 'Open in Library',
        onAction: async () => {
          if (kind === 'note') {
            document.getElementById('tool-notes-btn')?.click();
            return;
          }
          if (docId) {
            try {
              const mod = await import('../document.js');
              const load = mod.loadDocument || mod.default?.loadDocument;
              if (load) {
                await load(docId);
                return;
              }
            } catch { /* fall through */ }
          }
          document.getElementById('tool-documents-btn')?.click()
            || document.getElementById('tool-library-btn')?.click();
        },
      });
    } catch (e) {
      uiModule.showToast?.(e.message || 'Promote failed', 4000);
    } finally {
      btn.disabled = false;
    }
  }

  overlay.querySelector('#project-files-sheet-close').onclick = () => cleanup();
  overlay.querySelector('#project-files-promote-cancel').onclick = () => hidePromote();
  overlay.querySelector('#project-files-promote-do').onclick = () => { void doPromote(); };
  promoteOpenBtn.onclick = () => showPromote();
  overlay.onclick = (e) => { if (e.target === overlay) cleanup(); };

  document.addEventListener('keydown', onKey);
  overlay.classList.remove('hidden');
  overlay.classList.remove('project-files-sheet-enter');
  void overlay.offsetWidth;
  overlay.classList.add('project-files-sheet-enter');
  await loadRoot();
}

/** Alias matching plan naming. */
export const openProjectFilesSheet = openProjectFilePicker;

export default { openProjectFilePicker, openProjectFilesSheet };
