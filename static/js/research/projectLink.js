/**
 * Phase E — link completed Deep Research to Projects (breadth boundary).
 * Optional picker for compare/gap; post-complete confirm (never auto-link).
 */
import uiModule from '../ui.js';
import { isProjectsUiEnabled } from '../projects/featureFlag.js';

const SUGGEST_DISMISS_KEY = 'odysseus-research-project-suggest-dismissed';
const PROJECT_MODES = new Set(['compare', 'gap_analysis']);

let _projectsCache = [];
let _projectsLoadedAt = 0;
const _CACHE_MS = 60_000;

function _loadDismissed() {
  try {
    const raw = localStorage.getItem(SUGGEST_DISMISS_KEY);
    return new Set(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

function _markDismissed(sessionId) {
  if (!sessionId) return;
  const set = _loadDismissed();
  set.add(sessionId);
  try {
    localStorage.setItem(SUGGEST_DISMISS_KEY, JSON.stringify([...set].slice(-200)));
  } catch {}
}

export function modeWantsProjectLink(mode) {
  return PROJECT_MODES.has((mode || '').trim().toLowerCase());
}

export function researchNodeId(sessionId) {
  const sid = (sessionId || '').trim();
  if (!sid) return '';
  return sid.startsWith('research:') ? sid : `research:${sid}`;
}

export async function fetchProjects(apiBase) {
  const now = Date.now();
  if (_projectsCache.length && now - _projectsLoadedAt < _CACHE_MS) {
    return _projectsCache;
  }
  const res = await fetch(`${apiBase}/api/projects`, { credentials: 'same-origin' });
  if (!res.ok) throw new Error('Could not load projects');
  const data = await res.json();
  _projectsCache = (data.projects || []).filter((p) => !p.archived);
  _projectsLoadedAt = now;
  return _projectsCache;
}

export async function populateProjectSelect(apiBase, selectEl) {
  if (!selectEl) return;
  const current = selectEl.value;
  selectEl.innerHTML = '<option value="">None — decide after research</option>';
  try {
    const projects = await fetchProjects(apiBase);
    for (const p of projects) {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.title || p.id;
      selectEl.appendChild(opt);
    }
    if (current && [...selectEl.options].some((o) => o.value === current)) {
      selectEl.value = current;
    }
  } catch {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Projects unavailable';
    selectEl.appendChild(opt);
  }
}

export function updateProjectPickerVisibility() {
  const wrap = document.getElementById('research-project-setting-wrap');
  if (!wrap) return;
  if (!isProjectsUiEnabled()) {
    wrap.hidden = true;
    return;
  }
  const tab = document.querySelector('.research-compose-tab.active')?.getAttribute('data-tab') || 'topic';
  const mode = document.getElementById('research-mode')?.value || 'literature_review';
  const show = tab === 'papers' && modeWantsProjectLink(mode);
  wrap.hidden = !show;
}

export function readSelectedProjectId() {
  return (document.getElementById('research-project-id')?.value || '').trim();
}

export async function linkResearchToProject(apiBase, projectId, sessionId) {
  const pid = (projectId || '').trim();
  const sid = (sessionId || '').trim();
  if (!pid || !sid) throw new Error('Missing project or research id');
  const res = await fetch(
    `${apiBase}/api/projects/${encodeURIComponent(pid)}/links`,
    {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ to_id: researchNodeId(sid), kind: 'related' }),
    },
  );
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || data.error || 'Link failed');
  return data;
}

async function _pickProject(apiBase, title = 'Add to project') {
  let projects;
  try {
    projects = await fetchProjects(apiBase);
  } catch (e) {
    uiModule.showToast?.(e.message || 'Could not load projects', 4000);
    return null;
  }
  if (!projects.length) {
    uiModule.showToast?.('Create a project first (Projects nav)', 4000);
    return null;
  }
  const choice = await uiModule.styledListPick?.(
    'Link this research to a project workspace? It appears in the linked knowledge rail — not auto-imported into your code folder.',
    {
      title,
      items: projects.map((p) => ({
        id: p.id,
        label: p.title || p.id,
        hint: (p.working_dir || p.id || '').replace(/^~/, '~'),
      })),
      cancelLabel: 'Not now',
      emptyLabel: 'No projects yet',
    },
  );
  if (!choice) return null;
  return choice;
}

/**
 * Post-complete suggest for compare/gap jobs (confirm only — never silent link).
 */
export async function suggestLinkAfterComplete(job, apiBase) {
  if (!isProjectsUiEnabled()) return;
  if (!job || job.status !== 'done' || !job.id || job.id.startsWith('pending-')) return;
  const mode = (job.settings?.mode || '').trim().toLowerCase();
  if (!modeWantsProjectLink(mode)) return;
  if (_loadDismissed().has(job.id)) return;

  const srcCount = job.sources?.length ?? job.sourceCount ?? 0;
  if (srcCount === 0) return;

  let projectId = (job.settings?.project_id || '').trim();
  let projects = [];
  try {
    projects = await fetchProjects(apiBase);
  } catch {
    return;
  }

  if (projectId) {
    const project = projects.find((p) => p.id === projectId);
    if (!project) return;
    const ok = uiModule.styledConfirm
      ? await uiModule.styledConfirm(
          `Link this ${mode === 'compare' ? 'compare' : 'gap analysis'} research to "${project.title}"? It will show in that project's linked knowledge rail.`,
          { confirmText: 'Link to project', title: 'Add to project' },
        )
      : false;
    if (!ok) {
      _markDismissed(job.id);
      return;
    }
  } else if (projects.length) {
    projectId = await _pickProject(apiBase, 'Research complete');
    if (!projectId) {
      _markDismissed(job.id);
      return;
    }
  } else {
    return;
  }

  try {
    const data = await linkResearchToProject(apiBase, projectId, job.id);
    const project = projects.find((p) => p.id === projectId);
    const dup = data.duplicate ? ' (already linked)' : '';
    uiModule.showToast?.(`Linked to ${project?.title || 'project'}${dup}`, 3500);
    if (window.refreshProjectWorkspaceLinks) {
      void window.refreshProjectWorkspaceLinks(projectId);
    }
  } catch (e) {
    uiModule.showToast?.(e.message || 'Could not link to project', 4000);
  }
}

/** Manual action from completed job card — any research mode. */
export async function promptLinkResearchJob(job, apiBase) {
  if (!isProjectsUiEnabled()) return;
  if (!job?.id || job.id.startsWith('pending-')) return;
  const projectId = await _pickProject(apiBase, 'Link research to project');
  if (!projectId) return;
  try {
    const data = await linkResearchToProject(apiBase, projectId, job.id);
    const projects = await fetchProjects(apiBase);
    const project = projects.find((p) => p.id === projectId);
    const dup = data.duplicate ? ' (already linked)' : '';
    uiModule.showToast?.(`Linked to ${project?.title || 'project'}${dup}`, 3500);
    if (window.refreshProjectWorkspaceLinks) {
      void window.refreshProjectWorkspaceLinks(projectId);
    }
  } catch (e) {
    uiModule.showToast?.(e.message || 'Could not link to project', 4000);
  }
}

export function invalidateProjectsCache() {
  _projectsCache = [];
  _projectsLoadedAt = 0;
}
