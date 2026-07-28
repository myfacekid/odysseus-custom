/**
 * Projects feature flags.
 *
 * Context layer (chip, scope, promote) is on. The IDE-style workspace shell
 * stays off — see docs/projects-context-layer-roadmap.md.
 */
export const PROJECTS_UI_ENABLED = false;
export const PROJECTS_CONTEXT_LAYER_ENABLED = true;
/** Interactive home-dir browser for picking a project cwd on the server. Off —
 *  type a path or use the system folder picker instead. */
export const PROJECT_SERVER_DIR_BROWSE_ENABLED = false;

const HIDE_SELECTORS = [
  '#sidebar-new-project-btn',
  '#projects-section',
  '#project-workspace-panel',
  '#project-overflow-wrap',
  '#project-mode-pill',
  '.vis-row:has([data-ui-key="projects-section"])',
];

/** Hide Projects workspace chrome so users cannot enter the IDE shell. */
export function hideProjectsUi() {
  document.body.classList.add('projects-ui-hidden');
  for (const sel of HIDE_SELECTORS) {
    document.querySelectorAll(sel).forEach((el) => {
      el.hidden = true;
      el.setAttribute('aria-hidden', 'true');
    });
  }
  try {
    const raw = localStorage.getItem('ui-visibility');
    const prefs = raw ? JSON.parse(raw) : {};
    if (prefs['projects-section'] !== false) {
      prefs['projects-section'] = false;
      localStorage.setItem('ui-visibility', JSON.stringify(prefs));
    }
  } catch {
    /* ignore */
  }
}

export function isProjectsUiEnabled() {
  return PROJECTS_UI_ENABLED === true;
}

export function isProjectsContextLayerEnabled() {
  return PROJECTS_CONTEXT_LAYER_ENABLED === true;
}

export function isProjectServerDirBrowseEnabled() {
  return PROJECT_SERVER_DIR_BROWSE_ENABLED === true;
}
