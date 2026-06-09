/**
 * Project run panel — depth boundary (Phase C).
 * Runs `.py` files via POST /api/projects/{id}/run; shows stdout/stderr in-panel.
 */
import uiModule, { styledChoice } from '../ui.js';

const API_BASE = window.API_BASE || window.location.origin;
const FIRST_RUN_KEY = 'odysseus_project_run_intro_seen';

let _container = null;
let _projectId = null;
let _getOpenPath = () => null;
let _isDirty = () => false;
let _save = async () => true;
let _onRunComplete = null;
let _onRunStateChange = null;
let _lastPath = null;
let _lastArgs = [];
let _running = false;
let _mounted = false;

function _els() {
  return {
    shell: _container?.querySelector('#project-run-shell'),
    empty: _container?.querySelector('#project-run-empty'),
    status: _container?.querySelector('#project-run-status'),
    meta: _container?.querySelector('#project-run-meta'),
    stdout: _container?.querySelector('#project-run-stdout'),
    stderr: _container?.querySelector('#project-run-stderr'),
    stderrWrap: _container?.querySelector('#project-run-stderr-wrap'),
    intro: _container?.querySelector('#project-run-intro'),
    rerunBtn: _container?.querySelector('#project-run-rerun-btn'),
    clearBtn: _container?.querySelector('#project-run-clear-btn'),
    copyBtn: _container?.querySelector('#project-run-copy-btn'),
  };
}

function _firstRunKey() {
  return `${FIRST_RUN_KEY}:${_projectId || ''}`;
}

function _showIntroIfNeeded() {
  const { intro } = _els();
  if (!intro || !_projectId) return;
  try {
    if (sessionStorage.getItem(_firstRunKey()) === '1') {
      intro.classList.add('hidden');
      return;
    }
    intro.classList.remove('hidden');
  } catch {
    intro.classList.add('hidden');
  }
}

function _markIntroSeen() {
  const { intro } = _els();
  intro?.classList.add('hidden');
  try {
    sessionStorage.setItem(_firstRunKey(), '1');
  } catch {
    /* ignore */
  }
}

function _setRunning(running) {
  _running = running;
  const { rerunBtn, clearBtn, status } = _els();
  if (rerunBtn) rerunBtn.disabled = running;
  if (clearBtn) clearBtn.disabled = running;
  if (status && running) {
    status.textContent = 'Running…';
    status.className = 'project-run-status running';
  }
  if (running) _onRunStateChange?.('running');
}

function _showOutput(show) {
  const { shell, empty } = _els();
  shell?.classList.toggle('hidden', !show);
  empty?.classList.toggle('hidden', show);
}

function _clearOutput() {
  const { stdout, stderr, stderrWrap, meta, status } = _els();
  if (stdout) stdout.textContent = '';
  if (stderr) stderr.textContent = '';
  stderrWrap?.classList.add('hidden');
  if (meta) meta.textContent = '';
  if (status) {
    status.textContent = '';
    status.className = 'project-run-status';
  }
  _onRunStateChange?.(null);
  const path = _getOpenPath?.() || _lastPath;
  if (path && /\.py$/i.test(path)) {
    syncPath(path);
  } else if (_lastPath) {
    _showOutput(true);
  } else {
    _showOutput(false);
  }
}

function _formatMeta(result) {
  const parts = [];
  if (result.timed_out) {
    parts.push('timed out');
  } else if (result.exit_code != null) {
    parts.push(`exit ${result.exit_code}`);
  }
  if (result.duration_ms != null) {
    parts.push(`${result.duration_ms} ms`);
  }
  if (result.network_allowed === false) {
    parts.push('network off');
  } else if (result.network_allowed === true) {
    parts.push('network on');
  }
  return parts.join(' · ');
}

function _renderResult(result) {
  const { status, meta, stdout, stderr, stderrWrap } = _els();
  _showOutput(true);

  const ok = result.ok && !result.timed_out;
  if (status) {
    status.textContent = ok ? 'Finished' : (result.timed_out ? 'Timed out' : 'Failed');
    status.className = `project-run-status ${ok ? 'ok' : 'error'}`;
  }
  if (meta) meta.textContent = _formatMeta(result);

  if (stdout) stdout.textContent = result.stdout || (result.stderr ? '' : '(no output)');
  const errText = (result.stderr || '').trim();
  if (stderr && stderrWrap) {
    if (errText) {
      stderr.textContent = errText;
      stderrWrap.classList.remove('hidden');
    } else {
      stderr.textContent = '';
      stderrWrap.classList.add('hidden');
    }
  }
  if (!ok) _onRunStateChange?.('error');
  else _onRunStateChange?.(null);
}

async function _confirmSaveBeforeRun(path) {
  if (!_isDirty()) return true;
  const choice = await styledChoice(
    `Save changes to “${path}” before running? The script runs from disk, not your unsaved buffer.`,
    {
      title: 'Unsaved changes',
      choices: [
        { id: 'save', label: 'Save & run', primary: true },
        { id: 'discard', label: 'Run without saving', secondary: true },
        { id: 'cancel', label: 'Cancel', secondary: true },
      ],
    },
  );
  if (choice === 'cancel' || choice == null) return false;
  if (choice === 'save') {
    return _save({ silent: true, force: true });
  }
  return true;
}

async function _postRun(path, args = []) {
  const res = await fetch(
    `${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/run`,
    {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, args: args.length ? args : undefined }),
    },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Run failed');
  return data;
}

export async function runPath(path, { args = [], skipSavePrompt = false } = {}) {
  if (!_mounted || !_projectId || !path) return null;
  if (!path.toLowerCase().endsWith('.py')) {
    uiModule.showToast?.('Only .py scripts can be run in the project workspace', 4000);
    return null;
  }
  if (_running) return null;

  if (!skipSavePrompt) {
    const ok = await _confirmSaveBeforeRun(path);
    if (!ok) return null;
  }

  _markIntroSeen();
  _lastPath = path;
  _lastArgs = args;
  _setRunning(true);
  _showOutput(true);
  const { stdout, meta, status } = _els();
  if (stdout) stdout.textContent = '';
  if (meta) meta.textContent = '';
  if (status) {
    status.textContent = 'Running…';
    status.className = 'project-run-status running';
  }

  try {
    const result = await _postRun(path, args);
    _renderResult(result);
    if (result.ok) {
      uiModule.showToast?.('Script finished');
      _onRunComplete?.();
    } else if (result.timed_out) {
      uiModule.showToast?.('Script timed out', 4000);
    } else {
      uiModule.showToast?.(`Script exited with code ${result.exit_code ?? '?'}`, 4000);
    }
    return result;
  } catch (err) {
    _showOutput(true);
    if (status) {
      status.textContent = 'Error';
      status.className = 'project-run-status error';
    }
    if (stdout) stdout.textContent = err.message || 'Run failed';
    _onRunStateChange?.('error');
    uiModule.showToast?.(err.message || 'Run failed', 4000);
    return null;
  } finally {
    _setRunning(false);
  }
}

const SNIPPET_PATH = '.nobody_scratch/__run_snippet__.py';

async function _writeSnippetFile(content) {
  const res = await fetch(`${API_BASE}/api/projects/${encodeURIComponent(_projectId)}/file`, {
    method: 'PUT',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path: SNIPPET_PATH, content, create_dirs: true }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Failed to write snippet');
  return data;
}

export async function runMarkdownSnippet(code, lang) {
  if (!_mounted || !_projectId || !code) return null;
  const pick = (lang || '').toLowerCase();
  if (pick !== 'python' && pick !== 'py') {
    uiModule.showToast?.('Only Python snippets run in the project runner', 3000);
    return null;
  }
  if (_running) return null;
  try {
    await _writeSnippetFile(code);
  } catch (err) {
    uiModule.showToast?.(err.message || 'Could not save snippet', 4000);
    return null;
  }
  return runPath(SNIPPET_PATH, { skipSavePrompt: true });
}

export async function runCurrent() {
  const path = _getOpenPath();
  if (!path) {
    uiModule.showToast?.('Select a Python file in the tree first', 3000);
    return null;
  }
  return runPath(path);
}

function _bindEvents() {
  _container?.querySelector('#project-run-rerun-btn')?.addEventListener('click', () => {
    if (_lastPath) void runPath(_lastPath, { args: _lastArgs });
  });
  _container?.querySelector('#project-run-clear-btn')?.addEventListener('click', () => {
    _clearOutput();
    _lastPath = null;
    _lastArgs = [];
  });
  _container?.querySelector('#project-run-copy-btn')?.addEventListener('click', async () => {
    const { stdout, stderr } = _els();
    const text = [stdout?.textContent || '', stderr?.textContent ? `STDERR:\n${stderr.textContent}` : '']
      .filter(Boolean)
      .join('\n');
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      uiModule.showToast?.('Output copied');
    } catch {
      uiModule.showToast?.('Copy failed', 3000);
    }
  });
  _container?.querySelector('#project-run-intro-dismiss')?.addEventListener('click', () => {
    _markIntroSeen();
  });
}

function _renderChrome() {
  if (!_container) return;
  _container.innerHTML =
    '<div id="project-run-empty" class="project-pane-placeholder">Select a <code>.py</code> file and click Run</div>' +
    '<div id="project-run-shell" class="project-run-shell hidden">' +
      '<div id="project-run-intro" class="project-run-intro hidden">' +
        '<span>Runs use the saved file on disk (project cwd only — not admin shell).</span>' +
        '<button type="button" id="project-run-intro-dismiss" class="admin-btn-sm">Got it</button>' +
      '</div>' +
      '<div class="project-run-toolbar">' +
        '<span id="project-run-status" class="project-run-status"></span>' +
        '<span id="project-run-meta" class="project-run-meta"></span>' +
        '<span class="project-run-toolbar-actions">' +
          '<button type="button" id="project-run-copy-btn" class="project-run-tool-btn" title="Copy output">Copy</button>' +
          '<button type="button" id="project-run-rerun-btn" class="project-run-tool-btn" title="Re-run last script">Re-run</button>' +
          '<button type="button" id="project-run-clear-btn" class="project-run-tool-btn" title="Clear output">Clear</button>' +
        '</span>' +
      '</div>' +
      '<div class="project-run-output doc-run-output">' +
        '<pre id="project-run-stdout" class="doc-run-pre"></pre>' +
        '<div id="project-run-stderr-wrap" class="project-run-stderr-wrap hidden">' +
          '<div class="project-run-stderr-label">stderr</div>' +
          '<pre id="project-run-stderr" class="doc-run-error"></pre>' +
        '</div>' +
      '</div>' +
    '</div>';
  _bindEvents();
  _showIntroIfNeeded();
}

export function syncPath(path) {
  if (!_mounted) return;
  const { empty, shell, meta, status } = _els();
  const isPy = !!(path && /\.py$/i.test(path));
  if (isPy || _lastPath) {
    empty?.classList.add('hidden');
    shell?.classList.remove('hidden');
    if (isPy && !_lastPath && !_running) {
      const name = (path.split('/').pop() || path).trim();
      if (meta) meta.textContent = name;
      if (status && !status.textContent) {
        status.textContent = 'Ready';
        status.className = 'project-run-status';
      }
    }
  } else if (!path && !_lastPath) {
    empty?.classList.remove('hidden');
    shell?.classList.add('hidden');
    if (meta) meta.textContent = '';
    if (status) {
      status.textContent = '';
      status.className = 'project-run-status';
    }
  }
}

export function mount(container, projectId, { getOpenPath, isDirty, save, onRunComplete, onRunStateChange } = {}) {
  unmount();
  _container = container;
  _projectId = projectId;
  _getOpenPath = getOpenPath || (() => null);
  _isDirty = isDirty || (() => false);
  _save = save || (async () => true);
  _onRunComplete = onRunComplete || null;
  _onRunStateChange = onRunStateChange || null;
  _mounted = true;
  _lastPath = null;
  _lastArgs = [];
  _renderChrome();
}

export function unmount() {
  _container = null;
  _projectId = null;
  _getOpenPath = () => null;
  _isDirty = () => false;
  _save = async () => true;
  _onRunComplete = null;
  _onRunStateChange = null;
  _lastPath = null;
  _lastArgs = [];
  _running = false;
  _mounted = false;
}

export default {
  mount,
  unmount,
  runPath,
  runCurrent,
  runMarkdownSnippet,
  syncPath,
};
