/**
 * Run tab badge indicator (Phase G8) — running pulse or error dot on bottom Run tab.
 */
let _state = null;

export function setRunTabBadge(state) {
  _state = state || null;
  const btn = document.querySelector('.project-bottom-tab--run');
  if (!btn) return;
  btn.classList.toggle('project-bottom-tab--badge', !!state);
  btn.classList.toggle('project-bottom-tab--badge-error', state === 'error');
  btn.classList.toggle('project-bottom-tab--badge-running', state === 'running');
  btn.setAttribute('aria-label', state === 'running' ? 'Run — script running' : state === 'error' ? 'Run — script failed' : 'Run');
}

export function getRunTabBadge() {
  return _state;
}

export default { setRunTabBadge, getRunTabBadge };
