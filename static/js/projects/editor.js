/**
 * Project file editor — depth boundary (Phase B).
 * Reuses document editor CSS/highlight patterns; saves via project file PUT API.
 */
import uiModule, { styledChoice } from '../ui.js';
import { langIcon } from '../langIcons.js';
import markdownModule from '../markdown.js';
import codeRunnerModule from '../codeRunner.js';
import runPanelModule from './runPanel.js';
import workspaceShell from './workspaceShell.js';
import { formatButtonHtml, wireMarkdownFormat } from '../ui/editorChrome.js';

const API_BASE = window.API_BASE || window.location.origin;
const esc = uiModule.esc;
const AUTO_SAVE_MS = 2000;
const DISK_POLL_MS = 15000;
const MAX_FILE_BYTES = 2_000_000;
const _RUN_PLAY_SVG =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" stroke="none" aria-hidden="true">' +
  '<polygon points="5 3 19 12 5 21 5 3"/></svg>';
const _SAVE_SVG =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>' +
  '<polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>';
const _RELOAD_SVG =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>';
const _PREVIEW_SVG =
  '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
  '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>';

const EXT_TO_LANG = {
  py: 'python',
  js: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  ts: 'typescript',
  html: 'html',
  htm: 'html',
  css: 'css',
  md: 'markdown',
  json: 'json',
  yaml: 'yaml',
  yml: 'yaml',
  sh: 'bash',
  bash: 'bash',
  sql: 'sql',
  rs: 'rust',
  go: 'go',
  java: 'java',
  c: 'c',
  cpp: 'cpp',
  cc: 'cpp',
  h: 'c',
  hpp: 'cpp',
  txt: 'plaintext',
  toml: 'toml',
  xml: 'xml',
  svg: 'xml',
  csv: 'csv',
};

let _pane = null;
let _projectId = null;
let _path = null;
let _language = 'plaintext';
let _diskModifiedAt = null;
let _lastSavedContent = '';
let _autoSaveTimer = null;
let _hlDebounce = null;
let _diskPollTimer = null;
let _mounted = false;
let _onRun = null;
let _onDirtyChange = null;
let _pendingDiskPayload = null;
let _lineNumberResizeRaf = null;
let _lineNumberResizeObserver = null;
let _lineNumberObservedTextarea = null;
let _previewMode = null;

function _els() {
  return {
    path: _pane?.querySelector('#project-editor-path'),
    lang: _pane?.querySelector('#project-editor-lang'),
    status: _pane?.querySelector('#project-editor-save-status'),
    saveBtn: _pane?.querySelector('#project-editor-save-btn'),
    runBtn: _pane?.querySelector('#project-editor-run-btn'),
    reloadBtn: _pane?.querySelector('#project-editor-reload-btn'),
    wrap: _pane?.querySelector('#project-editor-wrap'),
    gutter: _pane?.querySelector('#project-editor-line-numbers'),
    pre: _pane?.querySelector('#project-editor-highlight'),
    code: _pane?.querySelector('#project-editor-code'),
    textarea: _pane?.querySelector('#project-editor-textarea'),
    placeholder: _pane?.querySelector('#project-editor-empty'),
    shell: _pane?.querySelector('#project-editor-shell'),
    diskBanner: _pane?.querySelector('#project-editor-disk-banner'),
    diskBannerMsg: _pane?.querySelector('#project-editor-disk-banner-msg'),
    previewBtn: _pane?.querySelector('#project-editor-preview-btn'),
    formatWrap: _pane?.querySelector('#project-editor-format-wrap'),
    mdPreview: _pane?.querySelector('#project-editor-md-preview'),
    htmlPreview: _pane?.querySelector('#project-editor-html-preview'),
    metaStatus: _pane?.querySelector('#project-editor-meta-status'),
  };
}

function _canPreview() {
  return _language === 'markdown' || _language === 'html';
}

function _updatePreviewButton() {
  const { previewBtn } = _els();
  if (!previewBtn) return;
  const show = _canPreview() && !!_path;
  previewBtn.classList.toggle('hidden', !show);
  previewBtn.classList.toggle('active', !!_previewMode);
  previewBtn.setAttribute('aria-pressed', _previewMode ? 'true' : 'false');
  previewBtn.title = _previewMode ? 'Return to editor' : 'Preview markdown or HTML';
}

function _exitPreview() {
  _previewMode = null;
  const { wrap, mdPreview, htmlPreview } = _els();
  if (mdPreview) {
    mdPreview.style.display = 'none';
    mdPreview.innerHTML = '';
  }
  if (htmlPreview) {
    htmlPreview.style.display = 'none';
    htmlPreview.srcdoc = '';
  }
  if (wrap) wrap.style.display = '';
  _updatePreviewButton();
}

function _syncPreviewContent() {
  if (!_previewMode) return;
  const { textarea, mdPreview, htmlPreview } = _els();
  const text = textarea?.value || '';
  if (_previewMode === 'markdown' && mdPreview) {
    mdPreview.innerHTML = markdownModule.mdToHtml ? markdownModule.mdToHtml(text) : esc(text);
    if (window.hljs) {
      mdPreview.querySelectorAll('pre code').forEach((b) => window.hljs.highlightElement(b));
    }
    _bindMarkdownPreviewRuns(mdPreview);
  } else if (_previewMode === 'html' && htmlPreview) {
    htmlPreview.srcdoc = text;
  }
}

function _bindMarkdownPreviewRuns(root) {
  if (!root || root.dataset.runBound === '1') return;
  root.dataset.runBound = '1';
  root.addEventListener('click', (e) => {
    const btn = e.target.closest('.run-code');
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const lang = (btn.getAttribute('data-lang') || '').toLowerCase();
    const code = btn.getAttribute('data-code') || '';
    if (!code) return;
    if (lang === 'python' || lang === 'py') {
      workspaceShell.focusRunTab();
      void runPanelModule.runMarkdownSnippet(code, lang);
      return;
    }
    if (codeRunnerModule?.run) codeRunnerModule.run(btn);
  });
}

function _setPreviewActive(active) {
  const { wrap, mdPreview, htmlPreview, textarea } = _els();
  if (!wrap || !textarea || !_canPreview()) return;
  if (!active) {
    _exitPreview();
    return;
  }
  _previewMode = _language === 'html' ? 'html' : 'markdown';
  if (_previewMode === 'markdown' && mdPreview) {
    _syncPreviewContent();
    mdPreview.style.display = '';
    if (htmlPreview) htmlPreview.style.display = 'none';
  } else if (_previewMode === 'html' && htmlPreview) {
    _syncPreviewContent();
    htmlPreview.style.display = '';
    if (mdPreview) mdPreview.style.display = 'none';
  }
  wrap.style.display = 'none';
  _updatePreviewButton();
}

export function togglePreview() {
  _setPreviewActive(!_previewMode);
}

function _langFromPath(path) {
  const base = (path || '').split('/').pop() || '';
  const dot = base.lastIndexOf('.');
  if (dot < 0) return 'plaintext';
  return EXT_TO_LANG[base.slice(dot + 1).toLowerCase()] || 'plaintext';
}

function _hlLang(lang) {
  if (lang === 'svg') return 'xml';
  if (lang === 'plaintext') return '';
  return lang;
}

function _lineNumberContentEl(gutter) {
  let inner = gutter.querySelector('.doc-line-number-content');
  if (!inner) {
    inner = document.createElement('div');
    inner.className = 'doc-line-number-content';
    gutter.textContent = '';
    gutter.appendChild(inner);
  }
  return inner;
}

function _lineNumberStyleSignature(style) {
  return [
    style.fontFamily,
    style.fontSize,
    style.fontWeight,
    style.fontStyle,
    style.lineHeight,
    style.letterSpacing,
    style.tabSize,
  ].join('|');
}

function _textareaTextWidth(textarea, style) {
  const paddingLeft = parseFloat(style.paddingLeft) || 0;
  const paddingRight = parseFloat(style.paddingRight) || 0;
  return Math.max(0, textarea.clientWidth - paddingLeft - paddingRight);
}

function _lineHeightPx(style) {
  const parsed = parseFloat(style.lineHeight);
  if (Number.isFinite(parsed) && parsed > 0) return parsed;
  const fontSize = parseFloat(style.fontSize) || 11;
  return fontSize * 1.45;
}

function _lineNumberMeasureEl(textarea) {
  const wrap = _pane?.querySelector('#project-editor-wrap') || textarea.parentElement || document.body;
  let probe = wrap.querySelector('.doc-line-number-measure');
  if (!probe) {
    probe = document.createElement('textarea');
    probe.className = 'doc-line-number-measure';
    probe.setAttribute('aria-hidden', 'true');
    probe.tabIndex = -1;
    probe.readOnly = true;
    probe.wrap = 'soft';
    wrap.appendChild(probe);
  }
  return probe;
}

function _syncLineNumberMeasureStyle(probe, style, textWidth) {
  probe.style.width = `${textWidth}px`;
  probe.style.fontFamily = style.fontFamily;
  probe.style.fontSize = style.fontSize;
  probe.style.fontWeight = style.fontWeight;
  probe.style.fontStyle = style.fontStyle;
  probe.style.lineHeight = style.lineHeight;
  probe.style.letterSpacing = style.letterSpacing;
  probe.style.tabSize = style.tabSize;
  probe.style.whiteSpace = style.whiteSpace;
  probe.style.wordWrap = style.wordWrap;
  probe.style.overflowWrap = style.overflowWrap;
}

function _measureLineNumberHeights(textarea, lines, textWidth, style) {
  const probe = _lineNumberMeasureEl(textarea);
  _syncLineNumberMeasureStyle(probe, style, textWidth);
  const lineHeight = _lineHeightPx(style);
  return lines.map((line) => {
    probe.value = line || ' ';
    const visualRows = Math.max(1, Math.round(probe.scrollHeight / lineHeight));
    return visualRows * lineHeight;
  });
}

function _renderLineNumberRows(inner, heights) {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < heights.length; i++) {
    const row = document.createElement('div');
    row.className = 'doc-line-number-row';
    row.style.height = `${heights[i]}px`;
    const label = document.createElement('span');
    label.className = 'doc-line-number-label';
    label.textContent = String(i + 1);
    row.appendChild(label);
    frag.appendChild(row);
  }
  inner.replaceChildren(frag);
}

function _scheduleLineNumberRerender() {
  if (_lineNumberResizeRaf) return;
  const run = () => {
    _lineNumberResizeRaf = null;
    const { textarea } = _els();
    if (textarea) updateLineNumbers(textarea.value, true);
  };
  if (typeof requestAnimationFrame === 'function') {
    _lineNumberResizeRaf = requestAnimationFrame(run);
  } else {
    run();
  }
}

function _ensureLineNumberResizeObserver(textarea) {
  if (typeof ResizeObserver === 'undefined') return;
  if (!_lineNumberResizeObserver) {
    _lineNumberResizeObserver = new ResizeObserver(_scheduleLineNumberRerender);
  }
  if (_lineNumberObservedTextarea === textarea) return;
  if (_lineNumberObservedTextarea) {
    _lineNumberResizeObserver.unobserve(_lineNumberObservedTextarea);
  }
  _lineNumberObservedTextarea = textarea;
  _lineNumberResizeObserver.observe(textarea);
}

function syncGutterScroll() {
  const { textarea, gutter } = _els();
  if (!textarea || !gutter) return;
  _lineNumberContentEl(gutter).style.transform = `translateY(${-textarea.scrollTop}px)`;
}

function updateLineNumbers(text, force = false) {
  const { textarea, gutter } = _els();
  if (!textarea || !gutter) return;
  const value = text || '';
  const lines = value.split('\n');
  const inner = _lineNumberContentEl(gutter);
  const style = getComputedStyle(textarea);
  const textWidth = _textareaTextWidth(textarea, style);
  const styleSig = _lineNumberStyleSignature(style);

  _ensureLineNumberResizeObserver(textarea);
  if (
    !force &&
    inner._lineNumberText === value &&
    inner._lineNumberWidth === textWidth &&
    inner._lineNumberStyleSig === styleSig
  ) {
    syncGutterScroll();
    return;
  }

  const heights = _measureLineNumberHeights(textarea, lines, textWidth, style);
  _renderLineNumberRows(inner, heights);
  inner._lineNumberText = value;
  inner._lineNumberWidth = textWidth;
  inner._lineNumberStyleSig = styleSig;
  syncGutterScroll();
}

function syncHighlighting() {
  const { textarea, code, pre } = _els();
  if (!textarea || !code) return;
  const text = textarea.value;
  code.textContent = `${text}\n`;
  const hl = _hlLang(_language);
  code.className = hl ? `language-${hl}` : '';
  if (window.hljs && hl) {
    code.removeAttribute('data-highlighted');
    window.hljs.highlightElement(code);
  }
  if (pre) {
    code.style.minHeight = `${textarea.scrollHeight}px`;
    pre.scrollTop = textarea.scrollTop;
    pre.scrollLeft = textarea.scrollLeft;
  }
  updateLineNumbers(text);
}

function _scheduleHighlight() {
  clearTimeout(_hlDebounce);
  _hlDebounce = setTimeout(syncHighlighting, 80);
}

function isDirty() {
  const { textarea } = _els();
  if (!_path || !textarea) return false;
  return textarea.value !== _lastSavedContent;
}

function _setSaveStatus(text, kind = '') {
  const { status } = _els();
  if (!status) return;
  status.textContent = text || '';
  status.className = `project-editor-save-status${kind ? ` ${kind}` : ''}`;
}

function _updateMetaStatus() {
  const { textarea, metaStatus } = _els();
  if (!metaStatus) return;
  if (!_path || !textarea) {
    metaStatus.textContent = '';
    return;
  }
  const lines = (textarea.value.match(/\n/g) || []).length + 1;
  const chars = textarea.value.length;
  metaStatus.textContent = `${lines} line${lines === 1 ? '' : 's'} · ${chars} char${chars === 1 ? '' : 's'} · UTF-8`;
}

function _notifyDirty() {
  if (_onDirtyChange) _onDirtyChange(_path, isDirty());
}

function _updatePathDisplay() {
  const { path } = _els();
  if (!path) return;
  path.textContent = _path || '';
  path.title = _path || '';
}

function _updateRunButton() {
  const { runBtn } = _els();
  if (!runBtn) return;
  const isPy = !!(_path && _path.toLowerCase().endsWith('.py'));
  runBtn.disabled = !isPy;
  runBtn.title = isPy ? 'Run script in project folder (Ctrl+Enter)' : 'Only .py files can be run';
  runBtn.classList.toggle('project-editor-run-ready', isPy);
  runBtn.classList.toggle('active', isPy);
  runBtn.style.opacity = isPy ? '0.85' : '0.3';
}

function _updateLangBadge() {
  const { lang, formatWrap } = _els();
  if (formatWrap) {
    formatWrap.classList.toggle('hidden', _language !== 'markdown' || !_path);
  }
  if (!lang) return;
  const icon = langIcon(_language);
  const label = _language === 'plaintext' ? 'Text' : _language;
  lang.innerHTML =
    icon
      ? `<span class="project-editor-lang-icon">${icon}</span><span>${esc(label)}</span>`
      : `<span>${esc(label)}</span>`;
}

function _showEditor(show) {
  const { shell, placeholder } = _els();
  shell?.classList.toggle('hidden', !show);
  placeholder?.classList.toggle('hidden', show);
}

function _showDiskBanner(message, { deleted = false } = {}) {
  const { diskBanner, diskBannerMsg } = _els();
  if (!diskBanner || !diskBannerMsg) return;
  diskBannerMsg.textContent = message;
  diskBanner.classList.toggle('project-editor-disk-banner-deleted', deleted);
  diskBanner.querySelector('[data-disk-action="reload"]')?.classList.toggle('hidden', deleted);
  diskBanner.querySelector('[data-disk-action="overwrite"]')?.classList.toggle('hidden', deleted);
  diskBanner.classList.remove('hidden');
}

function _hideDiskBanner() {
  const { diskBanner } = _els();
  diskBanner?.classList.add('hidden');
  _pendingDiskPayload = null;
}

function _startDiskPoll() {
  _stopDiskPoll();
  if (!_path) return;
  _diskPollTimer = setInterval(() => {
    void reconcileWithDisk({ quiet: true });
  }, DISK_POLL_MS);
  if (typeof window !== 'undefined') {
    window.addEventListener('focus', _onWindowFocus);
  }
}

function _stopDiskPoll() {
  clearInterval(_diskPollTimer);
  _diskPollTimer = null;
  if (typeof window !== 'undefined') {
    window.removeEventListener('focus', _onWindowFocus);
  }
}

function _onWindowFocus() {
  if (_path) void reconcileWithDisk({ quiet: true });
}

function _validateOpenPayload(payload) {
  if (!payload?.path) return 'Invalid file path';
  if (payload.size != null && payload.size > MAX_FILE_BYTES) {
    return `File exceeds ${Math.round(MAX_FILE_BYTES / 1_000_000)}MB limit`;
  }
  const content = payload.content ?? '';
  if (content.includes('\0')) {
    return 'Binary files cannot be edited in the text editor';
  }
  return null;
}

async function _fetchFile(path) {
  const res = await fetch(
    `${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/file?path=${encodeURIComponent(path)}`,
    { credentials: 'same-origin' },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to read file');
  return data;
}

async function _writeFile(path, content) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/file`, {
    method: 'PUT',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, content, create_dirs: true }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to save file');
  return data;
}

async function _checkDiskConflict() {
  if (!_path || _diskModifiedAt == null) return null;
  let disk;
  try {
    disk = await _fetchFile(_path);
  } catch (err) {
    if ((err.message || '').toLowerCase().includes('not found')) {
      return { deleted: true };
    }
    throw err;
  }
  if (disk.modified_at === _diskModifiedAt) return null;
  if (disk.content === _lastSavedContent) {
    _diskModifiedAt = disk.modified_at;
    return null;
  }
  return disk;
}

async function _promptUnsavedChanges(currentPath, nextLabel) {
  const choice = await styledChoice(
    nextLabel
      ? `Save changes to “${currentPath}” before opening “${nextLabel}”?`
      : `Save changes to “${currentPath}” before closing?`,
    {
      title: 'Unsaved changes',
      choices: [
        { id: 'save', label: 'Save', primary: true },
        { id: 'discard', label: "Don't save", secondary: true },
        { id: 'cancel', label: 'Cancel', secondary: true },
      ],
    },
  );
  if (choice === 'cancel' || choice == null) return false;
  if (choice === 'save') {
    const ok = await save({ silent: true, force: true });
    return ok;
  }
  return true;
}

async function _promptDiskConflict(disk, { interactive = true } = {}) {
  if (disk.deleted) {
    _showDiskBanner('This file was deleted on disk.', { deleted: true });
    return 'deleted';
  }

  _pendingDiskPayload = disk;
  const msg = `“${_path}” changed on disk since you opened it.`;
  if (!interactive) {
    _showDiskBanner(msg);
    return 'banner';
  }

  const choice = await styledChoice(msg, {
    title: 'File changed on disk',
    choices: [
      { id: 'reload', label: 'Reload from disk', primary: true },
      { id: 'overwrite', label: 'Keep editing (overwrite on save)', secondary: true },
      { id: 'cancel', label: 'Cancel', secondary: true },
    ],
  });
  if (choice === 'cancel' || choice == null) return 'cancel';
  if (choice === 'reload') {
    await _applyPayload(disk, { fromDisk: true });
    _hideDiskBanner();
    return 'reload';
  }
  if (choice === 'overwrite') {
    _diskModifiedAt = disk.modified_at;
    _hideDiskBanner();
    return 'overwrite';
  }
  return 'cancel';
}

async function _applyPayload(payload, { fromDisk = false } = {}) {
  _path = payload.path;
  _language = _langFromPath(_path);
  _diskModifiedAt = payload.modified_at ?? null;
  _lastSavedContent = payload.content ?? '';
  clearTimeout(_autoSaveTimer);

  const { textarea } = _els();
  _updatePathDisplay();
  _updateLangBadge();
  _updateRunButton();
  _exitPreview();
  _updatePreviewButton();
  _showEditor(true);
  if (textarea) {
    textarea.value = _lastSavedContent;
    textarea.placeholder = _path;
  }
  syncHighlighting();
  _setSaveStatus(fromDisk ? 'Reloaded from disk' : '', fromDisk ? 'saved' : '');
  _updateMetaStatus();
  _notifyDirty();
  _startDiskPoll();
}

export async function save({ silent = false, force = false } = {}) {
  const { textarea } = _els();
  if (!_projectId || !_path || !textarea) return false;

  if (!force) {
    try {
      const conflict = await _checkDiskConflict();
      if (conflict?.deleted) {
        if (silent) {
          await _promptDiskConflict(conflict, { interactive: false });
          return false;
        }
        const action = await _promptDiskConflict(conflict, { interactive: true });
        return action === 'reload' || action === 'overwrite';
      }
      if (conflict) {
        if (silent) {
          await _promptDiskConflict(conflict, { interactive: false });
          return false;
        }
        const action = await _promptDiskConflict(conflict, { interactive: true });
        if (action === 'cancel') return false;
        if (action === 'reload') return true;
        if (action === 'overwrite') return save({ silent, force: true });
      }
    } catch (err) {
      uiModule.showToast?.(err.message || 'Could not verify file on disk', 4000);
      return false;
    }
  }

  _setSaveStatus('Saving…', 'saving');
  try {
    const result = await _writeFile(_path, textarea.value);
    _lastSavedContent = textarea.value;
    _diskModifiedAt = result.modified_at ?? _diskModifiedAt;
    _hideDiskBanner();
    _setSaveStatus('Saved', 'saved');
    _updateMetaStatus();
    _notifyDirty();
    if (!silent) uiModule.showToast?.('File saved');
    return true;
  } catch (err) {
    _setSaveStatus('Save failed', 'error');
    if (!silent) uiModule.showToast?.(err.message || 'Save failed', 4000);
    return false;
  }
}

function _scheduleAutoSave() {
  if (!_path) return;
  clearTimeout(_autoSaveTimer);
  _setSaveStatus('Unsaved changes', 'dirty');
  _notifyDirty();
  _autoSaveTimer = setTimeout(() => {
    void save({ silent: true });
  }, AUTO_SAVE_MS);
}

function _bindEditorEvents() {
  const { textarea, saveBtn, reloadBtn, diskBanner } = _els();
  if (!textarea || textarea.dataset.bound) return;
  textarea.dataset.bound = '1';

  textarea.addEventListener('input', () => {
    _scheduleHighlight();
    _scheduleAutoSave();
    _syncPreviewContent();
    _updateMetaStatus();
  });
  textarea.addEventListener('scroll', () => {
    const { pre } = _els();
    if (pre) {
      pre.scrollTop = textarea.scrollTop;
      pre.scrollLeft = textarea.scrollLeft;
    }
    syncGutterScroll();
  });
  textarea.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      void save({ silent: false });
    }
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      const { runBtn } = _els();
      if (runBtn && !runBtn.disabled && _onRun) {
        e.preventDefault();
        void _onRun();
      }
    }
  });

  saveBtn?.addEventListener('click', () => void save({ silent: false }));
  _els().runBtn?.addEventListener('click', () => {
    if (_onRun) void _onRun();
  });
  reloadBtn?.addEventListener('click', () => void reloadFromDisk());
  _els().previewBtn?.addEventListener('click', () => togglePreview());

  diskBanner?.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-disk-action]');
    if (!btn) return;
    const action = btn.dataset.diskAction;
    if (action === 'reload' && _pendingDiskPayload) {
      void _applyPayload(_pendingDiskPayload, { fromDisk: true }).then(() => _hideDiskBanner());
    } else if (action === 'overwrite' && _pendingDiskPayload) {
      _diskModifiedAt = _pendingDiskPayload.modified_at;
      _hideDiskBanner();
      void save({ silent: true, force: true });
    } else if (action === 'close') {
      closeFile();
    }
  });

  if (typeof window !== 'undefined') {
    window.addEventListener('resize', _scheduleLineNumberRerender);
  }
}

function _renderChrome() {
  if (!_pane) return;
  _pane.innerHTML =
    '<div id="project-editor-empty" class="project-pane-placeholder">Select a file from the Files tab</div>' +
    '<div id="project-editor-shell" class="project-editor-shell hidden">' +
      '<div id="project-editor-disk-banner" class="project-editor-disk-banner hidden" role="status">' +
        '<span id="project-editor-disk-banner-msg"></span>' +
        '<span class="project-editor-disk-banner-actions">' +
          '<button type="button" class="admin-btn-sm" data-disk-action="reload">Reload</button>' +
          '<button type="button" class="admin-btn-sm" data-disk-action="overwrite">Overwrite</button>' +
          '<button type="button" class="admin-btn-sm" data-disk-action="close">Close</button>' +
        '</span>' +
      '</div>' +
      '<div class="project-editor-head project-editor-head--depth">' +
        '<span class="project-editor-boundary">Depth</span>' +
        '<span id="project-editor-path" class="project-editor-path" title=""></span>' +
        '<span id="project-editor-lang" class="project-editor-lang"></span>' +
        '<span class="project-editor-head-actions">' +
          '<span id="project-editor-format-wrap" class="project-editor-format-wrap hidden">' +
            formatButtonHtml() +
          '</span>' +
          '<button type="button" id="project-editor-preview-btn" class="doc-action-icon-btn hidden" title="Preview markdown or HTML" aria-pressed="false">' +
            _PREVIEW_SVG +
          '</button>' +
          '<button type="button" id="project-editor-reload-btn" class="doc-action-icon-btn" title="Reload from disk">' +
            _RELOAD_SVG +
          '</button>' +
          '<button type="button" id="project-editor-save-btn" class="doc-action-icon-btn" title="Save (Ctrl+S)">' +
            _SAVE_SVG +
          '</button>' +
          '<button type="button" id="project-editor-run-btn" class="doc-action-icon-btn project-editor-run-btn" disabled title="Run script">' +
            _RUN_PLAY_SVG +
          '</button>' +
        '</span>' +
      '</div>' +
      '<div id="project-editor-md-preview" class="doc-md-preview project-editor-md-preview" style="display:none"></div>' +
      '<iframe id="project-editor-html-preview" class="doc-html-preview project-editor-html-preview" sandbox="allow-scripts allow-modals" style="display:none"></iframe>' +
      '<div id="project-editor-wrap" class="doc-editor-wrap project-editor-wrap">' +
        '<div id="project-editor-line-numbers" class="doc-line-numbers"><div class="doc-line-number-content"><span class="doc-line-number-label">1</span></div></div>' +
        '<pre id="project-editor-highlight" class="doc-editor-highlight"><code id="project-editor-code"></code></pre>' +
        '<textarea id="project-editor-textarea" class="doc-editor-textarea" spellcheck="false" autocapitalize="off" autocomplete="off"></textarea>' +
      '</div>' +
      '<div class="project-editor-footer">' +
        '<span id="project-editor-meta-status" class="project-editor-meta-status"></span>' +
        '<span class="project-editor-hints">Ctrl+S save · Ctrl+Enter run · Ctrl+P open</span>' +
        '<span id="project-editor-save-status" class="project-editor-save-status"></span>' +
      '</div>' +
    '</div>';
  _bindEditorEvents();
  wireMarkdownFormat(_pane?.querySelector('#project-editor-format-wrap'), () => _els().textarea);
}

export async function openFile(payload) {
  if (!_mounted || !payload?.path) {
    closeFile();
    return;
  }

  const invalid = _validateOpenPayload(payload);
  if (invalid) {
    uiModule.showToast?.(invalid, 4000);
    return;
  }

  if (_path && _path !== payload.path && isDirty()) {
    const ok = await _promptUnsavedChanges(_path, payload.path);
    if (!ok) return;
  }

  await _applyPayload(payload);
  requestAnimationFrame(() => _els().textarea?.focus());
}

export function closeFile() {
  clearTimeout(_autoSaveTimer);
  clearTimeout(_hlDebounce);
  _stopDiskPoll();
  _hideDiskBanner();
  _exitPreview();
  _path = null;
  _diskModifiedAt = null;
  _lastSavedContent = '';
  _setSaveStatus('', '');
  _updateMetaStatus();
  _notifyDirty();
  _updateRunButton();
  _showEditor(false);
}

export async function confirmCloseIfDirty() {
  if (!isDirty()) return true;
  return _promptUnsavedChanges(_path);
}

export function handlePathChange(from, to) {
  if (!_path || _path !== from || !to) return;
  _path = to;
  _language = _langFromPath(_path);
  _updatePathDisplay();
  _updateLangBadge();
  _updateRunButton();
  _updatePreviewButton();
}

export async function reloadFromDisk() {
  if (!_path) return;
  if (isDirty()) {
    const choice = await styledChoice(`Reload “${_path}” from disk? Unsaved edits will be lost.`, {
      title: 'Reload from disk',
      choices: [
        { id: 'reload', label: 'Reload', primary: true },
        { id: 'cancel', label: 'Cancel', secondary: true },
      ],
    });
    if (choice !== 'reload') return;
  }
  try {
    const disk = await _fetchFile(_path);
    const invalid = _validateOpenPayload(disk);
    if (invalid) {
      uiModule.showToast?.(invalid, 4000);
      return;
    }
    await _applyPayload(disk, { fromDisk: true });
    _hideDiskBanner();
    uiModule.showToast?.('Reloaded from disk');
  } catch (err) {
    if ((err.message || '').toLowerCase().includes('not found')) {
      _showDiskBanner('This file was deleted on disk.', { deleted: true });
      return;
    }
    uiModule.showToast?.(err.message || 'Reload failed', 4000);
  }
}

export async function reconcileWithDisk({ quiet = false } = {}) {
  if (!_path || !_projectId) return;
  try {
    const conflict = await _checkDiskConflict();
    if (!conflict) {
      if (!quiet) _hideDiskBanner();
      return;
    }
    if (conflict.deleted) {
      _showDiskBanner('This file was deleted on disk.', { deleted: true });
      return;
    }
    if (isDirty()) {
      _pendingDiskPayload = conflict;
      _showDiskBanner(`“${_path}” changed on disk.`);
      return;
    }
    await _applyPayload(conflict, { fromDisk: true });
    if (!quiet) uiModule.showToast?.('File updated from disk');
  } catch {
    /* ignore background poll errors */
  }
}

export function mount(pane, projectId, { onRun, onDirtyChange } = {}) {
  unmount();
  _pane = pane;
  _projectId = projectId;
  _onRun = onRun || null;
  _onDirtyChange = onDirtyChange || null;
  _mounted = true;
  _renderChrome();
  closeFile();
}

export function unmount() {
  clearTimeout(_autoSaveTimer);
  clearTimeout(_hlDebounce);
  _stopDiskPoll();
  closeFile();
  if (_lineNumberObservedTextarea && _lineNumberResizeObserver) {
    _lineNumberResizeObserver.unobserve(_lineNumberObservedTextarea);
  }
  _lineNumberObservedTextarea = null;
  if (_pane) _pane.innerHTML = '';
  _pane = null;
  _projectId = null;
  _onRun = null;
  _onDirtyChange = null;
  _mounted = false;
}

export function getOpenPath() {
  return _path;
}

export default {
  mount,
  unmount,
  openFile,
  closeFile,
  save,
  isDirty,
  getOpenPath,
  confirmCloseIfDirty,
  handlePathChange,
  reloadFromDisk,
  reconcileWithDisk,
  togglePreview,
};
