/**
 * Shared content viewer (U8 — workspace shell / modal reduction).
 *
 * One place that turns a piece of content — PDF, markdown, code, or plain text —
 * into a DOM body, so Library, the Projects center pane, and other surfaces
 * present documents & reports the same way instead of each hand-rolling its own
 * <pre>/hljs/iframe block.
 *
 * Design: each factory RETURNS a detached element; callers insert it and keep
 * ownership of the surrounding chrome (action bars, fades, empty states). That
 * means adopting this module never disturbs a caller's existing layout logic —
 * it only unifies the "how do I render this body" decision.
 */
import markdownModule from '../markdown.js';
import uiModule from '../ui.js';

function esc(s) {
  if (uiModule && typeof uiModule.esc === 'function') return uiModule.esc(String(s ?? ''));
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// highlight.js is synchronous and O(n); skip it past this size so previews open
// instantly instead of freezing the main thread on a large file.
export const HL_CAP = 20000;
// mdToHtml on a multi-MB document can jank the main thread just like hljs; above
// this size fall back to a plain <pre> (still complete, just not formatted).
export const MD_CAP = 200000;

/** Render a PDF via iframe. `url` should already be fully-qualified. */
export function createPdf({ url, height = '60vh', className = 'content-view-pdf' } = {}) {
  const frame = document.createElement('iframe');
  if (className) frame.className = className;
  frame.src = url;
  frame.style.cssText =
    `width:100%;height:${height};border:1px solid var(--border);border-radius:6px;background:var(--bg);`;
  return frame;
}

/**
 * Render source into <pre><code>, syntax-highlighting when possible.
 * `skipHighlightLangs` lets a caller opt a language out of hljs (e.g. Library
 * intentionally shows markdown source plain rather than highlighted).
 */
export function createCode({
  content = '',
  language = 'text',
  cap = HL_CAP,
  skipHighlightLangs = [],
  className = '',
} = {}) {
  const pre = document.createElement('pre');
  if (className) pre.className = className;
  const code = document.createElement('code');
  const lang = (language || 'text').toLowerCase();
  const canHighlight =
    !!window.hljs &&
    lang && lang !== 'text' && lang !== 'plaintext' &&
    !skipHighlightLangs.includes(lang) &&
    content.length <= cap;
  try {
    if (canHighlight) {
      code.className = `hljs language-${lang}`;
      code.innerHTML = window.hljs.highlight(content, { language: lang }).value;
    } else {
      code.textContent = content;
    }
  } catch {
    code.textContent = content;
  }
  pre.appendChild(code);
  return pre;
}

/**
 * Render markdown to formatted HTML (reusing the app's `.doc-md-preview`
 * styles). Falls back to plain source for very large docs or if the markdown
 * module is unavailable.
 */
export function createMarkdown({ content = '', cap = MD_CAP, className = 'doc-md-preview content-view-md' } = {}) {
  if (content.length > cap || !(markdownModule && typeof markdownModule.mdToHtml === 'function')) {
    return createCode({ content, language: 'text' });
  }
  const div = document.createElement('div');
  if (className) div.className = className;
  try {
    div.innerHTML = markdownModule.mdToHtml(content);
    if (window.hljs) {
      div.querySelectorAll('pre code').forEach((block) => {
        try { window.hljs.highlightElement(block); } catch { /* leave as-is */ }
      });
    }
  } catch {
    return createCode({ content, language: 'text' });
  }
  return div;
}

/** Dispatch to the right factory by `kind`. */
export function createContent(spec = {}) {
  switch (spec.kind) {
    case 'pdf': return createPdf(spec);
    case 'markdown': return createMarkdown(spec);
    case 'code': return createCode(spec);
    case 'text':
    default: return createCode({ ...spec, language: 'text' });
  }
}

/**
 * Swap a rendered body into a container, removing any previous body
 * (`<pre>`, `<iframe>`, or `.doc-md-preview`) while leaving other chrome — e.g.
 * an actions bar — in place. Optionally re-appends `actionsBar` so it stays last.
 */
export function mountBody(container, el, { actionsBar = null, before = null } = {}) {
  if (!container || !el) return el;
  container.querySelectorAll(':scope > pre, :scope > iframe, :scope > .doc-md-preview')
    .forEach((n) => n.remove());
  container.insertBefore(el, before || container.firstChild);
  if (actionsBar && !container.contains(actionsBar)) container.appendChild(actionsBar);
  return el;
}

export default { HL_CAP, MD_CAP, createPdf, createCode, createMarkdown, createContent, mountBody };
