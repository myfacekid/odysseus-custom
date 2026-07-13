/**
 * Shared markdown formatting for textarea editors (U3 / P4).
 * Extracted from document.js so Documents and Projects can share one implementation.
 */

let _lastMdFormat = { action: null, t: 0 };
let _mdDdOpenedAt = 0;

export const FORMAT_MENU_ITEMS = [
  ['bold', 'Bold', '**'], ['italic', 'Italic', '*'], ['strike', 'Strikethrough', '~~'],
  ['h1', 'Heading 1', 'H1'], ['h2', 'Heading 2', 'H2'], ['h3', 'Heading 3', 'H3'],
  ['ul', 'Bullet list', '•'], ['ol', 'Numbered list', '1.'],
  ['code', 'Inline code', '`'], ['codeblock', 'Code block', '```'],
  ['link', 'Link', '[ ]'], ['hr', 'Horizontal rule', '—'],
];

function replaceRange(ta, from, to, text) {
  ta.focus();
  ta.selectionStart = from;
  ta.selectionEnd = to;
  const before = ta.value;
  let ok = false;
  try { ok = document.execCommand('insertText', false, text); } catch { ok = false; }
  if (!ok && ta.value === before) {
    ta.value = before.slice(0, from) + text + before.slice(to);
    ta.selectionStart = ta.selectionEnd = from + text.length;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
  }
}

function applyWrapToggle(ta, before, sel, after, start, end, mark) {
  const mLen = mark.length;
  if (sel.startsWith(mark) && sel.endsWith(mark) && sel.length > mLen * 2) {
    const inner = sel.slice(mLen, -mLen);
    replaceRange(ta, start, end, inner);
    ta.selectionStart = start;
    ta.selectionEnd = start + inner.length;
    return;
  }
  if (before.endsWith(mark) && after.startsWith(mark)) {
    replaceRange(ta, start - mLen, end + mLen, sel);
    ta.selectionStart = start - mLen;
    ta.selectionEnd = end - mLen;
    return;
  }
  const inner = sel;
  const wrapped = mark + inner + mark;
  replaceRange(ta, start, end, wrapped);
  ta.selectionStart = start + mLen;
  ta.selectionEnd = start + mLen + inner.length;
}

function applyHeadingToggle(ta, caret, prefix) {
  const val = ta.value;
  const lineStart = val.lastIndexOf('\n', caret - 1) + 1;
  const nlIdx = val.indexOf('\n', caret);
  const lineEnd = nlIdx === -1 ? val.length : nlIdx;
  const line = val.substring(lineStart, lineEnd);
  const m = line.match(/^(#{1,6}) /);
  let newLine;
  if (m && m[1].length === prefix.trim().length) {
    newLine = line.slice(m[0].length);
  } else if (m) {
    newLine = prefix + line.slice(m[0].length);
  } else {
    newLine = prefix + line;
  }
  replaceRange(ta, lineStart, lineEnd, newLine);
  const delta = newLine.length - line.length;
  const pos = Math.max(lineStart, caret + delta);
  ta.selectionStart = ta.selectionEnd = pos;
  ta.focus();
}

function applyLinePrefixToggle(ta, start, end, prefix) {
  const val = ta.value;
  const sel = val.substring(start, end);
  const lineStart = val.lastIndexOf('\n', start - 1) + 1;

  if (sel) {
    const lines = sel.split('\n');
    const nonEmpty = lines.filter((l) => l.trim());
    const allPrefixed = nonEmpty.length > 0 && nonEmpty.every((l) => l.startsWith(prefix));
    const result = allPrefixed
      ? lines.map((l) => (l.startsWith(prefix) ? l.slice(prefix.length) : l)).join('\n')
      : lines.map((l) => (l.trim() ? prefix + l : l)).join('\n');
    replaceRange(ta, start, end, result);
    ta.selectionStart = start;
    ta.selectionEnd = start + result.length;
  } else {
    const lineBefore = val.substring(lineStart, start);
    if (lineBefore.startsWith(prefix)) {
      replaceRange(ta, lineStart, lineStart + prefix.length, '');
    } else {
      replaceRange(ta, lineStart, lineStart, prefix);
    }
  }
}

function applyOrderedList(ta, start, end) {
  const val = ta.value;
  const sel = val.substring(start, end);
  const lineStart = val.lastIndexOf('\n', start - 1) + 1;

  if (sel) {
    const lines = sel.split('\n');
    const nonEmpty = lines.filter((l) => l.trim());
    const allNumbered = nonEmpty.length > 0 && nonEmpty.every((l) => /^\d+\.\s/.test(l));
    const result = allNumbered
      ? lines.map((l) => l.replace(/^\d+\.\s/, '')).join('\n')
      : (() => { let n = 0; return lines.map((l) => (l.trim() ? `${++n}. ${l}` : l)).join('\n'); })();
    replaceRange(ta, start, end, result);
    ta.selectionStart = start;
    ta.selectionEnd = start + result.length;
  } else {
    const lineBefore = val.substring(lineStart, start);
    if (/^\d+\.\s/.test(lineBefore)) {
      const prefixLen = lineBefore.match(/^\d+\.\s/)[0].length;
      replaceRange(ta, lineStart, lineStart + prefixLen, '');
    } else {
      const prevText = val.substring(0, lineStart);
      const prevMatch = prevText.match(/(\d+)\.\s[^\n]*\n$/);
      const num = prevMatch ? parseInt(prevMatch[1], 10) + 1 : 1;
      replaceRange(ta, lineStart, lineStart, `${num}. `);
    }
  }
}

/**
 * Apply a markdown formatting action to a textarea.
 * @param {HTMLTextAreaElement} ta
 * @param {string} action
 */
export function applyMdFormat(ta, action) {
  if (!ta) return;
  const now = Date.now();
  if (_lastMdFormat.action === action && now - _lastMdFormat.t < 350) return;
  _lastMdFormat = { action, t: now };

  const start = ta.selectionStart;
  const end = ta.selectionEnd;
  const val = ta.value;
  const sel = val.substring(start, end);
  const before = val.substring(0, start);
  const after = val.substring(end);

  const wrapMarks = { bold: '**', italic: '*', strike: '~~', code: '`' };
  if (wrapMarks[action]) {
    applyWrapToggle(ta, before, sel, after, start, end, wrapMarks[action]);
    return;
  }

  if (action === 'ol') {
    applyOrderedList(ta, start, end);
    return;
  }

  if (action === 'h1' || action === 'h2' || action === 'h3') {
    applyHeadingToggle(ta, start, { h1: '# ', h2: '## ', h3: '### ' }[action]);
    return;
  }

  const prefixMap = { quote: '> ', ul: '- ', check: '- [ ] ' };
  if (prefixMap[action]) {
    applyLinePrefixToggle(ta, start, end, prefixMap[action]);
    return;
  }

  let insert = '';
  let sS = start;
  let sE = start;
  switch (action) {
    case 'link':
      if (sel) {
        insert = `[${sel}](url)`;
        sS = start + 1;
        sE = start + 1 + sel.length;
      } else {
        insert = '[text](url)';
        sS = start + 1;
        sE = start + 5;
      }
      break;
    case 'codeblock': {
      const linesBefore = val.substring(0, start).split('\n');
      const linesAfter = val.substring(end).split('\n');
      let openIdx = -1;
      for (let i = linesBefore.length - 1; i >= 0; i--) {
        if (/^```/.test(linesBefore[i].trimEnd())) { openIdx = i; break; }
      }
      let closeIdx = -1;
      for (let i = 0; i < linesAfter.length; i++) {
        if (/^```\s*$/.test(linesAfter[i].trimEnd())) { closeIdx = i; break; }
      }
      if (openIdx >= 0 && closeIdx >= 0) {
        const openLineStart = linesBefore.slice(0, openIdx).join('\n').length + (openIdx > 0 ? 1 : 0);
        const openLineEnd = openLineStart + linesBefore[openIdx].length + 1;
        const closeLineStart = end + linesAfter.slice(0, closeIdx).join('\n').length + (closeIdx > 0 ? 1 : 0);
        const closeLineEnd = closeLineStart + linesAfter[closeIdx].length + (closeIdx < linesAfter.length - 1 ? 1 : 0);
        replaceRange(ta, closeLineStart, closeLineEnd, '');
        replaceRange(ta, openLineStart, openLineEnd, '');
        const inner = val.substring(openLineEnd, closeLineStart);
        ta.selectionStart = openLineStart;
        ta.selectionEnd = openLineStart + inner.length;
        return;
      }
      const nl = before.length > 0 && !before.endsWith('\n') ? '\n' : '';
      insert = `${nl}\`\`\`\n${sel || ''}\n\`\`\`\n`;
      sS = start + nl.length + 4;
      sE = sS + (sel ? sel.length : 0);
      break;
    }
    case 'hr': {
      const nl = before.length > 0 && !before.endsWith('\n') ? '\n' : '';
      insert = `${nl}---\n`;
      sE = sS = start + insert.length;
      break;
    }
    default:
      return;
  }
  replaceRange(ta, start, end, insert);
  ta.selectionStart = sS;
  ta.selectionEnd = sE;
}

/**
 * @param {HTMLButtonElement} toggleBtn
 * @param {(action: string) => void} onFormat
 * @param {string} [menuId]
 */
export function showMdFormatDropdown(toggleBtn, onFormat, menuId = 'md-format-dd-menu') {
  const kind = toggleBtn.dataset.dd || 'format';
  const now = Date.now();
  const existing = document.getElementById(menuId);
  if (existing && existing.dataset.dd === kind && (now - _mdDdOpenedAt) < 400) return;
  const prevKind = existing && existing.dataset.dd;
  if (existing) existing.remove();
  if (existing && prevKind === kind) return;
  _mdDdOpenedAt = now;

  const items = FORMAT_MENU_ITEMS;
  const rect = toggleBtn.getBoundingClientRect();
  const menu = document.createElement('div');
  menu.id = menuId;
  menu.dataset.dd = kind;
  menu.className = 'doc-overflow-menu open';
  menu.style.position = 'fixed';
  menu.style.top = `${rect.bottom + 4}px`;
  menu.style.left = `${rect.left}px`;
  menu.style.zIndex = '9999';

  items.forEach(([md, label, ico]) => {
    const it = document.createElement('button');
    it.className = 'doc-overflow-item';
    const icoSpan = document.createElement('span');
    icoSpan.className = 'md-dd-ico';
    icoSpan.textContent = ico;
    const lbl = document.createElement('span');
    lbl.textContent = label;
    it.append(icoSpan, lbl);
    it.addEventListener('mousedown', (ev) => ev.preventDefault());
    it.addEventListener('click', (ev) => {
      ev.stopPropagation();
      menu.remove();
      onFormat(md);
    });
    menu.appendChild(it);
  });
  document.body.appendChild(menu);

  const close = (ev) => {
    if (ev && ev.type === 'keydown') {
      if (ev.key !== 'Escape') return;
      ev.preventDefault();
      ev.stopPropagation();
      ev.stopImmediatePropagation?.();
    }
    if (ev && ev.type === 'click') {
      if (Date.now() - _mdDdOpenedAt < 400) return;
      if (menu.contains(ev.target) || toggleBtn.contains(ev.target)) return;
    }
    menu.remove();
    document.removeEventListener('click', close, true);
    document.removeEventListener('keydown', close, true);
    window.removeEventListener('scroll', close, true);
    window.removeEventListener('resize', close, true);
  };
  setTimeout(() => {
    document.addEventListener('click', close, true);
    document.addEventListener('keydown', close, true);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close, true);
  }, 0);
}

/**
 * Wire Format popover + keyboard shortcuts on a toolbar root.
 * @param {HTMLElement} toolbar
 * @param {() => HTMLTextAreaElement | null} getTextarea
 */
export function bindMarkdownFormatToolbar(toolbar, getTextarea) {
  if (!toolbar || toolbar.dataset.mdFormatBound) return;
  toolbar.dataset.mdFormatBound = '1';

  toolbar.addEventListener('mousedown', (e) => {
    if (e.target.closest('.md-dd-toggle, [data-md]')) e.preventDefault();
  });

  toolbar.addEventListener('click', (e) => {
    const dd = e.target.closest('.md-dd-toggle');
    if (dd) {
      e.preventDefault();
      showMdFormatDropdown(dd, (action) => {
        const ta = getTextarea();
        if (ta) applyMdFormat(ta, action);
      });
      return;
    }
    const btn = e.target.closest('[data-md]');
    if (!btn) return;
    e.preventDefault();
    const ta = getTextarea();
    if (ta) applyMdFormat(ta, btn.dataset.md);
  });

  toolbar.addEventListener('keydown', (e) => {
    if (!(e.ctrlKey || e.metaKey)) return;
    const ta = getTextarea();
    if (!ta) return;
    if (e.key === 'b') { e.preventDefault(); applyMdFormat(ta, 'bold'); }
    else if (e.key === 'i') { e.preventDefault(); applyMdFormat(ta, 'italic'); }
    else if (e.key === 'k') { e.preventDefault(); applyMdFormat(ta, 'link'); }
  });
}

export default {
  applyMdFormat,
  showMdFormatDropdown,
  bindMarkdownFormatToolbar,
  FORMAT_MENU_ITEMS,
};
