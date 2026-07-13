/**
 * Projects UI feature flag.
 *
 * The workspace shell is paused while Projects are redesigned as a
 * harness-level context layer (see docs/projects-context-layer-roadmap.md).
 * Backend APIs remain; this only gates user-facing Projects chrome.
 */
export const PROJECTS_UI_ENABLED = false;

const HIDE_SELECTORS = [
  '#sidebar-new-project-btn',
  '#projects-section',
  '#project-workspace-panel',
  '#project-overflow-wrap',
  '#project-mode-pill',
  '.vis-row:has([data-ui-key="projects-section"])',
];

/** Hide Projects chrome so users cannot enter the workspace shell. */
export function hideProjectsUi() {
  document.body.classList.add('projects-ui-hidden');
  for (const sel of HIDE_SELECTORS) {
    document.querySelectorAll(sel).forEach((el) => {
      el.hidden = true;
      el.setAttribute('aria-hidden', 'true');
    });
  }
  // Force Appearance visibility off so a cached preference cannot re-show it.
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
