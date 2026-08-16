// Structural smoke tests for harness-gap UI: Ask/Auto, ctx ring layout,
// steer chip, Getting started readiness (Zotero optional for chat).
//
// Run with:  node --test tests/ui/harness-gaps.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

const indexHtml = read('static/index.html');
const styleCss = read('static/style.css');
const appJs = read('static/app.js');
const chatJs = read('static/js/chat.js');
const chatRenderer = read('static/js/chatRenderer.js');
const setupStatus = read('static/js/setupStatus.js');
const settingsJs = read('static/js/settings.js');

test('Ask/Auto toggle lives beside mode pill and is agent/plan-only', () => {
  assert.ok(indexHtml.includes('id="agent-perm-toggle"'));
  assert.match(indexHtml, /perm-toggle[\s\S]*?data-perm="ask"/);
  assert.match(appJs, /mode === 'agent' \|\| mode === 'plan'\) permToggle\.removeAttribute\('hidden'\)/);
  assert.match(appJs, /\/api\/prefs\/agent_permission_mode/);
});

test('narrow composer hides perm-toggle before crowding send', () => {
  assert.match(
    styleCss,
    /@container chatbar \(max-width: 420px\)[\s\S]*?\.chat-input-right \.perm-toggle \{ display: none !important; \}/,
  );
  assert.match(
    styleCss,
    /@container chatbar \(max-width: 340px\)[\s\S]*?\.chat-input-right \.perm-toggle \{ display: none !important; \}/,
  );
});

test('msg-actions stay end-aligned so ctx-ring does not shove them', () => {
  assert.match(styleCss, /\.msg-actions \{[\s\S]*?margin-left: auto/);
  assert.match(chatRenderer, /insertBefore\(ctxRing, insertBeforeEl\)/);
  assert.match(chatRenderer, /context_breakdown/);
  assert.match(chatRenderer, /ctx-detail-popup/);
  assert.match(chatRenderer, /window\.innerWidth - pr\.width/);
});

test('steer chip is compact and Enter-while-streaming queues redirect', () => {
  assert.ok(indexHtml.includes('id="steer-queue-chip"'));
  assert.match(styleCss, /\.steer-queue-chip \{[\s\S]*?max-height: 1\.4em/);
  assert.match(chatJs, /queueMidRunSteer/);
  assert.match(chatJs, /\/api\/chat\/steer\//);
  assert.match(chatJs, /steerText\)[\s\S]*?queueMidRunSteer/);
});

test('approval card + change tape stay width-capped in chat column', () => {
  assert.match(styleCss, /\.tool-approval-card \{[\s\S]*?max-width: min\(420px, 100%\)/);
  assert.match(styleCss, /\.change-tape \{[\s\S]*?max-width: min\(480px, 100%\)/);
  assert.match(chatJs, /tool_approval_required/);
  assert.match(chatJs, /change_tape/);
  assert.match(chatRenderer, /change_tape/);
});

test('readyForChat ignores Zotero; readyForResearch needs search', () => {
  assert.match(setupStatus, /const readyForChat = !!endpoint\.ok;/);
  assert.match(
    setupStatus,
    /const readyForResearch = !!endpoint\.ok && !!webSearch\.ok;/,
  );
  assert.match(setupStatus, /required: false[\s\S]*?zotero|zotero:[\s\S]*?required: false/);
  assert.match(settingsJs, /status\.readyForChat/);
  assert.match(settingsJs, /Ready for chat/);
});
