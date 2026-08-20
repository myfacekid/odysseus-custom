/**
 * Deep Research side panel — open/close, form, job rendering, library.
 */
import * as jobs from './jobs.js';
import * as projectLink from './projectLink.js';
import { openZoteroSaveSheet } from './zoteroSaveSheet.js';
import { makeWindowDraggable } from '../windowDrag.js';
import { snapModalToZone } from '../tileManager.js';
import createResearchSynapse from '../researchSynapse.js';
import spinnerModule from '../spinner.js';
import { sortModelIds } from '../modelSort.js';
import { mountEmptyState, showLoadingRow, showError, ZOTERO_SETUP_MSG } from '../ui/feedback.js';

// jobId -> { synapse, status } — survives across _renderJobs() rebuilds so
// the SVG keeps its accumulated nodes/edges between progress events.
const _jobSynapses = new Map();
// Which foldable job sections ('active' / 'past') the user has collapsed — kept
// across re-renders so the panel doesn't re-expand on every job-state change.
const _collapsedSections = new Set();

// Persisted preference to minimize (hide) the per-job synapse "tree" visual.
// Stored globally so it survives the frequent _renderJobs() card rebuilds and
// applies to every running job.
const _SYNAPSE_MIN_KEY = 'research.synapseMinimized';
// Default to minimized for new users (U6) so a fresh run reads as a background
// job — question + one-line status, not a busy synapse. An explicit user choice
// (stored '0' = expanded) is always respected.
let _synapseMinimized = (() => { try { const v = localStorage.getItem(_SYNAPSE_MIN_KEY); return v === null ? true : v === '1'; } catch { return true; } })();
const _vizCollapseIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg>';
const _vizExpandIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
function _toggleSynapseMinimized() {
  _synapseMinimized = !_synapseMinimized;
  try { localStorage.setItem(_SYNAPSE_MIN_KEY, _synapseMinimized ? '1' : '0'); } catch {}
  // Apply live to all rendered cards without forcing a full rebuild.
  document.querySelectorAll('.research-job-synapse-host')
    .forEach(h => h.classList.toggle('synapse-collapsed', _synapseMinimized));
  document.querySelectorAll('.research-synapse-toggle').forEach(b => {
    b.classList.toggle('active', _synapseMinimized);
    b.title = _synapseMinimized ? 'Show visualization' : 'Minimize visualization';
    b.innerHTML = _synapseMinimized ? _vizExpandIcon : _vizCollapseIcon;
  });
}

/** @type {1|2} */
let _researchStep = 1;
/** @type {{ query: string, settings: object } | null} */
let _pendingPlanLaunch = null;
let _planFetchToken = 0;
let _open = false;

function _planLinesToText(lines) {
  return (lines || []).filter(Boolean).join('\n');
}

function _textToPlanLines(text) {
  return (text || '')
    .split(/[\n,]+/)
    .map(s => s.trim())
    .filter(Boolean);
}

function _setResearchStep(step) {
  _researchStep = step === 2 ? 2 : 1;
  document.querySelectorAll('.research-stepper-item').forEach((el) => {
    const n = parseInt(el.getAttribute('data-step'), 10);
    el.classList.toggle('active', n === _researchStep);
    el.classList.toggle('done', n < _researchStep);
  });
  const compose = document.getElementById('research-step-compose');
  const plan = document.getElementById('research-step-plan');
  const continueBtn = document.getElementById('research-continue-btn');
  const startBtn = document.getElementById('research-start-btn');
  const backBtn = document.getElementById('research-back-btn');
  const addBtn = document.getElementById('research-add-btn');
  const onStep1 = _researchStep === 1;
  if (compose) compose.hidden = !onStep1;
  if (plan) plan.hidden = onStep1;
  // Step 1 → single primary (Continue). Step 2 → Back + Queue + Start.
  if (continueBtn) continueBtn.hidden = !onStep1;
  if (backBtn) backBtn.hidden = onStep1;
  if (startBtn) startBtn.hidden = onStep1;
  if (addBtn) addBtn.hidden = onStep1;
  _updateComposeValidity();
  _updatePlanValidity();
}

/** True when step 1 has the minimum required input to proceed:
 *  topic mode needs a question; papers mode needs at least one seed. */
function _isComposeReady() {
  const tab = _getActiveComposeTab();
  const query = (document.getElementById('research-query')?.value || '').trim();
  if (tab === 'papers') return _seedRefsForApi().length > 0;
  return query.length > 0;
}

/** Gate the Continue button so the user can't advance to the search plan
 *  with an empty question / no seed papers (forced progression). */
function _updateComposeValidity() {
  const btn = document.getElementById('research-continue-btn');
  if (!btn) return;
  const ready = _isComposeReady();
  btn.disabled = !ready;
  btn.title = ready
    ? 'Continue to the search plan'
    : (_getActiveComposeTab() === 'papers'
        ? 'Add at least one seed paper first'
        : 'Enter a research question first');
}

/** Gate Start (and Queue) until the plan has at least one search keyword —
 *  keywords are what actually drive the run, so they're required. */
function _updatePlanValidity() {
  const hasKeywords = (document.getElementById('research-plan-keywords')?.value || '').trim().length > 0;
  const startBtn = document.getElementById('research-start-btn');
  const addBtn = document.getElementById('research-add-btn');
  if (startBtn) {
    startBtn.disabled = !hasKeywords;
    startBtn.title = hasKeywords ? 'Start research' : 'Add at least one search keyword first';
  }
  if (addBtn) addBtn.disabled = !hasKeywords;
}

function _setPlanStatus(kind, message) {
  const el = document.getElementById('research-plan-status');
  if (!el) return;
  el.dataset.status = kind || '';
  el.textContent = message || '';
  el.hidden = !message;
}

function _fillPlanReviewForm(plan) {
  const p = plan || {};
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.value = val ?? '';
  };
  set('research-plan-keywords', _planLinesToText(p.search_keywords));
  set('research-plan-anchors', _planLinesToText(p.anchor_terms));
  set('research-plan-avoid', _planLinesToText(p.avoid_topics));
  set('research-plan-subq', _planLinesToText(p.sub_questions));
  set('research-plan-topics', _planLinesToText(p.key_topics));
  set('research-plan-success', p.success_criteria || '');
  const scopeEl = document.getElementById('research-plan-scope');
  if (scopeEl) scopeEl.value = p.scope || 'balanced';
  // Auto-expand the optional fields if the draft populated any of them, so
  // agent-generated content is never silently hidden inside the disclosure.
  const advanced = document.querySelector('.research-plan-advanced');
  if (advanced) {
    const hasAdvanced = [
      p.anchor_terms, p.avoid_topics, p.sub_questions, p.key_topics,
    ].some((v) => Array.isArray(v) ? v.length : (v && String(v).trim()))
      || (p.success_criteria && String(p.success_criteria).trim());
    advanced.open = !!hasAdvanced;
  }
  _updatePlanValidity();
}

function _readApprovedPlanFromForm() {
  const scopeEl = document.getElementById('research-plan-scope');
  const plan = {
    search_keywords: _textToPlanLines(document.getElementById('research-plan-keywords')?.value),
    scope: scopeEl?.value || 'balanced',
  };
  const anchors = _textToPlanLines(document.getElementById('research-plan-anchors')?.value);
  const avoid = _textToPlanLines(document.getElementById('research-plan-avoid')?.value);
  const subq = _textToPlanLines(document.getElementById('research-plan-subq')?.value);
  const topics = _textToPlanLines(document.getElementById('research-plan-topics')?.value);
  const success = (document.getElementById('research-plan-success')?.value || '').trim();
  if (anchors.length) plan.anchor_terms = anchors;
  if (avoid.length) plan.avoid_topics = avoid;
  if (subq.length) plan.sub_questions = subq;
  if (topics.length) plan.key_topics = topics;
  if (success) plan.success_criteria = success;
  return plan;
}

function _validateComposeStep() {
  const queryEl = document.getElementById('research-query');
  const query = (queryEl?.value || '').trim();
  const tab = _getActiveComposeTab();
  const seeds = _seedRefsForApi();
  const mode = document.getElementById('research-mode')?.value || 'literature_review';
  if (tab === 'papers' && mode === 'compare' && seeds.length < 2) {
    if (typeof uiModule !== 'undefined' && uiModule?.showError) {
      uiModule.showError('Compare mode requires at least 2 seed papers.');
    }
    return null;
  }
  if (tab === 'topic' && !query) {
    queryEl?.focus();
    return null;
  }
  if (tab === 'papers' && !seeds.length && !query) {
    document.getElementById('research-seed-input')?.focus();
    return null;
  }
  _saveSettingsToStorage();
  const settings = _readSettings();
  const label = query || 'Literature synthesis from seed papers';
  return { query: label, settings, queryEl };
}

async function _fetchPlanDraftBackground() {
  if (!_pendingPlanLaunch) return;
  const token = ++_planFetchToken;
  const { query, settings } = _pendingPlanLaunch;
  _setPlanStatus('loading', 'Drafting keyword plan — edit these fields anytime while we generate a starting point.');
  try {
    const planData = await _fetchResearchPlan(query, settings);
    if (token !== _planFetchToken || _researchStep !== 2) return;
    _fillPlanReviewForm(planData.retrieval_plan || {});
    const note = document.getElementById('research-plan-seed-note');
    if (note) {
      const text = planData.seed_note || '';
      note.textContent = text;
      note.hidden = !text;
    }
    if (planData.plan_source === 'fallback') {
      _setPlanStatus(
        'ready',
        'Heuristic draft — the model did not return a full plan. Edit keywords, anchors, and optional fields before starting.'
      );
    } else {
      _setPlanStatus('ready', 'Draft ready — tune keywords, anchors, and exclusions, then start research.');
    }
  } catch (err) {
    if (token !== _planFetchToken || _researchStep !== 2) return;
    _setPlanStatus('error', `${err.message || 'Could not draft plan'} — fill keywords manually or go back.`);
  }
}

function _handleContinue() {
  const v = _validateComposeStep();
  if (!v) return;
  _pendingPlanLaunch = { query: v.query, settings: v.settings };
  _fillPlanReviewForm({});
  const note = document.getElementById('research-plan-seed-note');
  if (note) {
    note.textContent = '';
    note.hidden = true;
  }
  _setResearchStep(2);
  document.getElementById('research-step-plan')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  void _fetchPlanDraftBackground();
}

function _handleBack() {
  _planFetchToken += 1;
  _pendingPlanLaunch = null;
  _setPlanStatus('', '');
  _setResearchStep(1);
}

async function _fetchResearchPlan(query, settings) {
  const body = {
    query,
    mode: settings.mode || 'literature_review',
    include_zotero: settings.include_zotero !== false,
    endpoint_id: settings.endpoint_id,
    model: settings.model,
    seed_papers: settings.seed_papers || [],
  };
  const res = await fetch(`${_apiBase}/api/research/plan`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const txt = await res.text();
    let detail = txt;
    try { detail = JSON.parse(txt).detail || txt; } catch {}
    throw new Error(detail || `Plan request failed (${res.status})`);
  }
  return res.json();
}

function _confirmPlanAndRun() {
  if (!_pendingPlanLaunch || _researchStep !== 2) return;
  const kwEl = document.getElementById('research-plan-keywords');
  if (!(kwEl?.value || '').trim()) {
    _setPlanStatus('error', 'Add at least one search keyword before starting.');
    kwEl?.focus();
    return;
  }
  const { query } = _pendingPlanLaunch;
  const settings = { ..._pendingPlanLaunch.settings, ..._readSettings() };
  const approved = _readApprovedPlanFromForm();
  const queryEl = document.getElementById('research-query');
  _planFetchToken += 1;
  _pendingPlanLaunch = null;
  _setResearchStep(1);
  _setPlanStatus('', '');
  if (queryEl) queryEl.value = '';
  jobs.startJob(query, { ...settings, approved_plan: approved }).catch(() => {
    if (typeof uiModule !== 'undefined' && uiModule?.showError) {
      uiModule.showError('Failed to start research');
    }
    if (queryEl) queryEl.value = query;
  });
}

let _onDocKeydown = null;
let _apiBase = '';
let _endpoints = [];
let _expandedJobId = null;
let _markdownModule = null;
let _sessionModule = null;
const _SETTINGS_KEY = 'nobody-research-settings';

const _SEEDS_KEY = 'nobody-research-seeds';
const _TAB_KEY = 'nobody-research-compose-tab';
/** @type {'topic'|'papers'} */
let _activeComposeTab = 'topic';
/** @type {Array<{zotero_key:string,title:string,authors?:string,year?:string,has_pdf?:boolean,doi?:string}>} */
let _seedPapers = [];
let _seedPreviewTimer = null;
let _seedPreviewRequest = 0;
let _seedSearchTimer = null;
let _seedSearchRequest = 0;
let _seedPickerOpen = false;
/** Papers currently rendered in the picker (for keyboard nav / toggle). */
let _seedResultPapers = [];
let _seedActiveIdx = -1;

const _SEED_TIER_CLASS = {
  adequate: 'tier-adequate',
  abstract_only: 'tier-abstract',
  metadata_only: 'tier-thin',
  retrieval_failed: 'tier-thin',
  unsourced: 'tier-thin',
  unknown: 'tier-unknown',
};

function _loadSeedsFromStorage() {
  try {
    const raw = localStorage.getItem(_SEEDS_KEY);
    _seedPapers = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(_seedPapers)) _seedPapers = [];
  } catch { _seedPapers = []; }
}

function _saveSeedsToStorage() {
  try { localStorage.setItem(_SEEDS_KEY, JSON.stringify(_seedPapers)); } catch {}
}

/** First author's short form for a compact chip label (e.g. "Smith et al."). */
function _shortAuthors(authors) {
  const raw = (authors || '').trim();
  if (!raw) return '';
  const first = raw.split(/;|,| and | & /i)[0].trim();
  if (!first) return '';
  const surname = first.split(/\s+/).pop() || first;
  return /;| and | & |,/.test(raw) ? `${surname} et al.` : surname;
}

function _renderSeedChips() {
  _updateComposeValidity();
  _updateSeedMetaUI();
  const host = document.getElementById('research-seed-chips');
  if (!host) return;
  if (!_seedPapers.length) {
    host.innerHTML = `<div class="research-seed-empty">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"></path><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"></path></svg>
      <span>No seed papers yet. Search below to anchor the review on specific work.</span>
    </div>`;
    return;
  }
  host.innerHTML = _seedPapers.map((p, idx) => {
    const meta = [_shortAuthors(p.authors), p.year].filter(Boolean).join(' · ');
    const pdfTitle = p.has_pdf ? 'Full text (PDF) available' : 'No PDF — abstract/metadata only';
    const pdfCls = p.has_pdf ? 'research-seed-chip-dot--pdf' : 'research-seed-chip-dot--nopdf';
    return `<div class="research-seed-chip" data-idx="${idx}" title="${_esc(p.title || p.zotero_key || 'Paper')}">
      <span class="research-seed-chip-dot ${pdfCls}" title="${_esc(pdfTitle)}"></span>
      <div class="research-seed-chip-text">
        <div class="research-seed-chip-title">${_esc(p.title || p.zotero_key || 'Paper')}</div>
        ${meta ? `<div class="research-seed-chip-meta">${_esc(meta)}</div>` : ''}
      </div>
      <button type="button" class="research-seed-chip-remove" data-idx="${idx}" title="Remove" aria-label="Remove seed paper">×</button>
    </div>`;
  }).join('');
  host.querySelectorAll('.research-seed-chip-remove').forEach(btn => {
    btn.addEventListener('click', () => {
      const i = parseInt(btn.getAttribute('data-idx') || '-1', 10);
      if (i >= 0) {
        _seedPapers.splice(i, 1);
        _saveSeedsToStorage();
        _renderSeedChips();
        _scheduleSeedPreview();
        _refreshSeedResultStates();
      }
    });
  });
}

/** Sync the count pill, Clear-all button, compose-tab badge, and compare hint. */
function _updateSeedMetaUI() {
  const n = _seedPapers.length;
  const countEl = document.getElementById('research-seed-count');
  if (countEl) {
    countEl.textContent = n ? `${n} selected` : '';
    countEl.hidden = !n;
  }
  const clearEl = document.getElementById('research-seed-clear');
  if (clearEl) clearEl.hidden = n < 1;

  const mode = document.getElementById('research-mode')?.value || 'literature_review';
  const hintEl = document.getElementById('research-seed-input-hint');
  if (hintEl && mode === 'compare' && n < 2 && !hintEl.classList.contains('research-seed-input-hint--error')) {
    hintEl.textContent = `Compare mode needs at least 2 papers — add ${2 - n} more.`;
    hintEl.classList.add('research-seed-input-hint--compare');
  } else if (hintEl && hintEl.classList.contains('research-seed-input-hint--compare')) {
    hintEl.textContent = '';
    hintEl.classList.remove('research-seed-input-hint--compare');
  }

  const tabBadge = document.querySelector('.research-compose-tab[data-tab="papers"] .research-compose-tab-badge');
  if (tabBadge) {
    tabBadge.textContent = n ? String(n) : '';
    tabBadge.hidden = !n;
  }
}

function _clearAllSeeds() {
  if (!_seedPapers.length) return;
  _seedPapers = [];
  _saveSeedsToStorage();
  _renderSeedChips();
  _scheduleSeedPreview();
  _refreshSeedResultStates();
}

/** True if the given paper (by Zotero key or DOI) is already a seed. */
function _isSeedSelected(paper) {
  const key = (paper.zotero_key || paper.key || '').trim().toUpperCase();
  const doi = (paper.doi || '').trim();
  return _seedPapers.some(s => (key && (s.zotero_key || '').toUpperCase() === key) || (doi && s.doi === doi));
}

function _addSeedPaper(paper) {
  const key = (paper.zotero_key || paper.key || '').trim().toUpperCase();
  const doi = (paper.doi || '').trim();
  const id = key || doi;
  if (!id) return false;
  if (_isSeedSelected(paper)) return false;
  _seedPapers.push({
    zotero_key: key || id,
    title: paper.title || key || doi,
    authors: paper.authors || '',
    year: paper.year || '',
    has_pdf: !!paper.has_pdf,
    doi: doi || '',
  });
  _saveSeedsToStorage();
  _renderSeedChips();
  _scheduleSeedPreview();
  return true;
}

/** Remove a seed matching the given paper; returns true if one was removed. */
function _removeSeedPaper(paper) {
  const key = (paper.zotero_key || paper.key || '').trim().toUpperCase();
  const doi = (paper.doi || '').trim();
  const before = _seedPapers.length;
  _seedPapers = _seedPapers.filter(s =>
    !((key && (s.zotero_key || '').toUpperCase() === key) || (doi && s.doi === doi)));
  if (_seedPapers.length === before) return false;
  _saveSeedsToStorage();
  _renderSeedChips();
  _scheduleSeedPreview();
  return true;
}

function _extractDoiFromText(text) {
  const raw = (text || '').trim();
  if (!raw) return '';
  const lower = raw.toLowerCase();
  for (const prefix of ['https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'http://dx.doi.org/']) {
    if (lower.startsWith(prefix)) {
      return raw.slice(prefix.length).split(/[\s?#]/)[0].replace(/[.,;)]+$/, '');
    }
  }
  if (/^10\.\d/.test(raw) && raw.includes('/')) return raw.split(/\s/)[0].replace(/[.,;)]+$/, '');
  return '';
}

function _parseSeedInput(raw) {
  const s = (raw || '').trim();
  if (!s) return { ok: false, error: 'Enter a Zotero key or DOI' };

  const doiFromUrl = _extractDoiFromText(s);
  if (doiFromUrl) {
    return { ok: true, paper: { doi: doiFromUrl, zotero_key: doiFromUrl, title: `DOI ${doiFromUrl}` } };
  }

  if (/^paper:/i.test(s)) {
    const key = s.replace(/^paper:/i, '').trim().toUpperCase();
    if (/^[A-Z0-9]{8}$/.test(key)) return { ok: true, paper: { zotero_key: key, title: key } };
    return { ok: false, error: 'Invalid paper:KEY — use an 8-character Zotero key' };
  }

  if (/^doi:/i.test(s)) {
    const d = s.replace(/^doi:/i, '').trim();
    if (/^10\.\d/i.test(d)) return { ok: true, paper: { doi: d, zotero_key: d, title: `DOI ${d}` } };
    return { ok: false, error: 'Invalid DOI after doi: prefix' };
  }

  if (/^10\.\d/i.test(s)) {
    const d = s.split(/\s/)[0].replace(/[.,;)]+$/, '');
    return { ok: true, paper: { doi: d, zotero_key: d, title: `DOI ${d}` } };
  }

  const key = s.toUpperCase();
  if (/^[A-Z0-9]{8}$/.test(key)) return { ok: true, paper: { zotero_key: key, title: key } };

  return {
    ok: false,
    error: 'Unrecognized format — use an 8-character Zotero key, bare DOI, paper:KEY, or doi.org link',
  };
}

function _setSeedInputHint(message, isError) {
  const hint = document.getElementById('research-seed-input-hint');
  if (!hint) return;
  hint.textContent = message || '';
  hint.classList.toggle('research-seed-input-hint--error', !!isError && !!message);
}

function _scheduleSeedPreview() {
  clearTimeout(_seedPreviewTimer);
  _seedPreviewTimer = setTimeout(() => { void _refreshSeedPreview(); }, 350);
}

async function _refreshSeedPreview() {
  const host = document.getElementById('research-seed-preview');
  if (!host) return;
  if (!_seedPapers.length) {
    host.innerHTML = '';
    host.hidden = true;
    return;
  }
  host.hidden = false;
  host.innerHTML = '<div class="research-seed-preview-loading">Checking seed sources…</div>';
  const reqId = ++_seedPreviewRequest;
  const refs = _seedRefsForApi();
  try {
    const res = await fetch(`${_apiBase}/api/research/seeds/preview`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refs }),
    });
    if (!res.ok) throw new Error('Preview unavailable');
    const data = await res.json();
    if (reqId !== _seedPreviewRequest) return;
    const seeds = data.seeds || [];
    if (!seeds.length) {
      host.innerHTML = '<div class="research-seed-preview-empty">No preview — seeds will resolve when the run starts.</div>';
      return;
    }
    const syncBanner = data.sync_recommended
      ? '<div class="research-seed-sync-hint">Some seed PDF flags look stale vs Zotero — sync your catalog in Settings → Search.</div>'
      : '';
    host.innerHTML = `${syncBanner}<div class="research-seed-preview-heading">Before you run</div>
      <ul class="research-seed-preview-list">${seeds.map((s) => {
        const tierCls = _SEED_TIER_CLASS[s.sourcing_tier] || 'tier-unknown';
        const col = (s.collection_paths || []).slice(0, 2).join(', ');
        const bits = [
          s.doi ? `DOI ${s.doi}` : '',
          col ? col : '',
          s.live_has_pdf === true ? 'PDF on Zotero' : (s.has_pdf ? 'PDF in library' : ''),
        ].filter(Boolean);
        return `<li class="research-seed-preview-item">
          <div class="research-seed-preview-title">${_esc(s.title || s.ref || 'Paper')}</div>
          <div class="research-seed-preview-meta">${_esc(bits.join(' · ') || 'No catalog metadata')}</div>
          <span class="research-seed-preview-tier ${tierCls}">${_esc(s.sourcing_label || s.sourcing_tier || 'Unknown')}</span>
          ${s.in_catalog === false ? '<span class="research-seed-preview-note">Not in catalog — sync Zotero or resolves at run</span>' : ''}
          ${s.catalog_stale ? '<span class="research-seed-preview-note research-seed-preview-note--sync">Catalog out of date — sync Zotero in Settings</span>' : ''}
        </li>`;
      }).join('')}</ul>`;
  } catch {
    if (reqId !== _seedPreviewRequest) return;
    host.innerHTML = '<div class="research-seed-preview-empty">Could not load preview — seeds still run normally.</div>';
  }
}

/** Add a paper to Deep Research seeds and focus the Papers compose tab. */
export function addSeedPaper(paper) {
  const added = _addSeedPaper(paper);
  if (!_open) {
    openPanel();
  } else {
    const overlay = document.getElementById('research-overlay');
    if (overlay && overlay.style.display === 'none') {
      overlay.style.display = '';
      document.getElementById('tool-research-btn')?.classList.remove('minimized');
    }
  }
  _switchComposeTab('papers');
  _renderSeedChips();
  _scheduleSeedPreview();
  return added;
}

function _openSeedPicker() {
  const picker = document.getElementById('research-seed-picker');
  const input = document.getElementById('research-seed-input');
  if (!picker) return;
  _seedPickerOpen = true;
  picker.hidden = false;
  picker.classList.add('research-seed-picker--open');
  input?.setAttribute('aria-expanded', 'true');
  void _runSeedSearch((input?.value || '').trim());
}

function _closeSeedPicker() {
  const picker = document.getElementById('research-seed-picker');
  const input = document.getElementById('research-seed-input');
  if (!picker) return;
  _seedPickerOpen = false;
  picker.classList.remove('research-seed-picker--open');
  picker.hidden = true;
  _seedActiveIdx = -1;
  input?.setAttribute('aria-expanded', 'false');
}

function _scheduleSeedSearch(q) {
  clearTimeout(_seedSearchTimer);
  _seedSearchTimer = setTimeout(() => { void _runSeedSearch(q); }, 220);
}

async function _runSeedSearch(query) {
  const picker = document.getElementById('research-seed-picker');
  if (!picker || !_seedPickerOpen) return;
  const q = (query || '').trim();
  const reqId = ++_seedSearchRequest;
  const parsed = _parseSeedInput(q);
  const canAddExternal = parsed.ok && !!q;

  if (!picker.querySelector('.research-seed-picker-list')) {
    picker.innerHTML = '<div class="research-seed-picker-loading">Searching your library…</div>';
  }
  try {
    const url = `${_apiBase}/api/research/papers?limit=30${q ? `&search=${encodeURIComponent(q)}` : ''}`;
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) throw new Error('Failed to load papers');
    const data = await res.json();
    if (reqId !== _seedSearchRequest || !_seedPickerOpen) return;
    const papers = data.papers || [];
    if (!papers.length && !q) {
      mountEmptyState(picker, {
        kind: 'setup',
        title: 'Setup needed',
        message: ZOTERO_SETUP_MSG,
        actionLabel: 'Fix',
        actionTab: 'search',
      });
      return;
    }
    _renderSeedResults(papers, { query: q, canAddExternal, parsed });
  } catch (e) {
    if (reqId !== _seedSearchRequest) return;
    showError(picker, {
      message: e.message || 'Could not search papers',
      retry: () => { void _runSeedSearch(q); },
    });
  }
}

function _seedResultCardHtml(p, idx, selected) {
  const meta = [p.authors, p.year].filter(Boolean).join(' · ');
  const col = (p.collection_paths || []).slice(0, 1)[0] || '';
  return `<button type="button" class="research-seed-picker-item research-seed-picker-card${selected ? ' is-selected' : ''}"
    role="option" aria-selected="${selected ? 'true' : 'false'}" data-idx="${idx}"
    data-key="${_esc(p.zotero_key)}" data-title="${_esc(p.title)}" data-authors="${_esc(p.authors)}"
    data-year="${_esc(p.year)}" data-doi="${_esc(p.doi)}" data-pdf="${p.has_pdf ? '1' : '0'}">
    <span class="research-seed-picker-check" aria-hidden="true">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
    </span>
    <div class="research-seed-picker-card-body">
      <span class="research-seed-picker-title">${_esc(p.title || p.zotero_key || 'Untitled')}</span>
      ${meta ? `<span class="research-seed-picker-meta">${_esc(meta)}</span>` : ''}
      ${col ? `<span class="research-seed-picker-col">${_esc(col)}</span>` : ''}
    </div>
    ${p.has_pdf ? '<span class="research-seed-picker-badge">PDF</span>' : ''}
  </button>`;
}

function _renderSeedResults(papers, opts) {
  const picker = document.getElementById('research-seed-picker');
  if (!picker) return;
  const { query, canAddExternal, parsed } = opts || {};
  _seedResultPapers = papers;
  _seedActiveIdx = -1;

  const externalHtml = canAddExternal
    ? `<button type="button" class="research-seed-picker-external" data-external="1"
        data-key="${_esc(parsed.paper.zotero_key || '')}" data-doi="${_esc(parsed.paper.doi || '')}"
        data-title="${_esc(parsed.paper.title || '')}">
        <span class="research-seed-picker-external-icon">+</span>
        <span>Add <strong>${_esc(parsed.paper.doi ? `DOI ${parsed.paper.doi}` : parsed.paper.zotero_key)}</strong> directly</span>
      </button>`
    : '';

  let listHtml;
  if (papers.length) {
    listHtml = `<div class="research-seed-picker-list" role="listbox">${
      papers.map((p, i) => _seedResultCardHtml(p, i, _isSeedSelected(p))).join('')
    }</div>`;
  } else {
    listHtml = `<div class="research-seed-picker-empty">${
      query ? `No library matches for “${_esc(query)}”.` : 'Your library looks empty.'
    }${canAddExternal ? ' Use the option above to add it by reference.' : ''}</div>`;
  }

  picker.innerHTML = `${externalHtml}${listHtml}
    <div class="research-seed-picker-footer">
      <span class="research-seed-picker-hint">Click to add or remove · Esc to close</span>
      <button type="button" class="research-seed-picker-done" data-done="1">Done</button>
    </div>`;
  _wireSeedResultEvents(picker);
}

function _wireSeedResultEvents(picker) {
  picker.querySelector('[data-done]')?.addEventListener('click', () => {
    _closeSeedPicker();
    document.getElementById('research-seed-input')?.focus();
  });
  picker.querySelector('[data-external]')?.addEventListener('click', (e) => {
    const el = e.currentTarget;
    const paper = {
      zotero_key: el.getAttribute('data-key'),
      doi: el.getAttribute('data-doi'),
      title: el.getAttribute('data-title'),
    };
    if (_addSeedPaper(paper)) {
      const input = document.getElementById('research-seed-input');
      if (input) input.value = '';
      _setSeedInputHint('');
      void _runSeedSearch('');
    } else {
      window.uiModule?.showToast?.('Already in seed list', 2500);
    }
  });
  picker.querySelectorAll('.research-seed-picker-card').forEach(btn => {
    btn.addEventListener('click', () => _toggleSeedFromCard(btn));
  });
}

function _paperFromCard(btn) {
  return {
    zotero_key: btn.getAttribute('data-key'),
    title: btn.getAttribute('data-title'),
    authors: btn.getAttribute('data-authors'),
    year: btn.getAttribute('data-year'),
    doi: btn.getAttribute('data-doi'),
    has_pdf: btn.getAttribute('data-pdf') === '1',
  };
}

function _toggleSeedFromCard(btn) {
  const paper = _paperFromCard(btn);
  if (_isSeedSelected(paper)) {
    _removeSeedPaper(paper);
  } else {
    _addSeedPaper(paper);
    btn.classList.add('research-seed-picker-card--justadded');
    setTimeout(() => btn.classList.remove('research-seed-picker-card--justadded'), 420);
  }
  _refreshSeedResultStates();
}

/** Update selected styling in the open picker without a full re-render. */
function _refreshSeedResultStates() {
  const picker = document.getElementById('research-seed-picker');
  if (!picker || picker.hidden) return;
  picker.querySelectorAll('.research-seed-picker-card').forEach(btn => {
    const selected = _isSeedSelected(_paperFromCard(btn));
    btn.classList.toggle('is-selected', selected);
    btn.setAttribute('aria-selected', selected ? 'true' : 'false');
  });
}

function _setSeedActive(idx) {
  const picker = document.getElementById('research-seed-picker');
  if (!picker) return;
  const cards = Array.from(picker.querySelectorAll('.research-seed-picker-card'));
  if (!cards.length) return;
  _seedActiveIdx = ((idx % cards.length) + cards.length) % cards.length;
  cards.forEach((c, i) => c.classList.toggle('is-active', i === _seedActiveIdx));
  cards[_seedActiveIdx]?.scrollIntoView({ block: 'nearest' });
}

function _seedRefsForApi() {
  return _seedPapers.map(p => p.zotero_key || p.doi).filter(Boolean);
}

function _getActiveComposeTab() {
  return _activeComposeTab === 'papers' ? 'papers' : 'topic';
}

function _switchComposeTab(tab) {
  const next = tab === 'papers' ? 'papers' : 'topic';
  _activeComposeTab = next;
  try { localStorage.setItem(_TAB_KEY, next); } catch {}

  document.querySelectorAll('.research-compose-tab').forEach(btn => {
    const active = btn.getAttribute('data-tab') === next;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  const topicPane = document.getElementById('research-pane-topic');
  const papersPane = document.getElementById('research-pane-papers');
  if (topicPane) topicPane.hidden = next !== 'topic';
  if (papersPane) papersPane.hidden = next !== 'papers';
  if (next !== 'papers' && _seedPickerOpen) _closeSeedPicker();

  projectLink.updateProjectPickerVisibility();
  const queryEl = document.getElementById('research-query');
  if (queryEl) {
    queryEl.placeholder = next === 'papers'
      ? 'Optional — e.g. focus on mechanisms, clinical outcomes, or methods…'
      : 'e.g. What is the evidence for intermittent fasting on cardiovascular outcomes in adults? Include RCTs and systematic reviews.';
  }
  _updateComposeValidity();
}

function _saveSettingsToStorage() {
  try {
    const preprintsEl = document.getElementById('research-include-preprints');
    const zoteroEl = document.getElementById('research-include-zotero');
    const knowledgeEl = document.getElementById('research-include-knowledge');
    const modeEl = document.getElementById('research-mode');
    const lengthEl = document.getElementById('research-report-length');
    const projectEl = document.getElementById('research-project-id');
    localStorage.setItem(_SETTINGS_KEY, JSON.stringify({
      max_rounds: document.getElementById('research-rounds')?.value || '0',
      search_provider: document.getElementById('research-search-provider')?.value || '',
      endpoint_id: document.getElementById('research-endpoint')?.value || '',
      model: document.getElementById('research-model')?.value || '',
      include_preprints: preprintsEl ? !!preprintsEl.checked : true,
      include_zotero: zoteroEl ? !!zoteroEl.checked : true,
      include_knowledge: knowledgeEl ? !!knowledgeEl.checked : true,
      mode: modeEl?.value || 'literature_review',
      report_length: lengthEl?.value || 'standard',
      project_id: projectEl?.value || '',
      compose_tab: _getActiveComposeTab(),
    }));
  } catch {}
}

function _loadSettingsFromStorage() {
  try {
    const raw = localStorage.getItem(_SETTINGS_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch { return null; }
}

function _showBadge() {
  const btn = document.getElementById('tool-research-btn');
  if (!btn || btn.querySelector('.research-badge')) return;
  const dot = document.createElement('span');
  dot.className = 'research-badge';
  btn.appendChild(dot);
}

function _clearBadge() {
  const dot = document.querySelector('#tool-research-btn .research-badge');
  if (dot) dot.remove();
}

// Live sidebar/rail feedback — mirrors the cookbook pattern. While
// research jobs are running, the rail button pulses; errors flag red;
// nothing running clears it. Panel-independent so it works with the
// modal closed. Called from _renderJobs on every job-state change.
function _syncResearchRail() {
  let running = 0, errored = 0, runningJob = null;
  try {
    for (const j of jobs.getJobs()) {
      if (j.status === 'running' || j.status === 'queued') {
        running++;
        if (j.status === 'running' && !runningJob) runningJob = j;
      } else if (j.status === 'error') errored++;
    }
  } catch { return; }
  const railBtn = document.getElementById('rail-research');
  const toolBtn = document.getElementById('tool-research-btn');
  const active = running > 0 || errored > 0;
  // Shared flag so sessions.js:_updateRailNotifs (which lights the same
  // rail button for INLINE research mode) ORs with us instead of
  // clobbering — otherwise a session re-render would clear our dot.
  window._researchJobsActive = active;
  if (railBtn) {
    railBtn.classList.remove('rail-notify', 'rail-notify-success', 'rail-notify-error', 'research-notif-active');
    if (active) {
      railBtn.classList.add('rail-notify', errored ? 'rail-notify-error' : 'rail-notify-success', 'research-notif-active');
    }
  }
  if (toolBtn) {
    toolBtn.classList.toggle('research-notif-active', active);
    toolBtn.style.opacity = active ? '1' : '';
    // Sidebar feedback while running — a small pulsing dot + round text,
    // same style as Cookbook's running indicator (no glow).
    let wrap = toolBtn.querySelector('.research-sb-running');
    if (running > 0) {
      if (!wrap) {
        wrap = document.createElement('span');
        wrap.className = 'research-sb-running';
        wrap.innerHTML = '<span class="research-sb-status"></span><span class="research-sb-dot"></span>';
        toolBtn.appendChild(wrap);
      }
      const round = runningJob && runningJob.progress && runningJob.progress.round;
      // Just the round as "R1", "R2", … (empty until the first round lands).
      // Only update when we actually have a round — don't blank it out on
      // progress ticks that lack one, or it flickers on/off between rounds.
      if (round) wrap.querySelector('.research-sb-status').textContent = `R${round}`;
    } else if (wrap) {
      wrap.remove();
    }
  }
  if (window._syncRailDynamic) window._syncRailDynamic();
}

/** Fetch the count of saved research items and populate the header chip. */
async function _updateResearchCount() {
  const el = document.getElementById('research-stats');
  if (!el) return;
  try {
    const res = await fetch('/api/research/library?limit=1', { credentials: 'same-origin' });
    if (!res.ok) return;
    const data = await res.json();
    const n = data.total || 0;
    el.textContent = n + (n === 1 ? ' research' : ' research');
  } catch {}
}

const _searchIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/></svg>';
const _closeIcon = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
const _playIcon = '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5,3 19,12 5,21"/></svg>';
const _arrowLeftIcon = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/></svg>';
const _plusIcon = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>';
const _bookmarkIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>';
const _folderPlusIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="12" y1="11" x2="12" y2="17"/><line x1="9" y1="14" x2="15" y2="14"/></svg>';
const _linkIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>';
const _cancelIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
const _trashIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>';
const _externalIcon = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>';
const _copyIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/></svg>';
const _retryIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/></svg>';
const _chevronIcon = '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
const _editIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>';
const _chatIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';
const _exportIcon = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';

let _researchExportMenu = null;

export function init(apiBase, markdownMod, sessionMod) {
  _apiBase = apiBase;
  _markdownModule = markdownMod;
  _sessionModule = sessionMod;
  jobs.init(apiBase);
  jobs.setRenderCallback(_renderJobs);
  jobs.onComplete((job) => {
    if (!_open) _showBadge();
    void projectLink.suggestLinkAfterComplete(job, _apiBase);
  });
}

export function isOpen() { return _open; }
export function toggle() {
  if (_open) {
    // If minimized, restore instead of closing
    const overlay = document.getElementById('research-overlay');
    if (overlay && overlay.style.display === 'none') {
      overlay.style.display = '';
      const btn = document.getElementById('tool-research-btn');
      if (btn) btn.classList.remove('minimized');
      return;
    }
    closePanel();
  } else {
    openPanel();
  }
}

export function openPanel(focusJobId) {
  if (_open) {
    const overlay = document.getElementById('research-overlay');
    if (overlay && overlay.style.display === 'none') {
      overlay.style.display = '';
      const btn = document.getElementById('tool-research-btn');
      if (btn) btn.classList.remove('minimized');
    }
    document.body.classList.add('research-panel-view');
    if (focusJobId) _focusJob(focusJobId);
    return;
  }
  _open = true;

  const container = document.getElementById('chat-container');
  if (!container) return;

  import('../tourHints.js').then((m) => m.maybeNavHint?.('libraryVsResearch')).catch(() => {});

  document.body.classList.add('research-panel-view');
  const btn = document.getElementById('tool-research-btn');
  if (btn) btn.classList.add('active');

  const overlay = document.createElement('div');
  overlay.id = 'research-overlay';
  overlay.className = 'modal research-overlay';

  // Match doclib/gallery/calendar modal sizing exactly so research feels like
  // the rest of the modal family (centered, ~640px, 85vh).
  const pane = document.createElement('div');
  pane.id = 'research-pane';
  pane.className = 'modal-content doclib-modal-content research-pane';
  // Mobile: full-screen so the content has room and the jobs list can scroll
  // inside it. Desktop: centered ~640px / 85vh modal like the rest.
  pane.style.cssText = (window.innerWidth <= 768)
    ? 'width:100vw;max-width:100vw;height:90dvh;max-height:90dvh;border-radius:2px 2px 0 0;background:var(--bg);'
    : 'width:min(640px, 92vw);max-height:85vh;background:var(--bg);';
  pane.innerHTML = _buildPanelHTML();

  overlay.appendChild(pane);
  document.body.appendChild(overlay);

  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) closePanel();
  });

  // Document-level ESC handler — overlay-only listener never fired because
  // overlay isn't focused. Tracked in module scope so closePanel can detach.
  _onDocKeydown = (e) => {
    if (e.key === 'Escape' && _open) {
      e.preventDefault();
      closePanel();
    }
  };
  document.addEventListener('keydown', _onDocKeydown);

  // Desktop: shared window drag + edge dock + tile snap (parity with notes/docs).
  const paneHeader = pane.querySelector('.research-pane-header');
  if (paneHeader && window.innerWidth > 768) {
    overlay.setAttribute('data-tile-window', '1');
    makeWindowDraggable(overlay, {
      content: pane,
      header: paneHeader,
      enableDock: true,
      enableLeftDock: true,
      onEnterFullscreen: () => snapModalToZone(overlay, { name: 'fullscreen' }),
      onExitFullscreen: (cx, cy) => {
        const w = pane.offsetWidth || 640;
        const h = pane.offsetHeight || 480;
        pane.style.position = 'fixed';
        pane.style.left = `${Math.max(0, (cx || window.innerWidth / 2) - w / 2)}px`;
        pane.style.top = `${Math.max(0, (cy || 80) - 24)}px`;
        pane.style.width = `${w}px`;
        pane.style.height = `${h}px`;
        pane.style.right = 'auto';
        pane.style.bottom = 'auto';
        pane.style.maxWidth = 'none';
        pane.style.transform = 'none';
      },
    });
  }

  _wireEvents(pane);
  _loadEndpoints().then(_restoreSavedSettings);
  _clearBadge();
  _updateResearchCount();

  if ('Notification' in window && Notification.permission === 'default') {
    try { Notification.requestPermission(); } catch {}
  }

  if (focusJobId) _focusJob(focusJobId);
}

// Scroll to + highlight a research job card by session id. Used by the
// chat anchor-link delegate ([Topic](#research-<session_id>)).
function _focusJob(jobId) {
  if (!jobId) return;
  // jobs may still be loading from /api/research/active — retry a few times.
  let tries = 0;
  const tryFocus = () => {
    const card = document.querySelector(`[data-job-id="${jobId}"]`);
    if (card) {
      card.scrollIntoView({ behavior: 'smooth', block: 'center' });
      card.classList.add('research-card-flash');
      setTimeout(() => card.classList.remove('research-card-flash'), 2000);
      return;
    }
    if (tries++ < 8) setTimeout(tryFocus, 400);
  };
  setTimeout(tryFocus, 200);
}

export function closePanel() {
  if (!_open) return;
  _open = false;

  if (_onDocKeydown) {
    document.removeEventListener('keydown', _onDocKeydown);
    _onDocKeydown = null;
  }

  document.body.classList.remove('research-panel-view');
  const btn = document.getElementById('tool-research-btn');
  if (btn) btn.classList.remove('active');

  const overlay = document.getElementById('research-overlay');
  if (overlay) overlay.remove();
}

function _buildPanelHTML() {
  const searchProviders = ['', 'searxng', 'duckduckgo', 'tavily', 'brave', 'google', 'serper'];
  const providerOpts = searchProviders.map(p =>
    `<option value="${p}">${p || 'Default'}</option>`
  ).join('');

  let roundOpts = '<option value="0" selected>Auto</option>';
  for (let i = 1; i <= 20; i++) {
    roundOpts += `<option value="${i}">${i}</option>`;
  }

  return `
    <div class="modal-header research-pane-header">
      <h4><span style="position:relative;top:-1px;left:6px;display:inline-flex;vertical-align:middle;">${_searchIcon}</span><span style="margin-left:6px;">Research</span></h4>
      <div class="research-pane-header-actions">
        <button id="research-panel-minimize" class="modal-minimize-btn" type="button" title="Minimize"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="5" y1="18" x2="19" y2="18"/></svg></button>
        <button id="research-panel-close" class="close-btn" title="Close">&#x2716;</button>
      </div>
    </div>
    <div class="modal-body research-pane-body" data-no-swipe-dismiss>
      <div class="research-new-job">
        <div class="research-new-job-head">
          <h2 style="margin:0;padding:0;line-height:1;">Research <span id="research-stats" class="memory-count" style="font-size:0.6em;opacity:0.6;font-weight:normal"></span></h2>
        </div>
        <div id="research-no-past-hint" class="memory-desc doclib-desc" style="display:none;margin-top:-2px;font-size:11px;opacity:0.7;">Past reports in <button type="button" class="research-library-link">Library → Research</button></div>
        <nav class="research-stepper" aria-label="Research steps">
          <div class="research-stepper-item active" data-step="1">
            <span class="research-stepper-dot"></span>
            <span class="research-stepper-label">Question &amp; sources</span>
          </div>
          <div class="research-stepper-item" data-step="2">
            <span class="research-stepper-dot"></span>
            <span class="research-stepper-label">Search plan</span>
          </div>
        </nav>
        <div id="research-step-compose" class="research-wizard-pane">
        <div class="research-compose-tabs" role="tablist" aria-label="Research type">
          <button type="button" class="research-compose-tab active" data-tab="topic" role="tab" aria-selected="true">Topic</button>
          <button type="button" class="research-compose-tab" data-tab="papers" role="tab" aria-selected="false">From papers<span class="research-compose-tab-badge" hidden></span></button>
        </div>
        <textarea id="research-query" class="research-query" placeholder="e.g. What is the evidence for intermittent fasting on cardiovascular outcomes in adults? Include RCTs and systematic reviews." rows="4"></textarea>
        <div class="research-source-toggles" id="research-source-toggles">
          <span class="research-source-toggles-label">Sources</span>
          <label class="research-source-pill" title="When off, preprint hosts (arXiv, bioRxiv, medRxiv) are filtered from academic engine results">
            <input type="checkbox" id="research-include-preprints" checked>
            <span>Preprints</span>
          </label>
          <label class="research-source-pill" title="Keyword search on your synced Zotero catalog">
            <input type="checkbox" id="research-include-zotero" checked>
            <span>Zotero</span>
          </label>
          <label class="research-source-pill" title="Papers and documents from Links">
            <input type="checkbox" id="research-include-knowledge" checked>
            <span>Links</span>
          </label>
          <label class="research-setting research-length-inline">
            <span class="research-setting-label">Report length</span>
            <select id="research-report-length">
              <option value="standard">Standard (~1200 words)</option>
              <option value="extended">Extended (3000+ words)</option>
            </select>
          </label>
        </div>
        <div id="research-pane-papers" class="research-compose-pane" hidden>
          <label class="research-setting research-mode-setting">
            <span class="research-setting-label">Mode</span>
            <select id="research-mode">
              <option value="literature_review">Literature review</option>
              <option value="similar_papers">Similar papers</option>
              <option value="gap_analysis">Gap analysis</option>
              <option value="compare">Compare (2+ papers)</option>
            </select>
          </label>
          <label class="research-setting research-project-setting" id="research-project-setting-wrap" hidden>
            <span class="research-setting-label">Link to project</span>
            <select id="research-project-id">
              <option value="">None — decide after research</option>
            </select>
            <span class="research-project-hint">Optional for compare / gap analysis — we'll ask before linking when research completes.</span>
          </label>
          <div class="research-seeds-block research-seeds-block--compact">
            <div class="research-seeds-head">
              <span class="research-seeds-label">Seed papers</span>
              <span id="research-seed-count" class="research-seed-count" hidden></span>
              <button type="button" id="research-seed-clear" class="research-seed-clear" hidden>Clear all</button>
            </div>
            <div id="research-seed-chips" class="research-seed-chips"></div>
            <div id="research-seed-preview" class="research-seed-preview" hidden></div>
            <div class="research-seed-search-wrap">
              <svg class="research-seed-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
              <input type="search" id="research-seed-input" class="research-seed-input" placeholder="Search your library, or paste a DOI / Zotero key…" autocomplete="off" role="combobox" aria-expanded="false" aria-controls="research-seed-picker">
            </div>
            <div id="research-seed-input-hint" class="research-seed-input-hint"></div>
            <div id="research-seed-picker" class="research-seed-picker" hidden></div>
          </div>
        </div>
        </div>
        <div id="research-step-plan" class="research-wizard-pane" hidden>
        <div id="research-plan-review" class="research-plan-review">
          <div class="research-plan-review-head">
            <span class="research-plan-review-title">Search plan</span>
          </div>
          <p id="research-plan-status" class="research-plan-status" hidden></p>
          <p id="research-plan-seed-note" class="research-plan-seed-note" hidden></p>
          <div class="research-plan-grid">
            <label class="research-plan-field research-plan-field--wide">
              <span>Search keywords</span>
              <textarea id="research-plan-keywords" rows="2" placeholder="foldseek, esm3, structure representation…"></textarea>
              <span class="research-plan-field-hint">Query phrases sent to academic search APIs. Mix named methods with topical wording.</span>
            </label>
            <label class="research-plan-field">
              <span>Scope</span>
              <select id="research-plan-scope">
                <option value="balanced">Balanced</option>
                <option value="narrow_compare">Narrow / compare</option>
                <option value="gap_analysis">Gap analysis</option>
                <option value="field_overview">Field overview</option>
              </select>
            </label>
          </div>
          <details class="research-disclosure research-plan-advanced">
            <summary>Refine plan (optional)</summary>
            <div class="research-plan-grid">
              <label class="research-plan-field">
                <span>Anchor terms</span>
                <textarea id="research-plan-anchors" rows="2" placeholder="foldseek, esm3, 3di…"></textarea>
                <span class="research-plan-field-hint">Named methods, models, or acronyms papers should stay close to. Hard on-topic filter.</span>
              </label>
              <label class="research-plan-field">
                <span>Avoid topics</span>
                <textarea id="research-plan-avoid" rows="2" placeholder="gene ontology, function prediction…"></textarea>
                <span class="research-plan-field-hint">Nearby subfields that share vocabulary but are out of scope.</span>
              </label>
              <label class="research-plan-field research-plan-field--wide">
                <span>Sub-questions</span>
                <textarea id="research-plan-subq" rows="2" placeholder="How does method A encode structure?…"></textarea>
                <span class="research-plan-field-hint">Specific questions the literature review should answer.</span>
              </label>
              <label class="research-plan-field research-plan-field--wide">
                <span>Key topics</span>
                <textarea id="research-plan-topics" rows="2" placeholder="structural alphabet, search space coverage…"></textarea>
                <span class="research-plan-field-hint">Thematic coverage goals (concepts, populations, outcomes). Leave blank and the model generates these when research starts.</span>
              </label>
              <label class="research-plan-field research-plan-field--wide">
                <span>Success criteria</span>
                <textarea id="research-plan-success" rows="2" placeholder="A comparison grounded in the named methods with explicit limitations."></textarea>
                <span class="research-plan-field-hint">What a complete answer looks like when research is done.</span>
              </label>
            </div>
          </details>
        </div>
        <details class="research-disclosure research-run-advanced">
          <summary>Advanced run settings</summary>
          <div class="research-settings-row research-run-settings">
            <label class="research-setting">
              <span class="research-setting-label">Agent rounds</span>
              <select id="research-rounds">${roundOpts}</select>
            </label>
            <label class="research-setting">
              <span class="research-setting-label">Web search</span>
              <select id="research-search-provider">${providerOpts}</select>
            </label>
            <label class="research-setting">
              <span class="research-setting-label">Endpoint</span>
              <select id="research-endpoint"><option value="">Default</option></select>
            </label>
            <label class="research-setting">
              <span class="research-setting-label">Model</span>
              <select id="research-model"><option value="">Default</option></select>
            </label>
          </div>
        </details>
        </div>
        <div class="research-controls-row">
          <button type="button" id="research-back-btn" class="research-back-btn" hidden aria-label="Back to question">${_arrowLeftIcon} Back</button>
          <span class="research-controls-spacer"></span>
          <button id="research-add-btn" class="research-add-btn" hidden title="Add to queue with the current search plan">${_plusIcon} Queue</button>
          <button type="button" id="research-continue-btn" class="research-continue-btn">Continue</button>
          <button id="research-start-btn" class="research-start-btn" hidden>${_playIcon} Start research</button>
        </div>
      </div>
      <div id="research-jobs-list" class="research-jobs-list" data-no-swipe-dismiss></div>
    </div>
  `;
}

/** Fade/slide a card out, then run the removal — matches cookbook's smooth exit. */
function _animateOutThenRemove(el, removeFn) {
  if (!el || !el.style) { removeFn(); return; }
  el.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
  el.style.opacity = '0';
  el.style.transform = 'translateX(-10px)';
  setTimeout(removeFn, 320);
}

/** Dismiss the mobile keyboard by stealing focus into a throwaway readonly
 *  input (blur() alone is often ignored on Firefox mobile). */
function _dismissKeyboard(input) {
  try {
    if (input) input.blur();
    const tmp = document.createElement('input');
    tmp.setAttribute('readonly', 'readonly');
    tmp.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;opacity:0;border:0;padding:0;';
    document.body.appendChild(tmp);
    tmp.focus();
    setTimeout(() => { try { tmp.blur(); tmp.remove(); } catch {} }, 60);
  } catch {}
}

function _wireEvents(pane) {
  pane.querySelector('#research-panel-close').addEventListener('click', closePanel);
  pane.querySelector('#research-panel-minimize')?.addEventListener('click', () => {
    const overlay = document.getElementById('research-overlay');
    if (overlay) overlay.style.display = 'none';
    const btn = document.getElementById('tool-research-btn');
    if (btn) btn.classList.add('minimized');
  });
  pane.querySelector('#research-continue-btn')?.addEventListener('click', _handleContinue);
  pane.querySelector('#research-back-btn')?.addEventListener('click', _handleBack);
  pane.querySelector('#research-start-btn')?.addEventListener('click', _confirmPlanAndRun);
  pane.querySelector('#research-add-btn').addEventListener('click', _handleAdd);
  pane.querySelectorAll('.research-compose-tab').forEach(btn => {
    btn.addEventListener('click', () => _switchComposeTab(btn.getAttribute('data-tab')));
  });
  try {
    const savedTab = localStorage.getItem(_TAB_KEY);
    if (savedTab === 'papers' || savedTab === 'topic') _activeComposeTab = savedTab;
  } catch {}
  _switchComposeTab(_activeComposeTab);
  pane.querySelector('#research-seed-clear')?.addEventListener('click', _clearAllSeeds);
  const seedInput = pane.querySelector('#research-seed-input');
  seedInput?.addEventListener('focus', () => { if (!_seedPickerOpen) _openSeedPicker(); });
  seedInput?.addEventListener('input', () => {
    _setSeedInputHint('');
    if (!_seedPickerOpen) _openSeedPicker();
    else _scheduleSeedSearch((seedInput.value || '').trim());
  });
  seedInput?.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (!_seedPickerOpen) _openSeedPicker();
      _setSeedActive(_seedActiveIdx + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      _setSeedActive(_seedActiveIdx - 1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const picker = document.getElementById('research-seed-picker');
      const active = picker?.querySelector('.research-seed-picker-card.is-active');
      if (active) { _toggleSeedFromCard(active); return; }
      const parsed = _parseSeedInput(seedInput.value || '');
      if (parsed.ok) {
        if (_addSeedPaper(parsed.paper)) {
          seedInput.value = '';
          _setSeedInputHint('');
          void _runSeedSearch('');
        } else {
          window.uiModule?.showToast?.('Already in seed list', 2500);
        }
      } else if ((seedInput.value || '').trim()) {
        // Not a ref — add the top library match if there is one.
        const first = picker?.querySelector('.research-seed-picker-card');
        if (first) _toggleSeedFromCard(first);
        else _setSeedInputHint(parsed.error, true);
      }
    } else if (e.key === 'Escape') {
      if (_seedPickerOpen) { e.preventDefault(); _closeSeedPicker(); }
    }
  });
  // Close the picker when focus/clicks move outside the seeds block.
  document.addEventListener('click', (e) => {
    if (!_seedPickerOpen) return;
    const block = document.querySelector('#research-pane-papers .research-seeds-block');
    if (block && !block.contains(e.target)) _closeSeedPicker();
  });
  _loadSeedsFromStorage();
  _renderSeedChips();
  _scheduleSeedPreview();

  const queryInput = pane.querySelector('#research-query');
  queryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (_researchStep === 2) _confirmPlanAndRun();
      else _handleContinue();
    }
  });
  queryInput.addEventListener('input', _updateComposeValidity);
  pane.querySelector('#research-plan-keywords')?.addEventListener('input', _updatePlanValidity);

  const endpointSelect = pane.querySelector('#research-endpoint');
  endpointSelect.addEventListener('change', () => _populateModels(endpointSelect.value));

  ['research-include-preprints', 'research-include-zotero', 'research-include-knowledge'].forEach((id) => {
    pane.querySelector(`#${id}`)?.addEventListener('change', _saveSettingsToStorage);
  });

  ['research-rounds', 'research-search-provider', 'research-endpoint', 'research-model'].forEach((id) => {
    pane.querySelector(`#${id}`)?.addEventListener('change', _saveSettingsToStorage);
  });

  pane.querySelector('#research-mode')?.addEventListener('change', () => {
    projectLink.updateProjectPickerVisibility();
    _saveSettingsToStorage();
    _updateSeedMetaUI();
  });
  pane.querySelector('#research-project-id')?.addEventListener('change', _saveSettingsToStorage);

  _setResearchStep(1);
  _renderJobs();
  void projectLink.populateProjectSelect(_apiBase, document.getElementById('research-project-id'));
  projectLink.updateProjectPickerVisibility();
}

function _readSettings() {
  const preprintsEl = document.getElementById('research-include-preprints');
  const zoteroEl = document.getElementById('research-include-zotero');
  const knowledgeEl = document.getElementById('research-include-knowledge');
  const tab = _getActiveComposeTab();
  const seeds = tab === 'papers' ? _seedRefsForApi() : [];
  const settings = {
    max_rounds: parseInt(document.getElementById('research-rounds')?.value || '0', 10),
    search_provider: document.getElementById('research-search-provider')?.value || undefined,
    endpoint_id: document.getElementById('research-endpoint')?.value || undefined,
    model: document.getElementById('research-model')?.value || undefined,
    include_preprints: preprintsEl ? !!preprintsEl.checked : true,
    include_zotero: zoteroEl ? !!zoteroEl.checked : true,
    include_knowledge: knowledgeEl ? !!knowledgeEl.checked : true,
    mode: tab === 'papers'
      ? (document.getElementById('research-mode')?.value || 'literature_review')
      : 'literature_review',
    report_length: document.getElementById('research-report-length')?.value || 'standard',
    compose_tab: tab,
  };
  if (seeds.length) settings.seed_papers = seeds;
  const projectId = projectLink.readSelectedProjectId();
  if (projectId && projectLink.modeWantsProjectLink(settings.mode)) {
    settings.project_id = projectId;
  }
  const epSel = document.getElementById('research-endpoint');
  if (epSel && epSel.value) {
    const opt = epSel.options[epSel.selectedIndex];
    settings._endpointName = opt?.textContent || '';
  }
  const modelSel = document.getElementById('research-model');
  if (modelSel && modelSel.value) settings._modelName = modelSel.value;
  Object.keys(settings).forEach(k => { if (!settings[k]) delete settings[k]; });
  return settings;
}

function _handleAdd() {
  if (_researchStep !== 2 || !_pendingPlanLaunch) return;
  const approved = _readApprovedPlanFromForm();
  const { query } = _pendingPlanLaunch;
  const settings = { ..._pendingPlanLaunch.settings, ..._readSettings(), approved_plan: approved };
  jobs.addToQueue(query, settings);
  _planFetchToken += 1;
  _pendingPlanLaunch = null;
  _setPlanStatus('', '');
  _setResearchStep(1);
  const queryEl = document.getElementById('research-query');
  if (queryEl) {
    queryEl.value = '';
    queryEl.focus();
  }
}

// Move a job's data back into the compose form so user can edit and re-queue
function _editJob(job) {
  const queryEl = document.getElementById('research-query');
  if (queryEl) {
    queryEl.value = job.query || '';
    queryEl.focus();
    queryEl.setSelectionRange(queryEl.value.length, queryEl.value.length);
  }
  // Restore preprint toggle and settings
  const s = job.settings || {};
  const preprintsEl = document.getElementById('research-include-preprints');
  if (preprintsEl && s.include_preprints !== undefined) preprintsEl.checked = !!s.include_preprints;
  const zoteroEl = document.getElementById('research-include-zotero');
  if (zoteroEl && s.include_zotero !== undefined) zoteroEl.checked = !!s.include_zotero;
  const knowledgeEl = document.getElementById('research-include-knowledge');
  if (knowledgeEl && s.include_knowledge !== undefined) knowledgeEl.checked = !!s.include_knowledge;
  if (s.compose_tab) _switchComposeTab(s.compose_tab);
  else if ((s.seed_papers || []).length) _switchComposeTab('papers');
  const modeEl = document.getElementById('research-mode');
  if (modeEl && s.mode) modeEl.value = s.mode;
  const projectEl = document.getElementById('research-project-id');
  if (projectEl && s.project_id) projectEl.value = s.project_id;
  projectLink.updateProjectPickerVisibility();
  const lengthEl = document.getElementById('research-report-length');
  if (lengthEl && s.report_length) lengthEl.value = s.report_length;
  const roundsEl = document.getElementById('research-rounds');
  if (roundsEl && s.max_rounds) roundsEl.value = s.max_rounds;
  const spEl = document.getElementById('research-search-provider');
  if (spEl && s.search_provider) spEl.value = s.search_provider;
  const epEl = document.getElementById('research-endpoint');
  if (epEl && s.endpoint_id) epEl.value = s.endpoint_id;
  const mEl = document.getElementById('research-model');
  if (mEl && s.model) mEl.value = s.model;
  if (s.approved_plan) {
    _pendingPlanLaunch = {
      query: job.query || '',
      settings: { ...s },
    };
    delete _pendingPlanLaunch.settings.approved_plan;
    _fillPlanReviewForm(s.approved_plan);
    _setResearchStep(2);
    _setPlanStatus('ready', 'Edit the search plan, then start or queue.');
  } else {
    _setResearchStep(1);
  }
  jobs.removeJob(job.id);
  // Scroll the form into view
  queryEl?.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function _restoreSavedSettings() {
  const saved = _loadSettingsFromStorage();
  if (!saved) return;
  const preprintsEl = document.getElementById('research-include-preprints');
  if (preprintsEl && saved.include_preprints !== undefined) {
    preprintsEl.checked = !!saved.include_preprints;
  }
  const zoteroEl = document.getElementById('research-include-zotero');
  if (zoteroEl && saved.include_zotero !== undefined) {
    zoteroEl.checked = !!saved.include_zotero;
  }
  const knowledgeEl = document.getElementById('research-include-knowledge');
  if (knowledgeEl && saved.include_knowledge !== undefined) {
    knowledgeEl.checked = !!saved.include_knowledge;
  }
  const modeEl = document.getElementById('research-mode');
  if (modeEl && saved.mode) modeEl.value = saved.mode;
  const projectEl = document.getElementById('research-project-id');
  if (projectEl && saved.project_id) projectEl.value = saved.project_id;
  const lengthEl = document.getElementById('research-report-length');
  if (lengthEl && saved.report_length) lengthEl.value = saved.report_length;
  if (saved.compose_tab === 'papers' || saved.compose_tab === 'topic') {
    _switchComposeTab(saved.compose_tab);
  }
  projectLink.updateProjectPickerVisibility();
  // Users can pick a specific cap each time if needed.
  const search = document.getElementById('research-search-provider');
  if (search && saved.search_provider !== undefined) search.value = saved.search_provider;
  const ep = document.getElementById('research-endpoint');
  if (ep && saved.endpoint_id) {
    ep.value = saved.endpoint_id;
    _populateModels(saved.endpoint_id);
    if (saved.model) {
      setTimeout(() => {
        const model = document.getElementById('research-model');
        if (model) model.value = saved.model;
      }, 50);
    }
  }
}

async function _loadEndpoints() {
  try {
    const res = await fetch(`${_apiBase}/api/model-endpoints`, { credentials: 'same-origin' });
    if (!res.ok) return;
    _endpoints = await res.json();
    const sel = document.getElementById('research-endpoint');
    if (!sel) return;
    _endpoints.filter(e => e.is_enabled && e.model_type === 'llm').forEach(ep => {
      const opt = document.createElement('option');
      opt.value = ep.id;
      opt.textContent = ep.name || ep.base_url;
      sel.appendChild(opt);
    });
  } catch {}
}

function _populateModels(endpointId) {
  const sel = document.getElementById('research-model');
  if (!sel) return;
  sel.innerHTML = '<option value="">Default</option>';
  if (!endpointId) return;
  const ep = _endpoints.find(e => e.id === endpointId);
  if (!ep || !ep.models) return;
  sortModelIds(ep.models).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    opt.textContent = m;
    sel.appendChild(opt);
  });
}

// ── Job rendering ──

function _renderJobs() {
  // Keep the rail/sidebar indicator in sync on every job-state change,
  // even when the panel is closed (no container yet).
  _syncResearchRail();
  const container = document.getElementById('research-jobs-list');
  if (!container) return;

  if (!jobs.isHydrated()) {
    showLoadingRow(container, 'Loading research…');
    return;
  }

  const allJobs = jobs.getJobs();
  if (!allJobs.length) {
    // No empty-state text in the body — the query box above is the call to
    // action. But still surface the "All past research found in Library,
    // Research" hint under the main title, since the Past section won't
    // render to host it (this is exactly the case the dynamic hint targets).
    container.innerHTML = '';
    const noPastHint = document.getElementById('research-no-past-hint');
    if (noPastHint) {
      noPastHint.style.display = '';
      if (!noPastHint.dataset._wired) {
        noPastHint.dataset._wired = '1';
        noPastHint.querySelector('.research-library-link')?.addEventListener('click', (e) => {
          e.stopPropagation();
          closePanel();
          if (window.documentModule && window.documentModule.openLibrary) {
            window.documentModule.openLibrary({ tab: 'research' });
          }
        });
      }
    }
    return;
  }

  container.innerHTML = '';

  const active = allJobs.filter(j => j.status === 'queued' || j.status === 'running' || j.status === 'error' || j.status === 'cancelled');
  const past = allJobs.filter(j => j.status === 'done' && j._fromLibrary);
  const recentDone = allJobs.filter(j => j.status === 'done' && !j._fromLibrary).reverse();

  // Keep the header "(N research)" chip in sync with the Past-section count.
  // _updateResearchCount fetches the library total only, which under-counts
  // when there's a session-completed job not yet persisted to the library.
  const statsEl = document.getElementById('research-stats');
  if (statsEl) {
    const n = recentDone.length + past.length;
    statsEl.textContent = n + ' research';
  }

  // The main Start button doubles as "Start All (N)" when more than one job
  // is queued — clicking it then opens the parallel/sequential picker. No
  // separate queue-bar button (that was the redundant second button).
  const queued = active.filter(j => j.status === 'queued');
  const startBtn = document.getElementById('research-start-btn');
  if (startBtn && !startBtn.classList.contains('research-start-busy')) {
    startBtn.innerHTML = queued.length > 1
      ? `${_playIcon} Start All (${queued.length})`
      : `${_playIcon} Start`;
    startBtn.dataset._origHTML = startBtn.innerHTML;
  }

  // Dynamic Past hint: when the Past section won't render (no past items),
  // surface the "All past research found in Library, Research" line under
  // the main Research title instead, so the link is always discoverable.
  const noPastHint = document.getElementById('research-no-past-hint');
  if (noPastHint) {
    const hasPast = past.length + recentDone.length > 0;
    noPastHint.style.display = hasPast ? 'none' : '';
    if (!hasPast && !noPastHint.dataset._wired) {
      noPastHint.dataset._wired = '1';
      noPastHint.querySelector('.research-library-link')?.addEventListener('click', (e) => {
        e.stopPropagation();
        closePanel();
        if (window.documentModule && window.documentModule.openLibrary) {
          window.documentModule.openLibrary({ tab: 'research' });
        }
      });
    }
  }

  // Clean up synapses for jobs that finished or disappeared. complete()
  // marks the SVG green for ~800ms before destroy removes it.
  const liveIds = new Set(allJobs.filter(j => j.status === 'running').map(j => j.id));
  for (const [jobId, entry] of _jobSynapses) {
    if (liveIds.has(jobId)) continue;
    try { entry.synapse.complete(); } catch {}
    setTimeout(() => { try { entry.synapse.destroy(); } catch {} }, 800);
    _jobSynapses.delete(jobId);
  }

  // Group into foldable sections: "Active" (in-progress) and "Past research"
  // (everything done — this session + library). Each has a clickable title
  // that collapses its body. Collapsed state persists across re-renders via
  // the module-level _collapsedSections set.
  const _addSection = (key, title, arr) => {
    if (!arr.length) return;
    const collapsed = _collapsedSections.has(key);
    const sec = document.createElement('div');
    sec.className = 'research-section' + (collapsed ? ' collapsed' : '');
    const header = document.createElement('div');
    header.className = 'research-section-header';
    // Status dot on the right (visible even when folded):
    //  • Active = pulsing accent glow (work in progress)
    //  • any failed/cancelled job in Active = solid red
    //  • Past (done) = solid green (success)
    let dotColor, dotPulse = false;
    if (key === 'active') {
      const failed = arr.some(j => j.status === 'error' || j.status === 'cancelled');
      if (failed) { dotColor = '#f44336'; }
      else { dotColor = 'var(--accent, var(--red))'; dotPulse = true; }
    } else {
      dotColor = 'var(--color-success)';
    }
    // Both sections carry a "Clear all" button in the header (cookbook-running
    // section style); it clears all research and must not toggle the fold.
    const clearAllHtml = '<button class="research-section-clear" title="Clear all research">' + _cancelIcon + ' Clear all</button>';
    header.innerHTML =
      '<span class="research-section-title">' + title + '</span>'
      + '<span class="research-section-count memory-count">' + arr.length + ' research</span>'
      + '<span class="research-section-right">'
      +   clearAllHtml
      +   '<span class="research-section-dot' + (dotPulse ? ' pulsing' : '') + '" style="background:' + dotColor + ';"></span>'
      +   '<svg class="research-section-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>'
      + '</span>';
    header.addEventListener('click', () => {
      const nowCollapsed = sec.classList.toggle('collapsed');
      if (nowCollapsed) _collapsedSections.add(key); else _collapsedSections.delete(key);
    });
    header.querySelector('.research-section-clear')?.addEventListener('click', (e) => {
      e.stopPropagation();
      // Gracefully fade + collapse the whole section block(s) out, then clear.
      container.querySelectorAll('.research-section').forEach(s => {
        s.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
        s.style.opacity = '0';
        s.style.transform = 'translateX(-10px)';
      });
      setTimeout(() => jobs.clearAll(), 320);
    });
    const body = document.createElement('div');
    body.className = 'research-section-body';
    // Hint inside the "Past research" header (second line, styled like the main
    // Research description) — past research is kept in the Library's Research tab.
    if (key === 'past') {
      const hint = document.createElement('div');
      hint.className = 'memory-desc doclib-desc research-library-hint';
      hint.innerHTML = 'Past reports in <button type="button" class="research-library-link">Library → Research</button>';
      hint.querySelector('.research-library-link').addEventListener('click', (e) => {
        e.stopPropagation();
        // Close the research panel first so the Library opens ABOVE it on mobile
        // (otherwise it stacks under the full-screen panel).
        closePanel();
        if (window.documentModule && window.documentModule.openLibrary) {
          window.documentModule.openLibrary({ tab: 'research' });
        }
      });
      header.appendChild(hint);
    }
    arr.forEach(j => body.appendChild(_buildJobCard(j)));
    sec.appendChild(header);
    sec.appendChild(body);
    container.appendChild(sec);
  };

  // ("Clear all" lives inside the Past research section header — see _addSection.)

  _addSection('active', 'Active', active);
  _addSection('past', 'Past research', recentDone.concat(past));
}

/** Pick parallel vs sequential as a small popover anchored to the
 *  Start-All button. Drops down by default; flips to drop-up if there
 *  isn't enough room below the button. Outside-click / Esc dismiss. */
function _promptParallelOrSequential(count, anchorBtn) {
  // Strip any prior instance so a second click closes-then-reopens cleanly.
  const existing = document.getElementById('research-run-mode-popover');
  if (existing) { existing.remove(); return; }
  if (!anchorBtn) return;

  const rect = anchorBtn.getBoundingClientRect();
  const pop = document.createElement('div');
  pop.id = 'research-run-mode-popover';
  pop.className = 'research-run-mode-popover';
  // Same parallel / sequential glyphs the model-comparison picker uses.
  const ICON_PARALLEL = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="6" x2="20" y2="6"/><line x1="4" y1="12" x2="20" y2="12"/><line x1="4" y1="18" x2="20" y2="18"/></svg>';
  const ICON_SEQUENTIAL = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="8" y1="6" x2="20" y2="6"/><line x1="8" y1="12" x2="20" y2="12"/><line x1="8" y1="18" x2="20" y2="18"/><circle cx="4" cy="6" r="1.5" fill="currentColor"/><circle cx="4" cy="12" r="1.5" fill="currentColor"/><circle cx="4" cy="18" r="1.5" fill="currentColor"/></svg>';
  pop.innerHTML =
    '<button class="research-run-mode-row" data-mode="parallel">' + ICON_PARALLEL + '<span class="rrm-title">Parallel</span></button>'
    + '<button class="research-run-mode-row" data-mode="sequential">' + ICON_SEQUENTIAL + '<span class="rrm-title">Sequential</span></button>';
  document.body.appendChild(pop);

  // Position: prefer dropping down from the button's bottom-right corner.
  // If there isn't enough room below the viewport, flip to drop-up above.
  const popHeight = pop.offsetHeight;
  const margin = 6;
  const spaceBelow = window.innerHeight - rect.bottom;
  const goUp = spaceBelow < popHeight + margin && rect.top > popHeight + margin;
  const top = goUp ? (rect.top - popHeight - margin) : (rect.bottom + margin);
  // Right-align to the button so the menu doesn't extend off-screen on the right
  const right = Math.max(8, window.innerWidth - rect.right);
  pop.style.top = `${Math.round(top)}px`;
  pop.style.right = `${Math.round(right)}px`;
  pop.classList.add(goUp ? 'rrm-up' : 'rrm-down');

  const close = () => {
    pop.remove();
    document.removeEventListener('click', onDocClick, true);
    document.removeEventListener('keydown', onKey, true);
  };
  const onDocClick = (e) => {
    if (pop.contains(e.target) || e.target === anchorBtn) return;
    close();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
  };
  setTimeout(() => {
    document.addEventListener('click', onDocClick, true);
    document.addEventListener('keydown', onKey, true);
  }, 0);

  pop.querySelectorAll('.research-run-mode-row').forEach(b => {
    b.addEventListener('click', () => {
      const mode = b.dataset.mode;
      close();
      if (mode === 'parallel') jobs.startAllQueued();
      else jobs.startAllQueuedSequential();
    });
  });
}

function _buildJobCard(job) {
  const card = document.createElement('div');
  card.className = `research-job-card ${job.status}${job._fromLibrary ? ' from-library' : ''}`;
  card.dataset.jobId = job.id;
  if (job.category) card.dataset.category = job.category;
  else card.dataset.category = 'academic';

  const elapsed = jobs.formatElapsed(job.elapsed || 0);
  const isExpanded = _expandedJobId === job.id;
  const modelTag = (job.modelName || job.settings?._modelName)
    ? `<span class="research-job-model">${_esc(job.modelName || job.settings._modelName)}</span>` : '';

  if (job.status === 'queued') {
    const rounds = job.settings?.max_rounds;
    const roundsLabel = !rounds ? 'Auto rounds' : `${rounds} rounds`;
    const epName = job.settings?._endpointName || '';
    const mName = job.settings?._modelName || '';
    const meta = [mName, epName, roundsLabel].filter(Boolean).join(' -- ');
    card.innerHTML = `
      <div class="research-job-header">
        <span class="research-job-query">${_esc(job.query)}</span><span class="research-cat-badge research-cat-standard">Academic</span>
      </div>
      <div class="research-job-queued-meta">${_esc(meta)}</div>
      <div class="research-job-actions">
        <button class="research-job-action" data-action="start" title="Start">${_playIcon} Start</button>
        <button class="research-job-action" data-action="edit" title="Edit query">${_editIcon} Edit</button>
        <button class="research-job-action research-job-action-dim" data-action="remove" title="Remove">${_cancelIcon}</button>
      </div>
    `;
    card.querySelector('[data-action="start"]').addEventListener('click', (e) => {
      e.stopPropagation(); jobs.startQueued(job.id);
    });
    card.querySelector('[data-action="edit"]').addEventListener('click', (e) => {
      e.stopPropagation(); _editJob(job);
    });
    card.querySelector('[data-action="remove"]').addEventListener('click', (e) => {
      e.stopPropagation(); jobs.removeJob(job.id);
    });

  } else if (job.status === 'running') {
    // Auto mode (max_rounds=0/undefined) — show round number without total,
    // and base the progress bar on a heuristic cap of 8 rounds.
    const userMaxR = job.settings?.max_rounds || 0;
    const phaseMaxR = userMaxR || 0;  // 0 = formatPhase shows "Round X" without total
    const phase = jobs.formatPhase(job.progress, phaseMaxR);
    const round = job.progress?.round || 0;
    const barCap = userMaxR || 8;
    const pct = Math.min(100, Math.round((round / barCap) * 100));
    card.innerHTML = `
      <div class="research-job-header">
        <span class="research-job-query">${_esc(job.query)}</span><span class="research-cat-badge research-cat-standard">Academic</span>
        ${modelTag}
        <span class="research-job-time">${elapsed}</span>
        <button class="research-synapse-toggle${_synapseMinimized ? ' active' : ''}" title="${_synapseMinimized ? 'Show visualization' : 'Minimize visualization'}">${_synapseMinimized ? _vizExpandIcon : _vizCollapseIcon}</button>
        <button class="research-job-cancel" title="Cancel research">${_cancelIcon}</button>
      </div>
      <div class="research-job-phase">${phase}</div>
      <div class="research-job-synapse-host${_synapseMinimized ? ' synapse-collapsed' : ''}" data-synapse-host="${job.id}"></div>
      <div class="research-progress-bar"><div class="research-progress-fill" style="width:${pct}%"></div></div>
    `;
    card.querySelector('.research-job-cancel').addEventListener('click', (e) => {
      e.stopPropagation(); jobs.cancelJob(job.id);
    });
    card.querySelector('.research-synapse-toggle')?.addEventListener('click', (e) => {
      e.stopPropagation(); _toggleSynapseMinimized();
    });
    // Click anywhere on the header (title/model/time) toggles the visualization
    // too — the cancel/synapse buttons stopPropagation so they keep their own.
    const _runHdr = card.querySelector('.research-job-header');
    if (_runHdr) {
      _runHdr.style.cursor = 'pointer';
      _runHdr.addEventListener('click', () => _toggleSynapseMinimized());
    }
    // Attach (or re-attach) the live synapse visualization. Created once per
    // job so animations/state persist across the _renderJobs() rebuilds that
    // fire on every progress event.
    const host = card.querySelector('.research-job-synapse-host');
    let entry = _jobSynapses.get(job.id);
    if (!entry) {
      const synapse = createResearchSynapse(host, {
        query: job.query || '',
        startedAt: job.startedAt || (Date.now() - (job.elapsed || 0) * 1000),
        compact: true,
      });
      entry = { synapse, status: 'running' };
      _jobSynapses.set(job.id, entry);
    } else {
      // Move the existing element into the freshly-rendered host
      host.appendChild(entry.synapse.element);
    }
    // Push the current progress state
    if (job.progress) {
      entry.synapse.setPhase(job.progress.phase, job.progress);
      if (typeof job.progress.round === 'number') entry.synapse.setRound(job.progress.round);
      if (typeof job.progress.total_sources === 'number') entry.synapse.setSourceCount(job.progress.total_sources);
    }

  } else if (job.status === 'done') {
    // Library-loaded jobs have sources=null but pre-set sourceCount; fresh jobs
    // populate sources directly. Prefer the pre-set count if present. LDR also
    // stores sources on evidence_registry even when top-level sources is empty.
    const registryCount = Array.isArray(job.evidence_registry?.sources)
      ? job.evidence_registry.sources.length
      : 0;
    const srcCount = Math.max(
      job.sources?.length || 0,
      typeof job.sourceCount === 'number' ? job.sourceCount : 0,
      registryCount,
    );
    // Flag failure only when nothing usable was gathered (no sources and no report).
    const hasReport = !!(job.raw_report || job.result || '').trim()
      && !/## Research Failed|## Complete Research Failure|## Research Engine Unavailable/i.test(
        job.raw_report || job.result || ''
      );
    const failed = srcCount === 0 && !hasReport;
    if (failed) card.classList.add('research-job-failed');
    const doneBadge = failed
      ? `<span class="research-cat-badge research-cat-failed">${_cancelIcon} no results</span>`
      : `<span class="research-cat-badge research-cat-standard">Academic</span>`;
    const failNote = failed
      ? `<div class="research-job-failnote">Couldn't extract anything — try rephrasing the question, or switch the search engine in Settings.</div>`
      : '';
    const connCount = jobs.isConnectionsReviewed(job.id)
      ? 0
      : (job.graph_connection_proposals?.proposal_count || 0);
    const connBtn = connCount
      ? `<button class="research-job-action research-job-action-connections" data-action="connections" title="Review proposed graph links from this research">${_linkIcon} Review ${connCount} graph connection${connCount === 1 ? '' : 's'}</button>`
      : '';
    // Actions stay hidden until the card is opened — past research reads as a
    // clean list of titles, and the (simplified) action row only appears on
    // demand. Graph-connection review is the one CTA kept visible when present.
    const actionsHtml = `
      <div class="research-job-actions">
        <button class="research-job-action research-job-action-report" data-action="report" title="Visual report">${_externalIcon} Visual Report</button>
        <button class="research-job-action" data-action="chat" title="Open follow-up chat with this research as context">${_chatIcon} Discuss</button>
        <button class="research-job-action" data-action="export" title="Download report">${_exportIcon} Export</button>
        <button class="research-job-action" data-action="copy" title="Copy report to clipboard">${_copyIcon} Copy</button>
        <button class="research-job-action" data-action="zotero" title="Choose sources and a Zotero folder">${_bookmarkIcon} Save to Zotero</button>
        <button class="research-job-action" data-action="project" title="Link this research to a project workspace">${_folderPlusIcon} Add to project</button>
        <button class="research-job-action research-job-action-dim" data-action="dismiss" title="Clear from list">${_cancelIcon} Clear</button>
        <button class="research-job-action research-job-action-dim" data-action="delete" title="Delete from disk">${_trashIcon} Delete</button>
      </div>`;
    card.innerHTML = `
      <div class="research-job-header">
        <span class="research-job-query">${_esc(job.query)}</span>${doneBadge}
        ${modelTag}
        <span class="research-job-meta">${elapsed} -- ${srcCount} sources</span>
      </div>
      ${failNote}
      ${connBtn ? `<div class="research-job-actions research-job-actions-conn">${connBtn}</div>` : ''}
      ${isExpanded ? actionsHtml : ''}
      ${isExpanded ? `<div class="research-job-result">${_renderResult(job)}</div>` : '<div class="research-job-preview-hint">Click to preview report &amp; actions</div>'}
    `;
    card.classList.toggle('is-expanded', isExpanded);
    card.addEventListener('click', async (e) => {
      if (e.target.closest('.research-job-action, .research-export-menu, .research-cite-link, .research-report-sources a, .research-preview-section, .research-preview-section *')) return;
      if (_expandedJobId === job.id) _expandedJobId = null;
      else {
        _expandedJobId = job.id;
        await _ensureResult(job);
      }
      _renderJobs();
    });
    card.querySelector('[data-action="connections"]')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      const btn = e.currentTarget;
      if (btn.dataset.busy === '1') return;
      btn.dataset.busy = '1';
      try {
        const open = await jobs.toggleResearchConnections(job);
        btn.classList.toggle('is-active', open);
        const n = job.graph_connection_proposals?.proposal_count || 0;
        btn.innerHTML = open
          ? `${_linkIcon} Hide graph connection${n === 1 ? '' : 's'}`
          : `${_linkIcon} Review ${n} graph connection${n === 1 ? '' : 's'}`;
      } finally {
        btn.dataset.busy = '';
      }
    });
    card.querySelector('[data-action="copy"]')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      const btn = e.currentTarget; // capture before await — currentTarget becomes null after
      if (!job.result) await _ensureResult(job);
      _copyResult(job, btn);
    });
    card.querySelector('[data-action="export"]')?.addEventListener('click', (e) => {
      e.stopPropagation();
      _toggleResearchExportMenu(e.currentTarget, job.id);
    });
    card.querySelector('[data-action="report"]')?.addEventListener('click', (e) => {
      e.stopPropagation();
      window.open(`${_apiBase}/api/research/report/${job.id}`, '_blank');
    });
    card.querySelector('[data-action="chat"]')?.addEventListener('click', (e) => {
      e.stopPropagation();
      _chatAboutResearch(job.id, e.currentTarget);
    });
    card.querySelector('[data-action="zotero"]')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      const btn = e.currentTarget;
      const orig = btn.textContent;
      btn.disabled = true;
      try {
        const result = await openZoteroSaveSheet({ sessionId: job.id, apiBase: _apiBase });
        if (result?.cancelled) return;
        if (result?.ok) {
          const skipped = result.skipped_in_library
            ? ` (${result.skipped_in_library} already in library)`
            : '';
          btn.textContent = `Saved ${result.created || 0}${skipped}`;
          setTimeout(() => { btn.textContent = orig; }, 2500);
        }
      } catch (err) {
        btn.textContent = 'Failed';
        btn.title = err.message || 'Save failed';
        setTimeout(() => {
          btn.textContent = orig;
          btn.title = 'Choose sources and a Zotero folder';
        }, 2500);
      } finally {
        btn.disabled = false;
      }
    });
    card.querySelector('[data-action="project"]')?.addEventListener('click', (e) => {
      e.stopPropagation();
      void projectLink.promptLinkResearchJob(job, _apiBase);
    });
    card.querySelector('[data-action="delete"]')?.addEventListener('click', async (e) => {
      e.stopPropagation();
      if (window.styledConfirm) {
        const ok = await window.styledConfirm('Delete this research? This permanently removes it from disk.', { confirmText: 'Delete', danger: true });
        if (!ok) return;
      }
      try { await fetch(`${_apiBase}/api/research/${job.id}`, { method: 'DELETE', credentials: 'same-origin' }); } catch {}
      _animateOutThenRemove(card, () => jobs.removeJob(job.id));
    });
    card.querySelector('[data-action="dismiss"]')?.addEventListener('click', (e) => {
      e.stopPropagation();
      _animateOutThenRemove(card, () => jobs.removeJob(job.id));
    });
    if (isExpanded) _wireResearchReportInteractions(card);

  } else {
    const errMsg = job.errorMsg ? `<div class="research-job-error">${_esc(job.errorMsg)}</div>` : '';
    card.innerHTML = `
      <div class="research-job-header">
        <span class="research-job-query">${_esc(job.query)}</span><span class="research-cat-badge research-cat-standard">Academic</span>
        <span class="research-job-status">${job.status}</span>
      </div>
      ${errMsg}
      <div class="research-job-actions">
        <button class="research-job-action" data-action="retry" title="Retry">${_retryIcon} Retry</button>
        <button class="research-job-action" data-action="edit" title="Edit and retry">${_editIcon} Edit</button>
        <button class="research-job-action research-job-action-dim" data-action="dismiss" title="Dismiss">${_cancelIcon}</button>
      </div>
    `;
    card.querySelector('[data-action="retry"]').addEventListener('click', (e) => {
      e.stopPropagation(); jobs.retryJob(job.id);
    });
    card.querySelector('[data-action="edit"]').addEventListener('click', (e) => {
      e.stopPropagation(); _editJob(job);
    });
    card.querySelector('[data-action="dismiss"]').addEventListener('click', (e) => {
      e.stopPropagation(); jobs.removeJob(job.id);
    });
  }

  return card;
}

const _CAT_ICONS = {
  academic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/><path d="M8 7h8"/><path d="M8 11h6"/></svg>',
};

const _CAT_LABELS = {
  academic: 'Academic Literature Review',
};

function _splitExecutiveSummary(markdown) {
  const text = markdown || '';
  const match = text.match(/^##\s+Executive Summary\s*$/im);
  if (!match) return { summary: '', body: text };
  const start = match.index + match[0].length;
  const rest = text.slice(start);
  const next = rest.search(/^##\s+/m);
  const summary = (next >= 0 ? rest.slice(0, next) : rest).trim();
  const prefix = text.slice(0, match.index).trim();
  const suffix = next >= 0 ? rest.slice(next).trim() : '';
  const body = [prefix, suffix].filter(Boolean).join('\n\n');
  return { summary, body: body || text };
}

function _resolveSourceNav(source) {
  const url = (source.url || '').trim();
  const sid = (source.source_id || '').trim();
  const num = source.citation_num;
  if (url.startsWith('http://') || url.startsWith('https://')) {
    return { href: url, external: true, nodeId: '' };
  }
  let nodeId = '';
  if (url.startsWith('links://')) nodeId = url.slice('links://'.length);
  else if (sid.startsWith('src:graph:')) nodeId = sid.slice('src:graph:'.length);
  else if (sid.startsWith('src:paper:')) nodeId = `paper:${sid.slice('src:paper:'.length)}`;
  else if (sid.startsWith('src:zotero:')) nodeId = `paper:${sid.slice('src:zotero:'.length)}`;
  if (nodeId) {
    const idx = nodeId.indexOf(':');
    const type = idx >= 0 ? nodeId.slice(0, idx) : 'document';
    const raw = idx >= 0 ? nodeId.slice(idx + 1) : nodeId;
    if (type === 'document' && raw) return { href: `#document-${raw}`, external: false, nodeId };
    if (type === 'paper' && raw) return { href: `#paper-${raw.toUpperCase()}`, external: false, nodeId };
    if (type === 'task' && raw) return { href: `#task-${raw}`, external: false, nodeId };
  }
  if (url.startsWith('#document-') || url.startsWith('#paper-') || url.startsWith('#task-')) {
    return { href: url, external: false, nodeId: nodeId || '' };
  }
  return { href: `#research-source-${num}`, external: false, nodeId: '' };
}

function _linkifyCitationMarkersMd(md) {
  return (md || '').split('\n').map((line) => {
    if (/^\[\d+\]:\s/.test(line.trim())) return line;
    return line.replace(/\[(\d+)\](?!\()(?!:)/g, '%%CITE:$1%%');
  }).join('\n');
}

const _CITE_SLOT_PREFIX = '___CITE_SLOT_';

function _protectCitationPlaceholders(md) {
  const slots = [];
  const text = (md || '').replace(/%%CITE:(\d+)%%/g, (_m, num) => {
    const token = `${_CITE_SLOT_PREFIX}${slots.length}___`;
    slots.push(num);
    return token;
  });
  return { text, slots };
}

function _restoreCitationPlaceholders(html, slots) {
  let out = html || '';
  slots.forEach((num, i) => {
    out = out.split(`${_CITE_SLOT_PREFIX}${i}___`).join(`%%CITE:${num}%%`);
  });
  return out;
}

function _linkifyBracketCitationsHtml(html) {
  const parts = (html || '').split(/(<a\b[^>]*>.*?<\/a>)/gis);
  return parts.map((part, i) => {
    if (i % 2 === 1) return part;
    return part.replace(/\[(\d+)\](?!\()/g, (_m, num) =>
      `<a href="#research-source-${num}" class="research-cite-link" data-cite="${num}">[${num}]</a>`);
  }).join('');
}

function _applyCitationPlaceholders(html) {
  let out = (html || '').replace(/%%CITE:(\d+)%%/g, (_m, num) =>
    `<a href="#research-source-${num}" class="research-cite-link" data-cite="${num}">[${num}]</a>`);
  return _linkifyBracketCitationsHtml(out);
}

function _renderMarkdown(md) {
  if (!md) return '';
  const prepared = _linkifyCitationMarkersMd(md);
  const { text, slots } = _protectCitationPlaceholders(prepared);
  if (_markdownModule?.mdToHtml) {
    const html = _restoreCitationPlaceholders(_markdownModule.mdToHtml(text), slots);
    return _applyCitationPlaceholders(html);
  }
  return `<p>${_esc(md)}</p>`;
}

function _registrySources(job) {
  const reg = job.evidence_registry;
  if (reg && Array.isArray(reg.sources) && reg.sources.length) {
    return reg.sources
      .slice()
      .sort((a, b) => (a.citation_num || 0) - (b.citation_num || 0))
      .map((s) => ({
        citation_num: s.citation_num,
        title: s.title || '',
        url: s.url || '',
        authors: s.authors || '',
        year: s.year || '',
        source_id: s.source_id || '',
      }));
  }
  return (job.sources || []).map((s, i) => ({
    citation_num: i + 1,
    title: s.title || '',
    url: s.url || '',
    authors: '',
    year: '',
    source_id: '',
  }));
}

function _renderRegistrySources(sources) {
  if (!sources.length) return '';
  const rows = sources.map((s) => {
    const nav = _resolveSourceNav(s);
    const meta = [s.authors, s.year].filter(Boolean).join(' · ');
    const title = _esc(s.title || s.url || 'Untitled');
    const href = _esc(nav.href);
    const external = nav.external ? ' target="_blank" rel="noopener"' : '';
    const nodeAttr = nav.nodeId ? ` data-node-id="${_esc(nav.nodeId)}"` : '';
    const cls = nav.external ? '' : ' research-report-source-internal';
    return `<a id="research-source-${s.citation_num}" class="research-report-source${cls}" href="${href}"${external}${nodeAttr} data-cite="${s.citation_num}">
      <span class="research-report-source-num">[${s.citation_num}]</span>
      <span class="research-report-source-title">${title}${meta ? `<span class="research-report-source-meta">${_esc(meta)}</span>` : ''}</span>
    </a>`;
  }).join('');
  return `<aside class="research-report-sources"><div class="research-report-sources-title">Sources</div><div class="research-report-sources-scroll">${rows}</div></aside>`;
}

function _openInternalResearchLink(href, nodeId) {
  const openNode = (id) => {
    import('../knowledge.js').then((mod) => {
      const open = mod.openKnowledgeNode || mod.default?.openKnowledgeNode;
      if (open) open(id);
    }).catch(() => {});
  };
  if (nodeId) {
    openNode(nodeId);
    return;
  }
  if (href.startsWith('#document-')) {
    openNode(`document:${href.slice('#document-'.length)}`);
    return;
  }
  if (href.startsWith('#paper-')) {
    openNode(`paper:${href.slice('#paper-'.length)}`);
    return;
  }
  if (href.startsWith('#task-')) {
    openNode(`task:${href.slice('#task-'.length)}`);
    return;
  }
}

function _wireResearchReportInteractions(card) {
  card.querySelectorAll('.research-cite-link').forEach((link) => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const target = card.querySelector(`#research-source-${link.dataset.cite}`);
      if (!target) return;
      target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      target.classList.add('is-highlighted');
      setTimeout(() => target.classList.remove('is-highlighted'), 1600);
    });
  });
  card.querySelectorAll('.research-report-source-internal, .research-report-source[data-node-id]').forEach((link) => {
    link.addEventListener('click', (e) => {
      const href = link.getAttribute('href') || '';
      if (!href || href.startsWith('http')) return;
      e.preventDefault();
      e.stopPropagation();
      _openInternalResearchLink(href, link.dataset.nodeId || '');
    });
  });
}

function _closeResearchExportMenu() {
  if (_researchExportMenu) {
    _researchExportMenu.remove();
    _researchExportMenu = null;
  }
}

function _downloadResearchExport(jobId, format, scope = 'cited') {
  const url = `${_apiBase}/api/research/${encodeURIComponent(jobId)}/export?format=${encodeURIComponent(format)}&scope=${encodeURIComponent(scope)}`;
  const a = document.createElement('a');
  a.href = url;
  a.rel = 'noopener';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function _toggleResearchExportMenu(anchorBtn, jobId) {
  if (_researchExportMenu) {
    _closeResearchExportMenu();
    return;
  }
  const rect = anchorBtn.getBoundingClientRect();
  const menu = document.createElement('div');
  menu.className = 'research-export-menu';
  menu.innerHTML = [
    { label: 'Markdown (.md)', fmt: 'markdown', scope: 'cited' },
    { label: 'BibTeX (cited)', fmt: 'bibtex', scope: 'cited' },
    { label: 'CSL JSON (cited)', fmt: 'csl-json', scope: 'cited' },
    { label: 'BibTeX (all sources)', fmt: 'bibtex', scope: 'all' },
  ].map((item) => `<button type="button" class="research-export-item" data-fmt="${item.fmt}" data-scope="${item.scope}">${item.label}</button>`).join('');
  document.body.appendChild(menu);
  _researchExportMenu = menu;
  const top = Math.min(rect.bottom + 6, window.innerHeight - menu.offsetHeight - 8);
  menu.style.top = `${Math.round(top)}px`;
  menu.style.left = `${Math.round(Math.max(8, rect.left))}px`;
  const close = () => {
    _closeResearchExportMenu();
    document.removeEventListener('click', onDocClick, true);
    document.removeEventListener('keydown', onKey, true);
  };
  const onDocClick = (e) => {
    if (menu.contains(e.target) || e.target === anchorBtn) return;
    close();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
  };
  setTimeout(() => {
    document.addEventListener('click', onDocClick, true);
    document.addEventListener('keydown', onKey, true);
  }, 0);
  menu.querySelectorAll('.research-export-item').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      _downloadResearchExport(jobId, btn.dataset.fmt, btn.dataset.scope || 'cited');
      close();
    });
  });
}

function _renderVerificationBadge(job) {
  const v = job.verification;
  if (!v || !(v.checked > 0)) return '';
  const supported = v.supported || 0;
  const partial = v.partial || 0;
  const unsupported = v.unsupported || 0;
  let tone = 'ok', label = 'Citations verified';
  if (unsupported) { tone = 'bad'; label = 'Citations need review'; }
  else if (partial) { tone = 'warn'; label = 'Citations mostly verified'; }
  const conf = (typeof v.confidence === 'number') ? ` · ${v.confidence}% supported` : '';
  const flagged = Array.isArray(v.flagged) ? v.flagged : [];
  let details = '';
  if (flagged.length) {
    const rows = flagged.slice(0, 20).map((it) => {
      const verdict = String(it.verdict || '').toUpperCase();
      const vc = verdict === 'UNSUPPORTED' ? 'bad' : 'warn';
      const cites = (it.citations || []).map((n) => `[${n}]`).join(' ');
      const reason = it.reason ? ` — <em>${_esc(it.reason)}</em>` : '';
      return `<li><span class="rv-tag rv-${vc}">${_esc(verdict)}</span> `
        + `<span class="rv-cite">${_esc(cites)}</span> `
        + `${_esc(it.claim || '')}${reason}</li>`;
    }).join('');
    details = `<details class="rv-details"><summary>Review ${flagged.length} flagged `
      + `claim${flagged.length === 1 ? '' : 's'}</summary><ul class="rv-list">${rows}</ul></details>`;
  }
  return `<div class="rv-badge rv-${tone}">`
    + `<div class="rv-head"><span class="rv-dot"></span>`
    + `<span class="rv-label">${_esc(label)}</span>`
    + `<span class="rv-meta">${v.checked} claims checked${conf}</span></div>`
    + `<div class="rv-counts">`
    + `<span class="rv-count rv-ok">${supported} supported</span>`
    + `<span class="rv-count rv-warn">${partial} partial</span>`
    + `<span class="rv-count rv-bad">${unsupported} unsupported</span></div>`
    + `${details}</div>`;
}

function _renderResult(job) {
  if (!job.result) return '<div class="research-job-loading">Loading result...</div>';
  const reportText = job.rawReport || job.result;
  const { summary } = _splitExecutiveSummary(reportText);
  const registrySources = _registrySources(job);

  let html = '<div class="research-report-shell">';
  html += _renderRegistrySources(registrySources);
  html += '<div class="research-report-main">';
  html += _renderVerificationBadge(job);
  html += `
    <section class="research-preview-section">
      <div class="research-preview-label">Executive Summary</div>
      <div class="research-preview-body">${summary
    ? _renderMarkdown(summary)
    : '<p class="research-preview-empty">No executive summary section in this report.</p>'}</div>
    </section>`;
  html += '</div></div>';
  return html;
}

async function _ensureResult(job) {
  if (job.result) return;
  try {
    const res = await fetch(`${_apiBase}/api/research/result-peek/${job.id}`, {
      method: 'POST', credentials: 'same-origin',
    });
    if (!res.ok) return;
    const d = await res.json();
    job.result = d.result;
    job.rawReport = d.raw_report || d.result;
    job.sources = d.sources;
    job.findings = d.raw_findings;
    job.evidence_registry = d.evidence_registry || null;
    job.verification = d.verification || null;
  } catch {}
}

async function _copyResult(job, btn) {
  if (!job.result) return;
  let text = `# ${job.query}\n\n${job.result}`;
  if (job.findings?.length) {
    text += '\n\n---\n## Raw Findings\n';
    for (const f of job.findings) {
      text += `\n### ${f.title || 'Untitled'}\nSource: ${f.url || ''}\n${f.summary || ''}\n`;
    }
  }
  if (job.sources?.length) {
    const srcList = job.sources.map(s => `- [${s.title || s.url}](${s.url})`).join('\n');
    text += `\n\n---\n## Sources\n${srcList}`;
  }
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      ok = true;
    }
  } catch {}
  if (!ok) {
    // Fallback for non-secure contexts (HTTP self-host) where navigator.clipboard
    // is unavailable. The textarea must be in-viewport and focusable for Firefox
    // Android / iOS Safari to allow execCommand('copy').
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.readOnly = false;
    ta.contentEditable = 'true';
    ta.style.cssText = 'position:fixed;top:0;left:0;width:1px;height:1px;padding:0;border:0;opacity:0;font-size:16px;';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    try { ta.setSelectionRange(0, text.length); } catch {}
    try {
      const sel = window.getSelection();
      if (sel && (!sel.rangeCount || sel.isCollapsed)) {
        const range = document.createRange();
        range.selectNodeContents(ta);
        sel.removeAllRanges();
        sel.addRange(range);
        ta.setSelectionRange(0, text.length);
      }
    } catch {}
    try { ok = document.execCommand('copy'); } catch {}
    ta.remove();
  }
  if (btn) {
    const orig = btn.innerHTML;
    if (ok) {
      btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`;
      btn.classList.add('research-job-action-copied');
      setTimeout(() => { btn.innerHTML = orig; btn.classList.remove('research-job-action-copied'); }, 2000);
    } else {
      btn.innerHTML = `${_cancelIcon} Failed`;
      setTimeout(() => { btn.innerHTML = orig; }, 2000);
    }
  }
}

// ── Chat about this research (server-side spinoff) ──

async function _chatAboutResearch(researchId, btn) {
  if (!researchId) return;
  const origLabel = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = `${_chatIcon} Creating…`; }
  const sm = window.sessionModule || _sessionModule;
  try {
    const res = await fetch(`${_apiBase}/api/research/spinoff/${encodeURIComponent(researchId)}`, {
      method: 'POST', credentials: 'same-origin',
    });
    if (!res.ok) {
      let detail = '';
      try { detail = (await res.json()).detail || ''; } catch {}
      throw new Error(detail || `HTTP ${res.status}`);
    }
    const payload = await res.json();
    closePanel();
    if (sm && sm.selectSession && payload.session_id) {
      if (sm.loadSessions) await sm.loadSessions().catch(() => {});
      await sm.selectSession(payload.session_id);
    } else if (payload.session_id) {
      window.location.hash = '#' + payload.session_id;
      window.location.reload();
    } else {
      throw new Error('Server returned no session id');
    }
  } catch (e) {
    if (btn) { btn.disabled = false; btn.innerHTML = origLabel; }
    const msg = 'Could not start follow-up chat: ' + (e.message || e);
    if (window.uiModule && window.uiModule.showError) window.uiModule.showError(msg);
    else alert(msg);
  }
}

function _esc(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}
