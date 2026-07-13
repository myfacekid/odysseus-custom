/**
 * Shared editor chrome helpers (P4).
 */
import { bindMarkdownFormatToolbar } from './mdFormat.js';

const FORMAT_BTN_HTML =
  '<button type="button" class="md-dd-toggle doc-action-icon-btn" data-dd="format" ' +
  'title="Format (bold, headings, lists)" aria-label="Format">' +
  '<b style="font-style:italic;">A</b>' +
  '<svg width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
  'stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round">' +
  '<polyline points="6 9 12 15 18 9"/></svg></button>';

export function formatButtonHtml() {
  return FORMAT_BTN_HTML;
}

/**
 * @param {HTMLElement | null} wrap — container holding the format button
 * @param {() => HTMLTextAreaElement | null} getTextarea
 */
export function wireMarkdownFormat(wrap, getTextarea) {
  if (!wrap) return;
  bindMarkdownFormatToolbar(wrap, getTextarea);
}

export default { formatButtonHtml, wireMarkdownFormat };
