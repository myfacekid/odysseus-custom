/**
 * Project workspace layout presets, collapse, and mobile drawers (P6/P8).
 */
import uiModule from '../ui.js';
import workspaceState from './workspaceState.js';
import workspaceShell from './workspaceShell.js';
import workspaceResize from './workspaceResize.js';

const MOBILE_MQ = '(max-width: 768px)';
const LEFT_ICON_WIDTH = 48;

export const LAYOUT_PRESETS = {
  research: {
    label: 'Research',
    leftTab: 'links',
    footerExpanded: false,
    leftCollapsed: false,
    footerMinimized: false,
  },
  code: {
    label: 'Code',
    leftTab: 'files',
    footerExpanded: true,
    leftCollapsed: false,
    footerMinimized: false,
  },
  focus: {
    label: 'Focus',
    leftTab: 'links',
    footerExpanded: false,
    leftCollapsed: true,
    footerMinimized: true,
  },
  split: {
    label: 'Split',
    leftTab: 'links',
    footerExpanded: false,
    leftCollapsed: false,
    footerMinimized: false,
    centerSplit: true,
  },
};

let _projectId = null;
let _leftCollapsed = false;
let _footerMinimized = false;
let _mobileLeftOpen = false;
let _mobileFooterOpen = false;
let _mq = null;

function _grid() {
  return document.getElementById('project-workspace-grid');
}

function _panel() {
  return document.getElementById('project-workspace-panel');
}

function _isMobile() {
  return window.matchMedia(MOBILE_MQ).matches;
}

function _syncBodyClasses() {
  const panel = _panel();
  if (!panel) return;
  panel.classList.toggle('project-left-collapsed', _leftCollapsed && !_isMobile());
  panel.classList.toggle('project-footer-minimized', _footerMinimized && !_isMobile());
  panel.classList.toggle('project-mobile-left-open', _mobileLeftOpen && _isMobile());
  panel.classList.toggle('project-mobile-footer-open', _mobileFooterOpen && _isMobile());
  document.body.classList.toggle('project-mobile-active', !!_projectId && _isMobile());
}

export function toggleLeftCollapsed() {
  _leftCollapsed = !_leftCollapsed;
  if (_projectId) workspaceState.saveLayoutPreset(_projectId, { leftCollapsed: _leftCollapsed });
  workspaceResize.setLeftCollapsed(_leftCollapsed);
  _syncBodyClasses();
  uiModule.showToast?.(_leftCollapsed ? 'Sidebar collapsed' : 'Sidebar expanded');
}

export function toggleFooterMinimized() {
  _footerMinimized = !_footerMinimized;
  if (_projectId) workspaceState.saveLayoutPreset(_projectId, { footerMinimized: _footerMinimized });
  workspaceResize.setFooterMinimized(_footerMinimized);
  _syncBodyClasses();
}

export function applyLayoutPreset(presetKey) {
  const preset = LAYOUT_PRESETS[presetKey];
  if (!preset || !_projectId) return;

  workspaceState.saveLayoutPreset(_projectId, { preset: presetKey, ...preset });
  workspaceShell.setLeftTab(preset.leftTab);
  _leftCollapsed = !!preset.leftCollapsed;
  _footerMinimized = !!preset.footerMinimized;
  workspaceResize.setLeftCollapsed(_leftCollapsed);
  workspaceResize.setFooterMinimized(_footerMinimized);
  if (preset.footerExpanded) workspaceResize.expandFooter();
  else workspaceResize.collapseFooter();

  if (preset.centerSplit) {
    const splitBtn = document.getElementById('project-split-toggle');
    if (splitBtn && splitBtn.getAttribute('aria-pressed') !== 'true') splitBtn.click();
  }

  _syncBodyClasses();
  uiModule.showToast?.(`Layout: ${preset.label}`);
}

function _closeMobileDrawers() {
  _mobileLeftOpen = false;
  _mobileFooterOpen = false;
  _syncBodyClasses();
}

function _toggleMobileLeft() {
  _mobileLeftOpen = !_mobileLeftOpen;
  if (_mobileLeftOpen) _mobileFooterOpen = false;
  _syncBodyClasses();
}

function _toggleMobileFooter() {
  _mobileFooterOpen = !_mobileFooterOpen;
  if (_mobileFooterOpen) _mobileLeftOpen = false;
  _syncBodyClasses();
}

function _onMqChange() {
  if (!_isMobile()) _closeMobileDrawers();
  _syncBodyClasses();
  workspaceResize.setLeftCollapsed(_leftCollapsed && !_isMobile());
  workspaceResize.setFooterMinimized(_footerMinimized && !_isMobile());
}

function _bindControls() {
  document.getElementById('project-left-collapse-btn')?.addEventListener('click', () => {
    if (_isMobile()) _toggleMobileLeft();
    else toggleLeftCollapsed();
  });

  document.getElementById('project-mobile-footer-grabber')?.addEventListener('click', () => {
    _toggleMobileFooter();
  });

  document.getElementById('project-left-drawer-backdrop')?.addEventListener('click', () => {
    _closeMobileDrawers();
  });

  document.querySelectorAll('[data-layout-preset]').forEach((btn) => {
    if (btn.dataset.layoutBound) return;
    btn.dataset.layoutBound = '1';
    btn.addEventListener('click', () => {
      applyLayoutPreset(btn.dataset.layoutPreset);
      document.getElementById('project-overflow-menu')?.classList.remove('open');
    });
  });
}

export function mount(projectId) {
  _projectId = projectId;
  const saved = workspaceState.getLayoutPreset(projectId);
  _leftCollapsed = saved.leftCollapsed === true;
  _footerMinimized = saved.footerMinimized === true;
  _closeMobileDrawers();

  if (!saved.preset && !workspaceState.getLeftTab(projectId)) {
    workspaceState.saveLayoutPreset(projectId, { preset: 'research' });
  }

  workspaceResize.setLeftCollapsed(_leftCollapsed && !_isMobile());
  workspaceResize.setFooterMinimized(_footerMinimized && !_isMobile());
  _syncBodyClasses();
  _bindControls();

  if (!_mq) {
    _mq = window.matchMedia(MOBILE_MQ);
    _mq.addEventListener('change', _onMqChange);
  }
}

export function unmount() {
  _projectId = null;
  _closeMobileDrawers();
  document.body.classList.remove('project-mobile-active');
  const panel = _panel();
  panel?.classList.remove('project-left-collapsed', 'project-footer-minimized', 'project-mobile-left-open', 'project-mobile-footer-open');
}

export default {
  mount,
  unmount,
  applyLayoutPreset,
  toggleLeftCollapsed,
  toggleFooterMinimized,
  LAYOUT_PRESETS,
};
