/**
 * Project workspace tab shell (Phase G1–G5).
 * Left: Links | Files — Center: content well — Bottom: Chat | Run
 */
import workspaceState from './workspaceState.js';

const LEFT_TABS = ['links', 'files'];
const BOTTOM_TABS = ['chat', 'run'];

let _projectId = null;
let _onLeftTab = null;
let _onBottomTab = null;

function _leftTabBtn(tab) {
  return document.querySelector(`.project-left-tab[data-left-tab="${tab}"]`);
}

function _bottomTabBtn(tab) {
  return document.querySelector(`.project-bottom-tab[data-bottom-tab="${tab}"]`);
}

function _setLeftTab(tab, { persist = true, notify = true } = {}) {
  const pick = LEFT_TABS.includes(tab) ? tab : 'links';
  document.querySelectorAll('.project-left-tab').forEach((btn) => {
    const active = btn.dataset.leftTab === pick;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-left-pane]').forEach((pane) => {
    pane.classList.toggle('hidden', pane.dataset.leftPane !== pick);
  });
  if (persist && _projectId) workspaceState.saveLeftTab(_projectId, pick);
  if (notify && _onLeftTab) _onLeftTab(pick);
}

function _setBottomTab(tab, { persist = true, notify = true } = {}) {
  const pick = BOTTOM_TABS.includes(tab) ? tab : 'chat';
  document.querySelectorAll('.project-bottom-tab').forEach((btn) => {
    const active = btn.dataset.bottomTab === pick;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-bottom-pane]').forEach((pane) => {
    pane.classList.toggle('hidden', pane.dataset.bottomPane !== pick);
  });
  if (persist && _projectId) workspaceState.saveBottomTab(_projectId, pick);
  if (notify && _onBottomTab) _onBottomTab(pick);
}

function _bindTabBars() {
  document.querySelectorAll('.project-left-tab').forEach((btn) => {
    if (btn.dataset.shellBound) return;
    btn.dataset.shellBound = '1';
    btn.addEventListener('click', () => {
      _setLeftTab(btn.dataset.leftTab || 'links');
    });
  });
  document.querySelectorAll('.project-bottom-tab').forEach((btn) => {
    if (btn.dataset.shellBound) return;
    btn.dataset.shellBound = '1';
    btn.addEventListener('click', () => {
      _setBottomTab(btn.dataset.bottomTab || 'chat');
    });
  });
}

export function mount(projectId, { onLeftTab, onBottomTab } = {}) {
  _projectId = projectId;
  _onLeftTab = onLeftTab || null;
  _onBottomTab = onBottomTab || null;
  _bindTabBars();
  const left = workspaceState.getLeftTab(projectId) || 'links';
  const bottom = workspaceState.getBottomTab(projectId) || 'chat';
  _setLeftTab(left, { persist: false, notify: false });
  _setBottomTab(bottom, { persist: false, notify: false });
  if (_onLeftTab) _onLeftTab(left);
  if (_onBottomTab) _onBottomTab(bottom);
}

export function unmount() {
  _projectId = null;
  _onLeftTab = null;
  _onBottomTab = null;
}

export function setLeftTab(tab, opts) {
  _setLeftTab(tab, opts);
}

export function setBottomTab(tab, opts) {
  _setBottomTab(tab, opts);
}

export function focusRunTab() {
  _setBottomTab('run');
}

export function focusChatTab() {
  _setBottomTab('chat');
}

export function getLeftTab() {
  return _leftTabBtn('files')?.classList.contains('active') ? 'files' : 'links';
}

export function getBottomTab() {
  return _bottomTabBtn('run')?.classList.contains('active') ? 'run' : 'chat';
}

export default {
  mount,
  unmount,
  setLeftTab,
  setBottomTab,
  focusRunTab,
  focusChatTab,
  getLeftTab,
  getBottomTab,
};
