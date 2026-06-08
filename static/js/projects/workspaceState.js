/**
 * Per-project workspace UI persistence (Phase D3).
 * Stores last open file + active chat in localStorage (keyed by project id).
 */
import Storage from '../storage.js';

const STATE_PREFIX = 'odysseus_project_workspace:';
export const LAST_OPEN_PROJECT_KEY = 'odysseus_project_last_open';

function _key(projectId) {
  return `${STATE_PREFIX}${projectId || ''}`;
}

export function loadState(projectId) {
  if (!projectId) return {};
  return Storage.getJSON(_key(projectId), {}) || {};
}

export function saveState(projectId, patch) {
  if (!projectId || !patch || typeof patch !== 'object') return;
  const next = { ...loadState(projectId), ...patch };
  Storage.setJSON(_key(projectId), next);
}

export function getOpenFile(projectId) {
  const path = loadState(projectId).openFile;
  return typeof path === 'string' && path.trim() ? path.trim() : null;
}

export function saveOpenFile(projectId, path) {
  saveState(projectId, { openFile: path || null });
}

export function getActiveChat(projectId) {
  const id = loadState(projectId).activeChatId;
  return typeof id === 'string' && id.trim() ? id.trim() : null;
}

export function saveActiveChat(projectId, sessionId) {
  saveState(projectId, { activeChatId: sessionId || null });
}

export function saveLastOpenProject(projectId) {
  if (!projectId) return;
  try {
    Storage.set(LAST_OPEN_PROJECT_KEY, projectId);
  } catch {}
}

export function getLastOpenProject() {
  try {
    return Storage.get(LAST_OPEN_PROJECT_KEY, null);
  } catch {
    return null;
  }
}

export default {
  loadState,
  saveState,
  getOpenFile,
  saveOpenFile,
  getActiveChat,
  saveActiveChat,
  saveLastOpenProject,
  getLastOpenProject,
};
