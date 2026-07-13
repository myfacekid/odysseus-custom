/**
 * Unified Activity strip (U8c — workspace shell / modal reduction).
 *
 * One auto-hiding view of everything currently running across tools:
 *   - Research jobs        (research/jobs.js  → getJobs())
 *   - Cookbook tasks       (cookbookRunning.js → _loadTasks())
 *   - Scheduled Task runs  (GET /api/tasks/runs/recent)
 *
 * Before this, each subsystem lit its own indicator (Research + Cookbook the
 * rail/sidebar; Tasks had none) and nothing aggregated them. This strip reads
 * the existing modules' state — it adds no new source of truth. Clicking a row
 * opens the owning tool via its existing toolbar button.
 *
 * The strip lives as a small floating pill anchored bottom-right; it stays
 * hidden while nothing is running and never covers an open modal (low z-index).
 */
import { getJobs, formatElapsed, formatPhase } from './research/jobs.js';

const API_BASE = window.API_BASE || window.location.origin;

// Cookbook persists its tasks in localStorage; read that key directly rather
// than importing cookbookRunning.js. The activity strip loads early in app
// boot, and pulling in the full cookbook module graph here risks a circular
// top-level init ordering problem — a plain localStorage read has no such edge.
const COOKBOOK_TASKS_KEY = 'cookbook-tasks';
function _loadCookbookTasks() {
  try { return JSON.parse(localStorage.getItem(COOKBOOK_TASKS_KEY)) || []; }
  catch { return []; }
}

// In-memory + localStorage sources are cheap → poll on a short tick. Task runs
// need a network round-trip → throttle to a slower interval, cache in between.
const TICK_MS = 4000;
const TASKS_POLL_MS = 30000;

const TOOL_META = {
  research: {
    label: 'Research', open: 'tool-research-btn',
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  },
  cookbook: {
    label: 'Cookbook', open: 'tool-cookbook-btn',
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a6 6 0 0 0-6 6c0 2 1 3 1 5h10c0-2 1-3 1-5a6 6 0 0 0-6-6z"/><line x1="9" y1="20" x2="15" y2="20"/></svg>',
  },
  tasks: {
    label: 'Tasks', open: 'tool-tasks-btn',
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/></svg>',
  },
  project: {
    label: 'Project', open: null,
    icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-6l-2-2H5a2 2 0 0 0-2 2z"/></svg>',
  },
};

let _root = null;
let _pill = null;
let _panel = null;
let _countEl = null;
let _labelEl = null;
let _expanded = false;
let _tickInterval = null;
let _tasksCache = [];
let _tasksLastFetch = 0;
let _tasksInflight = false;
let _lastSig = null;
let _projectRun = null;

function _esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _collectResearch() {
  try {
    return getJobs()
      .filter((j) => j.status === 'running' || j.status === 'queued')
      .map((j) => ({
        tool: 'research',
        key: `research:${j.id}:${j.status}`,
        label: j.query || 'Research',
        detail: j.status === 'queued'
          ? 'Queued'
          : formatPhase(j.progress, j.settings && j.settings.max_rounds),
        elapsed: (j.status === 'running' && j.startedAt)
          ? formatElapsed(Date.now() - j.startedAt)
          : '',
      }));
  } catch { return []; }
}

function _collectCookbook() {
  try {
    return _loadCookbookTasks()
      .filter((t) => t.status === 'running' || t.status === 'queued' || t.status === 'ready')
      .map((t) => ({
        tool: 'cookbook',
        key: `cookbook:${t.sessionId || t.id || t.name}:${t.status}`,
        label: (t.payload && t.payload.repo_id) || t.name || 'Cookbook task',
        detail: t.type === 'download' ? 'Downloading'
          : t.type === 'serve' ? (t.status === 'ready' ? 'Ready' : 'Serving')
          : (t.status === 'queued' ? 'Queued' : 'Running'),
        elapsed: '',
      }));
  } catch { return []; }
}

async function _refreshTasks() {
  const now = Date.now();
  if (_tasksInflight || (now - _tasksLastFetch) < TASKS_POLL_MS) return;
  _tasksInflight = true;
  _tasksLastFetch = now;
  try {
    const res = await fetch(`${API_BASE}/api/tasks/runs/recent?limit=50`, { credentials: 'same-origin' });
    if (!res.ok) return;
    const data = await res.json().catch(() => ({}));
    const runs = data.runs || [];
    _tasksCache = runs
      .filter((r) => r.status === 'running' || r.status === 'queued')
      .map((r) => ({
        tool: 'tasks',
        key: `tasks:${r.run_id || r.session_id || r.task_id || r.started_at}:${r.status}`,
        label: r.task_name || 'Task',
        detail: r.status === 'queued' ? 'Queued' : 'Running',
        elapsed: '',
      }));
    _render();
  } catch {
    /* leave last cache in place on transient failure */
  } finally {
    _tasksInflight = false;
  }
}

function _rowHtml(item) {
  const meta = TOOL_META[item.tool] || { label: item.tool, icon: '', open: '' };
  const detail = [item.detail, item.elapsed].filter(Boolean).join(' · ');
  return `<div class="activity-strip-row" role="listitem" data-open="${_esc(meta.open)}" data-tool="${_esc(item.tool)}" title="${_esc(item.label)}">`
    + `<span class="activity-strip-row-icon">${meta.icon}</span>`
    + `<span class="activity-strip-row-main">`
    + `<span class="activity-strip-row-title">${_esc(item.label)}</span>`
    + `<span class="activity-strip-row-detail">${_esc(detail)}</span>`
    + `</span>`
    + `<span class="activity-strip-row-tool">${_esc(meta.label)}</span>`
    + `</div>`;
}

function _collectProject() {
  if (!_projectRun) return [];
  return [{
    tool: 'project',
    key: `project:${_projectRun.key || _projectRun.label}:${_projectRun.detail || 'running'}`,
    label: _projectRun.label || 'Project script',
    detail: _projectRun.detail || 'Running',
    elapsed: _projectRun.elapsed || '',
  }];
}

function _render() {
  if (!_root) return;
  const items = [..._collectResearch(), ..._collectCookbook(), ..._tasksCache, ..._collectProject()];
  const n = items.length;

  if (n === 0) {
    _root.classList.remove('active', 'expanded');
    _expanded = false;
    _pill.setAttribute('aria-expanded', 'false');
    _lastSig = '';
    return;
  }

  _root.classList.add('active');
  _countEl.textContent = String(n);
  if (_labelEl) _labelEl.textContent = 'running';
  _pill.setAttribute('aria-label', `Activity — ${n} running`);

  // Only rebuild the panel when the underlying set/status actually changed, so
  // an open panel isn't torn down mid-hover on every 4s tick.
  const sig = items.map((i) => i.key).join('|');
  if (sig !== _lastSig) {
    _lastSig = sig;
    _panel.innerHTML = items.map(_rowHtml).join('');
    _panel.querySelectorAll('.activity-strip-row').forEach((row) => {
      row.addEventListener('click', () => {
        const openId = row.dataset.open;
        const tool = row.dataset.tool;
        if (tool === 'project') {
          const footer = document.getElementById('project-workspace-footer');
          const runTab = document.querySelector('.project-bottom-tab[data-bottom-tab="run"]');
          runTab?.click();
          footer?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
          return;
        }
        if (openId) document.getElementById(openId)?.click();
      });
    });
  }
}

function _tick() {
  _refreshTasks();
  _render();
}

export function setProjectRunActivity(item) {
  _projectRun = item || null;
  _render();
}

export function initActivityStrip() {
  if (_root) return;
  _root = document.createElement('div');
  _root.id = 'activity-strip';

  // Panel first (renders above the pill in the bottom-anchored column).
  _panel = document.createElement('div');
  _panel.className = 'activity-strip-panel';
  _panel.setAttribute('role', 'list');

  _pill = document.createElement('button');
  _pill.className = 'activity-strip-pill';
  _pill.type = 'button';
  _pill.setAttribute('aria-expanded', 'false');
  _pill.setAttribute('aria-label', 'Activity — running jobs');

  const dot = document.createElement('span');
  dot.className = 'activity-strip-dot';
  _countEl = document.createElement('span');
  _countEl.className = 'activity-strip-count';
  _countEl.textContent = '0';
  _labelEl = document.createElement('span');
  _labelEl.className = 'activity-strip-label';
  _labelEl.textContent = 'running';
  _pill.appendChild(dot);
  _pill.appendChild(_countEl);
  _pill.appendChild(_labelEl);

  _root.appendChild(_panel);
  _root.appendChild(_pill);
  document.body.appendChild(_root);

  _pill.addEventListener('click', (e) => {
    e.stopPropagation();
    _expanded = !_expanded;
    _root.classList.toggle('expanded', _expanded);
    _pill.setAttribute('aria-expanded', String(_expanded));
  });

  // Collapse when clicking elsewhere.
  document.addEventListener('click', (e) => {
    if (_expanded && !_root.contains(e.target)) {
      _expanded = false;
      _root.classList.remove('expanded');
      _pill.setAttribute('aria-expanded', 'false');
    }
  });

  _tick();
  _tickInterval = setInterval(_tick, TICK_MS);
}

export function stopActivityStrip() {
  if (_tickInterval) clearInterval(_tickInterval);
  _tickInterval = null;
}

export default { initActivityStrip, stopActivityStrip, setProjectRunActivity };
