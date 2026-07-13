/**
 * Live readiness checks for chat, research, and Links — used by Getting started
 * and setup-style empty states (U1).
 */

const SEARCH_NEEDS_KEY = { brave: 1, google_pse: 1, tavily: 1, serper: 1 };
const SEARCH_KEY_FIELDS = {
  brave: 'brave_api_key',
  google_pse: 'google_pse_key',
  tavily: 'tavily_api_key',
  serper: 'serper_api_key',
};
const SEARCH_LABELS = {
  searxng: 'SearXNG',
  duckduckgo: 'DuckDuckGo',
  brave: 'Brave Search',
  google_pse: 'Google PSE',
  tavily: 'Tavily',
  serper: 'Serper',
  disabled: 'Disabled',
};

export const ZOTERO_SETUP_PATH = 'Settings → Search → Zotero';
export const ZOTERO_SETUP_MSG = `Sync your library in ${ZOTERO_SETUP_PATH}, then Sync catalog.`;

function _webSearchOk(settings) {
  const prov = settings?.search_provider || 'searxng';
  if (prov === 'disabled') {
    return { ok: false, detail: 'Web search is disabled' };
  }
  if (SEARCH_NEEDS_KEY[prov]) {
    const kf = SEARCH_KEY_FIELDS[prov];
    const raw = kf ? (settings[kf] || settings.search_api_key || '') : '';
    const hasKey = !!String(raw).trim();
    if (!hasKey) {
      return { ok: false, detail: `${SEARCH_LABELS[prov] || prov} needs an API key` };
    }
  }
  const label = SEARCH_LABELS[prov] || prov;
  return { ok: true, detail: `${label} configured` };
}

function _endpointOk(endpoints) {
  const enabled = (endpoints || []).filter((e) => e && e.is_enabled !== false);
  if (!enabled.length) {
    return { ok: false, detail: 'No model endpoint enabled — add one under Add Models' };
  }
  const names = enabled.slice(0, 2).map((e) => e.name || e.id).filter(Boolean);
  const extra = enabled.length > 2 ? ` +${enabled.length - 2} more` : '';
  return {
    ok: true,
    detail: names.length ? `${enabled.length} enabled (${names.join(', ')}${extra})` : `${enabled.length} endpoint(s) enabled`,
  };
}

function _zoteroOk(cfg) {
  const catalog = cfg?.catalog;
  if (catalog?.synced) {
    const n = catalog.item_count || 0;
    return { ok: true, detail: n ? `${n} papers in local catalog` : 'Catalog synced (empty library)' };
  }
  if (cfg?.configured) {
    return { ok: false, detail: 'Zotero connected — run Sync catalog' };
  }
  return { ok: false, detail: 'Not connected — add User ID and API key' };
}

/**
 * @returns {Promise<{ endpoint: object, webSearch: object, zotero: object, allOk: boolean }>}
 */
export async function fetchSetupStatus() {
  const [epRes, settingsRes, zoteroRes] = await Promise.all([
    fetch('/api/model-endpoints', { credentials: 'same-origin' }).catch(() => null),
    fetch('/api/auth/settings', { credentials: 'same-origin' }).catch(() => null),
    fetch('/api/zotero/config', { credentials: 'same-origin' }).catch(() => null),
  ]);

  let endpoints = [];
  let settings = {};
  let zoteroCfg = {};

  try {
    if (epRes?.ok) {
      const data = await epRes.json();
      endpoints = Array.isArray(data) ? data : [];
    }
  } catch { /* ignore */ }

  try {
    if (settingsRes?.ok) settings = await settingsRes.json();
  } catch { /* ignore */ }

  try {
    if (zoteroRes?.ok) zoteroCfg = await zoteroRes.json();
  } catch { /* ignore */ }

  const epState = _endpointOk(endpoints);
  const searchState = _webSearchOk(settings);
  const zoteroState = _zoteroOk(zoteroCfg);

  const endpoint = {
    id: 'endpoint',
    label: 'Model endpoint',
    fixTab: 'services',
    ...epState,
  };
  const webSearch = {
    id: 'webSearch',
    label: 'Web search',
    fixTab: 'search',
    ...searchState,
  };
  const zotero = {
    id: 'zotero',
    label: 'Zotero catalog',
    fixTab: 'search',
    ...zoteroState,
  };

  return {
    endpoint,
    webSearch,
    zotero,
    allOk: endpoint.ok && webSearch.ok && zotero.ok,
  };
}

export async function isZoteroCatalogReady() {
  try {
    const res = await fetch('/api/zotero/config', { credentials: 'same-origin' });
    if (!res.ok) return false;
    const cfg = await res.json();
    return !!cfg?.catalog?.synced;
  } catch {
    return false;
  }
}

export function notifySetupStatusChanged() {
  try {
    window.dispatchEvent(new CustomEvent('setup-status-changed'));
  } catch { /* ignore */ }
}
