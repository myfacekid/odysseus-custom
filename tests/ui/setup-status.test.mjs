// Unit tests for Getting started readiness helpers.
//
// Run with:  node --test tests/ui/setup-status.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const modUrl = pathToFileURL(join(here, '..', '..', 'static', 'js', 'setupStatus.js')).href;

function mockFetch(map) {
  return async (url) => {
    const key = String(url).replace(/^https?:\/\/[^/]+/, '');
    const hit = map[key] ?? map[url];
    if (!hit) return { ok: false, json: async () => ({}) };
    return {
      ok: true,
      json: async () => hit,
    };
  };
}

test('readyForChat with endpoint only — Zotero missing does not block', async () => {
  const prev = globalThis.fetch;
  globalThis.fetch = mockFetch({
    '/api/model-endpoints': [{ id: '1', name: 'local', is_enabled: true }],
    '/api/auth/settings': { search_provider: 'disabled' },
    '/api/zotero/config': { configured: false },
  });
  try {
    const { fetchSetupStatus } = await import(`${modUrl}?t=${Date.now()}`);
    const s = await fetchSetupStatus();
    assert.equal(s.readyForChat, true);
    assert.equal(s.readyForResearch, false);
    assert.equal(s.zotero.required, false);
    assert.equal(s.allOk, false);
  } finally {
    globalThis.fetch = prev;
  }
});

test('readyForResearch needs endpoint + web search', async () => {
  const prev = globalThis.fetch;
  globalThis.fetch = mockFetch({
    '/api/model-endpoints': [{ id: '1', name: 'local', is_enabled: true }],
    '/api/auth/settings': { search_provider: 'searxng' },
    '/api/zotero/config': { configured: false },
  });
  try {
    const { fetchSetupStatus } = await import(`${modUrl}?t=${Date.now() + 1}`);
    const s = await fetchSetupStatus();
    assert.equal(s.readyForChat, true);
    assert.equal(s.readyForResearch, true);
    assert.equal(s.allOk, false);
  } finally {
    globalThis.fetch = prev;
  }
});

test('no endpoints → not ready for chat', async () => {
  const prev = globalThis.fetch;
  globalThis.fetch = mockFetch({
    '/api/model-endpoints': [],
    '/api/auth/settings': { search_provider: 'duckduckgo' },
    '/api/zotero/config': { catalog: { synced: true, item_count: 3 } },
  });
  try {
    const { fetchSetupStatus } = await import(`${modUrl}?t=${Date.now() + 2}`);
    const s = await fetchSetupStatus();
    assert.equal(s.readyForChat, false);
    assert.equal(s.readyForResearch, false);
    assert.equal(s.zotero.ok, true);
  } finally {
    globalThis.fetch = prev;
  }
});
