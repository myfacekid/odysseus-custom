// Structural smoke test for the Links window graph view (Obsidian-style
// force-directed nodes + edges).
//
// Run with:  node --test tests/ui/knowledge-graph-view.test.mjs
//
// The graph itself is canvas/pointer driven and only meaningful in a browser,
// so these assertions guard the wiring: the three panes (graph, preview, list)
// exist in the markup, the layout styles are present, knowledge.js drives the
// view, and the graph module loads and exports its class under Node.

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (...p) => readFileSync(join(repoRoot, ...p), 'utf8');

const html = read('static', 'index.html');
const css = read('static', 'style.css');
const knowledgeJs = read('static', 'js', 'knowledge.js');

test('Links shows graph, preview, and list together (no view toggle)', () => {
  // The List/Graph toggle was removed — all three panes are visible at once.
  assert.ok(!html.includes('kg-view-toggle'), 'view toggle should be gone');
  assert.ok(!html.includes('kg-view-btn'), 'view buttons should be gone');
  const panels = html.slice(
    html.indexOf('class="kg-panels"'),
    html.indexOf('id="kg-node-list"') + 40,
  );
  assert.ok(panels.includes('id="kg-graph"'));
  assert.ok(panels.includes('id="kg-detail"'));
  assert.ok(panels.includes('id="kg-node-list"'));
  // The graph pane is no longer hidden behind a toggle.
  assert.match(html, /id="kg-graph"\s+class="kg-graph"/);
  assert.ok(!/id="kg-graph"\s+class="kg-graph hidden"/.test(html));
});

test('layout: graph top-left, preview below it, list on the full-height right', () => {
  assert.match(css, /\.kg-graph\s*\{\s*grid-column:\s*1;\s*grid-row:\s*1;\s*\}/);
  assert.match(css, /\.kg-detail\s*\{\s*grid-column:\s*1;\s*grid-row:\s*2;\s*\}/);
  assert.match(css, /\.kg-node-list\s*\{\s*grid-column:\s*2;\s*grid-row:\s*1\s*\/\s*span\s*2;\s*\}/);
});

test('graph canvas styles are present', () => {
  for (const sel of ['.kg-graph', '.kg-graph-canvas', '.kg-graph-overlay']) {
    assert.ok(css.includes(sel), `expected style.css to define ${sel}`);
  }
});

test('knowledge.js renders both surfaces without duplicate declarations', () => {
  // Regression guard: a duplicate `let _graphView` (two competing
  // implementations) is a syntax error that would break the whole Links modal.
  const graphViewDecls = knowledgeJs.match(/^\s*let _graphView\b/gm) || [];
  assert.equal(graphViewDecls.length, 1, 'exactly one _graphView declaration');
  const renderGraphDefs = knowledgeJs.match(/^async function _renderGraph\b/gm) || [];
  assert.equal(renderGraphDefs.length, 1, 'exactly one _renderGraph definition');

  assert.match(knowledgeJs, /knowledgeGraphView\.js/);
  // Graph + list are rendered together; the old toggle plumbing is gone.
  assert.match(knowledgeJs, /async function _renderAll\(/);
  assert.ok(!/function _setView\(/.test(knowledgeJs), '_setView should be removed');
  assert.ok(!/_refreshActiveView/.test(knowledgeJs), '_refreshActiveView should be removed');

  // Selecting a node keeps the graph highlight in sync with the detail panel.
  assert.match(knowledgeJs, /_graphView\?\.setSelected/);
  // Graph data comes from the existing /graph endpoint's edge sample.
  assert.match(knowledgeJs, /edges_sample/);
});

test('the graph module loads under Node and exports its class', async () => {
  const mod = await import(join(repoRoot, 'static', 'js', 'knowledgeGraphView.js'));
  assert.equal(typeof mod.KnowledgeGraphView, 'function');
});

test('shared edgeKinds module exposes colour + glyph per kind', async () => {
  const mod = await import(join(repoRoot, 'static', 'js', 'edgeKinds.js'));
  assert.equal(typeof mod.edgeKind, 'function');
  for (const kind of ['relates', 'derives_from', 'supports', 'refutes', 'depends_on']) {
    const kd = mod.edgeKind(kind);
    assert.ok(kd.color && kd.glyph && kd.label, `${kind} needs color/glyph/label`);
  }
  // Unknown kinds fall back rather than throwing.
  assert.ok(mod.edgeKind('nonexistent').color);
});

test('knowledge.js wires the new graph callbacks + interactions', () => {
  for (const hook of ['onOpen:', 'onAddLink:', 'onRemoveLink:', 'onRebuild:']) {
    assert.ok(knowledgeJs.includes(hook), `expected graph view option ${hook}`);
  }
  // Enter-in-search jumps the graph to the first match.
  assert.match(knowledgeJs, /focusSearchMatch/);
  // Idle animation is gated to when the modal is open.
  assert.match(knowledgeJs, /setActive\(true\)/);
  assert.match(knowledgeJs, /setActive\(false\)/);
  // Per-type filter chip counts.
  assert.match(knowledgeJs, /_updateFilterCounts/);
});

test('graph overlay/legend/tooltip/menu styles are present', () => {
  for (const sel of [
    '.kg-graph-legend', '.kg-graph-tooltip', '.kg-graph-menu',
    '.kg-graph-emptystate', '.kg-graph-ctl.active',
  ]) {
    assert.ok(css.includes(sel), `expected style.css to define ${sel}`);
  }
});

test('graph legend is toggleable from the overlay controls', () => {
  const graphJs = read('static', 'js', 'knowledgeGraphView.js');
  assert.match(graphJs, /data-act="legend"/);
  assert.match(graphJs, /_toggleLegend/);
  assert.match(graphJs, /legendVisible/);
});

test('graph legend always shows the complete kind key including refutes', () => {
  const edgeKindsJs = read('static', 'js', 'edgeKinds.js');
  const graphJs = read('static', 'js', 'knowledgeGraphView.js');
  assert.match(edgeKindsJs, /export const LEGEND_EDGE_KINDS/);
  assert.match(edgeKindsJs, /['"]refutes['"]/);
  assert.match(graphJs, /LEGEND_EDGE_KINDS/);
  assert.doesNotMatch(graphJs, /present\.has\(k\)/);
  assert.doesNotMatch(graphJs, /new Set\(this\.edges\.map/);
});

test('document body snippets are hidden from compact Links panes', () => {
  assert.match(knowledgeJs, /function _compactSnippet/);
  assert.match(knowledgeJs, /type === 'document'/);
});

test('research-sourced link reasons collapse to a compact chip', () => {
  assert.match(knowledgeJs, /function _compactLinkReason/);
  assert.match(knowledgeJs, /kg-link-source-chip/);
  assert.match(css, /\.kg-link-source-chip/);
});
