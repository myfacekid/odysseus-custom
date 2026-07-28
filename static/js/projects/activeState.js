/**
 * Active project preference for the harness context layer.
 * Migrates legacy `odysseus_project_last_open` once into the chip key.
 */
import Storage from '../storage.js';
import { LAST_OPEN_PROJECT_KEY, clearLastOpenProject } from './workspaceState.js';

export const ACTIVE_PROJECT_KEY = 'odysseus_active_project_id';
export const ACTIVE_PROJECT_EVENT = 'odysseus-active-project-changed';

let _cache = undefined;

function _emit(id) {
  try {
    window.dispatchEvent(new CustomEvent(ACTIVE_PROJECT_EVENT, { detail: { projectId: id || null } }));
  } catch {
    /* ignore */
  }
}

/** One-time migrate last-open workspace → active chip. */
export function migrateLastOpenToActive() {
  try {
    const existing = Storage.get(ACTIVE_PROJECT_KEY, null);
    if (existing) return existing;
    const legacy = Storage.get(LAST_OPEN_PROJECT_KEY, null);
    if (legacy) {
      Storage.set(ACTIVE_PROJECT_KEY, legacy);
      clearLastOpenProject();
      _cache = legacy;
      return legacy;
    }
  } catch {
    /* ignore */
  }
  return null;
}

export function getActiveProjectId() {
  if (_cache !== undefined) return _cache;
  try {
    migrateLastOpenToActive();
    const id = Storage.get(ACTIVE_PROJECT_KEY, null);
    _cache = typeof id === 'string' && id.trim() ? id.trim() : null;
  } catch {
    _cache = null;
  }
  return _cache;
}

export function setActiveProjectId(projectId) {
  const next = typeof projectId === 'string' && projectId.trim() ? projectId.trim() : null;
  _cache = next;
  try {
    if (next) Storage.set(ACTIVE_PROJECT_KEY, next);
    else Storage.remove(ACTIVE_PROJECT_KEY);
  } catch {
    /* ignore */
  }
  _emit(next);
  return next;
}

export function clearActiveProjectId() {
  return setActiveProjectId(null);
}

export default {
  ACTIVE_PROJECT_KEY,
  ACTIVE_PROJECT_EVENT,
  getActiveProjectId,
  setActiveProjectId,
  clearActiveProjectId,
  migrateLastOpenToActive,
};
