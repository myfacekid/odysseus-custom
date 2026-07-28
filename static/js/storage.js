// static/js/storage.js
// Centralized localStorage access with key constants and JSON parse safety

// ── Key constants ──
const LEGACY_KEY_MAP = {
  'nobody-theme': ['oculus-theme', 'odysseus-theme'],
  'nobody-toggles': ['oculus-toggles', 'odysseus-toggles'],
  'nobody-model-expanded': ['oculus-model-expanded', 'odysseus-model-expanded'],
  'nobody-model-endpoints': ['oculus-model-endpoints', 'odysseus-model-endpoints'],
  'nobody-selected-model': ['oculus-selected-model', 'odysseus-selected-model'],
  'nobody-sessions-sort': ['oculus-sessions-sort', 'odysseus-sessions-sort'],
  'nobody-search-scope': ['oculus-search-scope', 'odysseus-search-scope'],
  'nobody-incognito': ['oculus-incognito', 'odysseus-incognito'],
  'nobody-rag-active': ['oculus-rag-active', 'odysseus-rag-active'],
  'nobody-mcp-active': ['oculus-mcp-active', 'odysseus-mcp-active'],
  'nobody-density': ['oculus-density', 'odysseus-density'],
};

function _readKey(key) {
  try {
    let val = localStorage.getItem(key);
    if (val !== null) return val;
    for (const legacy of LEGACY_KEY_MAP[key] || []) {
      val = localStorage.getItem(legacy);
      if (val !== null) {
        localStorage.setItem(key, val);
        return val;
      }
    }
  } catch (_) {}
  return null;
}

export const KEYS = {
  THEME: 'nobody-theme',
  TOGGLES: 'nobody-toggles',
  SIDEBAR_COLLAPSED: 'sidebar-collapsed',
  SIDEBAR_WIDTH: 'sidebar-width',
  SIDEBAR_SIDE: 'sidebar-side',
  CURRENT_SESSION: 'currentSessionId',
  COMPARE_SAVE: 'compare-save-results',
  COMPARE_CHAT: 'compare-continue-chat',
  COMPARE_BLIND: 'compare-blind',
  COMPARE_RANDOM: 'compare-randomize',
  MODELS_EXPANDED: 'nobody-model-expanded',
  MODEL_ENDPOINTS: 'nobody-model-endpoints',
  MODEL_SELECTED: 'nobody-selected-model',
  SORT_ORDER: 'nobody-sessions-sort',
  CHAT_SEARCH_SCOPE: 'nobody-search-scope',
  INCOGNITO: 'nobody-incognito',
  RAG_ACTIVE: 'nobody-rag-active',
  MCP_ACTIVE: 'nobody-mcp-active',
  SECTION_ORDER: 'sidebar-section-order',
  ADMIN_LAST_TAB: 'admin-last-tab',
  DENSITY: 'nobody-density'
};

/**
 * Safely get and parse a JSON value from localStorage.
 * Returns fallback on any error.
 */
export function getJSON(key, fallback) {
  try {
    const raw = _readKey(key);
    if (raw === null) return fallback !== undefined ? fallback : null;
    return JSON.parse(raw);
  } catch (e) {
    console.warn('[Storage] Failed to parse key "' + key + '":', e.message);
    return fallback !== undefined ? fallback : null;
  }
}

/**
 * Set a JSON-serialized value in localStorage.
 * When writing a canonical key that has legacy aliases, drop the aliases so
 * readers that still check old names (or a stale migrated copy) cannot
 * override the fresh value.
 */
export function setJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    for (const legacy of LEGACY_KEY_MAP[key] || []) {
      try { localStorage.removeItem(legacy); } catch (_) {}
    }
  } catch (e) {
    console.warn('[Storage] Failed to set key "' + key + '":', e.message);
  }
}

/**
 * Get a raw string value from localStorage.
 */
export function get(key, fallback) {
  try {
    const val = _readKey(key);
    return val !== null ? val : (fallback !== undefined ? fallback : null);
  } catch (e) {
    return fallback !== undefined ? fallback : null;
  }
}

/**
 * Set a raw string value in localStorage.
 */
export function set(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (e) {
    console.warn('[Storage] Failed to set key "' + key + '":', e.message);
  }
}

/**
 * Remove a key from localStorage (and any legacy aliases for that key).
 */
export function remove(key) {
  try {
    localStorage.removeItem(key);
    for (const legacy of LEGACY_KEY_MAP[key] || []) {
      try { localStorage.removeItem(legacy); } catch (_) {}
    }
  } catch (e) {
    // Ignore removal errors
  }
}

// ── Toggle state helpers ──

export function loadToggleState() {
  return getJSON(KEYS.TOGGLES, {});
}

export function saveToggleState(state) {
  setJSON(KEYS.TOGGLES, state);
}

export function getToggle(name, fallback) {
  const state = loadToggleState();
  return state[name] !== undefined ? state[name] : (fallback !== undefined ? fallback : false);
}

export function setToggle(name, value) {
  const state = loadToggleState();
  state[name] = value;
  saveToggleState(state);
}

const Storage = {
  KEYS,
  getJSON,
  setJSON,
  get,
  set,
  remove,
  loadToggleState,
  saveToggleState,
  getToggle,
  setToggle
};

export default Storage;
