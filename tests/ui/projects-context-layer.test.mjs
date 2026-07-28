// Structural smoke tests for Projects context layer (L1–L4).
//
// Run with:  node --test tests/ui/projects-context-layer.test.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, '..', '..');
const read = (p) => readFileSync(join(repoRoot, p), 'utf8');

const indexHtml = read('static/index.html');
const flagJs = read('static/js/projects/featureFlag.js');
const chipJs = read('static/js/projects/activeChip.js');
const stateJs = read('static/js/projects/activeState.js');
const pickerJs = read('static/js/projects/filePicker.js');
const indexJs = read('static/js/projects/index.js');
const sessionsJs = read('static/js/sessions.js');
const styleCss = read('static/style.css');
const promotePy = read('src/project_promote.py');
const projectRoutes = read('routes/project_routes.py');
const sessionRoutes = read('routes/session_routes.py');

test('L0/L1: workspace shell stays off; context layer on', () => {
  assert.match(flagJs, /PROJECTS_UI_ENABLED\s*=\s*false/);
  assert.match(flagJs, /PROJECTS_CONTEXT_LAYER_ENABLED\s*=\s*true/);
  assert.match(flagJs, /PROJECT_SERVER_DIR_BROWSE_ENABLED\s*=\s*false/);
});

test('L1: active chip markup and module exist', () => {
  assert.ok(indexHtml.includes('id="project-active-chip"'));
  assert.ok(indexHtml.includes('id="project-active-chip-btn"'));
  assert.ok(indexHtml.includes('id="project-active-chip-menu"'));
  assert.ok(chipJs.includes('initActiveProjectChip'));
  assert.ok(chipJs.includes('setActiveProjectFromId'));
  assert.ok(stateJs.includes('ACTIVE_PROJECT_KEY'));
  assert.ok(stateJs.includes('migrateLastOpenToActive'));
  assert.ok(indexJs.includes('initActiveProjectChip'));
  // Chip sits beside the Nobody brand in the sidebar header
  const brandIdx = indexHtml.indexOf('id="sidebar-brand-btn"');
  const chipIdx = indexHtml.indexOf('id="project-active-chip"');
  assert.ok(brandIdx > 0 && chipIdx > brandIdx);
  assert.ok(indexHtml.indexOf('sidebar-header') < brandIdx);
  assert.ok(!indexHtml.includes('project-active-chip-hint'));
  assert.ok(!chipJs.includes('Tools run in project folder'));
  assert.ok(chipJs.includes('_toastProjectScoped'));
  assert.ok(chipJs.includes('Switch projects anytime next to Nobody'));
});

test('L1: chip animations defined with reduced-motion guard', () => {
  assert.ok(styleCss.includes('@keyframes project-chip-enter'));
  assert.ok(styleCss.includes('.project-active-chip-menu.is-slate'));
  assert.ok(styleCss.includes('slate-from-left'));
  assert.ok(styleCss.includes('slate-from-right'));
  assert.ok(styleCss.includes('translateX(-100%)'));
  assert.ok(styleCss.includes('translateX(100%)'));
  assert.ok(styleCss.includes('@keyframes project-chip-slate-in'));
  assert.ok(chipJs.includes('_positionSlate'));
  assert.ok(chipJs.includes('is-slate'));
  assert.ok(chipJs.includes('document.body.appendChild(menu)'));
  assert.ok(styleCss.includes('.project-active-chip'));
  assert.match(styleCss, /prefers-reduced-motion[\s\S]*project-active-chip/);
  // Old left-anchored dropdown-only open motion is gone
  assert.ok(!styleCss.includes('@keyframes project-chip-menu-in'));
});

test('L2: session create accepts project_id; chats filter scope', () => {
  assert.ok(sessionRoutes.includes('project_id: str = Form'));
  assert.ok(sessionsJs.includes("fd.append('project_id'"));
  assert.ok(sessionsJs.includes('setSessionScope'));
  assert.ok(indexHtml.includes('data-scope="project"'));
  assert.ok(indexHtml.includes('data-scope="all"'));
  assert.ok(sessionsJs.includes('session-project-badge'));
});

test('L2: main session list no longer hides project chats', () => {
  // The is_project_workspace_session filter must not gate /api/sessions list
  assert.ok(!sessionRoutes.includes('and not is_project_workspace_session('));
});

test('L4: promote API + UI file picker', () => {
  assert.ok(promotePy.includes('def promote_project_file'));
  assert.ok(projectRoutes.includes('/{project_id}/promote'));
  assert.ok(pickerJs.includes('openProjectFilePicker'));
  assert.ok(pickerJs.includes('library_type'));
  assert.ok(pickerJs.includes('Add to Library'));
});

test('L4: agent tool promote_project_file wired', () => {
  const schema = read('src/tool_schemas.py');
  const exec = read('src/tool_execution.py');
  const policy = read('src/project_tool_policy.py');
  assert.ok(schema.includes('"name": "promote_project_file"'));
  assert.ok(exec.includes('_execute_promote_project_file'));
  assert.ok(policy.includes('promote_project_file'));
});

test('L5: workspace panel remains gated/hidden', () => {
  assert.ok(flagJs.includes("'#project-workspace-panel'"));
  assert.ok(styleCss.includes('body.projects-ui-hidden #project-workspace-panel'));
});

test('F1–F4: project files sheet uses modal-content + tree/reader', () => {
  assert.ok(pickerJs.includes('modal-content project-files-sheet-content'));
  assert.ok(pickerJs.includes('id="project-files-tree"'));
  assert.ok(pickerJs.includes('id="project-files-reader"'));
  assert.ok(pickerJs.includes('project-files-cwd-badge'));
  assert.ok(pickerJs.includes('Project file'));
  assert.ok(pickerJs.includes('contentViewer'));
  assert.ok(pickerJs.includes('createMarkdown') || pickerJs.includes('contentViewer.createMarkdown'));
  assert.ok(styleCss.includes('.project-files-sheet'));
  assert.ok(styleCss.includes('.project-files-sheet-content'));
  assert.ok(styleCss.includes('@keyframes project-files-sheet-in'));
  assert.ok(styleCss.includes('.project-files-cwd-badge'));
  assert.ok(styleCss.includes('var(--project-depth-accent)'));
  assert.match(styleCss, /prefers-reduced-motion[\s\S]*project-files-sheet/);
});

test('F5: Project files is an Explore tool (gated on active project)', () => {
  const appJs = read('static/app.js');
  const registry = read('static/js/nav/toolRegistry.js');
  const indexHtml = read('static/index.html');
  assert.ok(registry.includes("key: 'project-files'"));
  assert.ok(registry.includes("railId: 'rail-project-files'"));
  assert.ok(registry.includes("sidebarId: 'tool-project-files-btn'"));
  assert.ok(registry.includes('requiresActiveProject: true'));
  assert.ok(indexHtml.includes('id="tool-project-files-btn"'));
  assert.ok(appJs.includes('syncProjectFilesToolVisibility'));
  assert.ok(appJs.includes('openProjectFilePicker'));
  assert.ok(appJs.includes('tool-project-files-btn'));
  // Moved off the chip menu into Tools / rail
  assert.ok(!chipJs.includes('Browse project files'));
  assert.ok(!chipJs.includes("data-action=\"files\""));
});
