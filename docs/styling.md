# Nobody styling guide — raised stamps

Nobody’s chrome is a **3D stamp**: a filled plate with a hard bottom-right drop, no blur, and no four-sided hairline. This guide is how to make new controls match the ones already in the app.

Default paper is light **Modus Operandi Tinted** (`--bg` / `--panel`). Appearance work goes through the theme system; do not hard-code a parallel palette.

## Tokens

Defined near the top of `static/style.css`, with ink strength tuned at runtime by `stampShadowInks()` in `static/js/color/hex.js` (applied from `theme.js`):

| Token | Role |
| --- | --- |
| `--shadow-ink` | Translucent **black** drop at rest (not `--fg`, not an opaque panel shade) |
| `--shadow-press-ink` | Slightly softer black for the seated state |
| `--shadow-hard` | `2px 2px 0 var(--shadow-ink)` — the raise |
| `--shadow-press` | `1px 1px 0 var(--shadow-press-ink)` — pressed |
| `--radius-tech` | `2px` corners |
| `--panel` / `--fg` / `--accent` (`--red`) | Fill, type, icon ink |

Light surfaces use ~18% black; darker themes raise alpha so the drop still reads. Always black + alpha.

## Recipe A — labeled raised button

Use for text actions: `.btn`, `.admin-btn-sm`, `.confirm-btn`, send, empty-state CTAs, toolbar labeled chips, etc.

```css
border: 1px solid transparent;          /* not var(--border) */
border-radius: var(--radius-tech, 2px);
background: var(--panel);               /* or panel mix / accent fill */
color: var(--fg);
box-shadow: var(--shadow-hard);
/* hover: wash the fill only; keep border transparent */
/* active: */
transform: translate(1px, 1px);
box-shadow: var(--shadow-press);
```

**Why transparent border?** A visible 1px stroke on all four sides reads as lines on the lit (top/left) edges. The raise is the bottom-right drop only.

**Typography for compact chrome:** `--font-ui` (Iosevka), uppercase + `--tracking-label` where the existing `.btn` family does. Reading surfaces may use `--font-family`.

**Flush joins:** square the shared edge with `.btn-flush-start` / `.btn-flush-end`. Stacked choice lists use `.btn-stack` (4px gap), not a single fused card.

Reuse an existing class. Do not invent a one-off “almost `.btn`” stylesheet.

## Recipe B — icon stamp well

Use when the control is an **icon**, not a labeled plate: icon rail, expanded sidebar Search / New Chat / tool rows, Chats & Tools section headers, session list icons.

- Row stays **flat** (transparent background, no row shadow).
- Stamp lives on a **fixed square well** (24×24 desktop, larger on mobile touch rows).
- Icon color is `--accent`; well fill is `color-mix(in srgb, var(--panel) 92%, var(--fg))` plus `--shadow-hard`.
- Glyph centered: direct SVGs use equal padding + `box-sizing: border-box`; nested wells (e.g. `.session-icon`) are `inline-flex` + centered child SVG with `display: block`.
- Press: translate + `--shadow-press` on the **well**, not the whole row.

Collapsed rail and expanded sidebar must read as the **same icon language**. Keep action **order** aligned (Search → New Chat, then tools).

Trailing meta on expanded rows (shortcut chip, `›`, Library `+`) is quiet chrome — not a second stamp plate unless it is itself a small control (e.g. Library `+`).

## Recipe C — joined segment bar

Agent / Plan / Chat and Ask / Auto: **one** stamped track (`.mode-toggle` / `.perm-toggle`), segments flush inside, sliding pill via CSS variables. Do not stamp each segment as its own floating plate.

## Recipe D — hard seams & separators

Sidebar / icon rail outer edge: hard offset seam (`2px 0 0` / `-2px 0 0` with `--shadow-ink`), not a hairline border. Small stamped separators (rail dividers, tool subgroup rules) use the same ink language at a smaller scale.

## Do / don’t

| Do | Don’t |
| --- | --- |
| Reuse `.btn` / toolbar / rail classes | New button CSS that almost matches |
| Transparent stroke + hard drop | Four-sided `border: 1px solid var(--border)` on raised plates |
| `--shadow-ink` (black + alpha) | `--fg`-tinted or solid panel “shadow” |
| Stamp icons only in nav lists | Full-row plates behind Search / tools / chats |
| Inline SVG, monochrome | Unicode emoji in UI |
| Extend existing patterns | Parallel widgets for the same job |

## Where it lives

| Piece | Location |
| --- | --- |
| Tokens + labeled primitive | `static/style.css` (Blueprint primitives) |
| Icon rail + sidebar chrome | same file — search “Sidebar chrome rows” / `.icon-rail-btn` |
| Shadow ink helper | `static/js/color/hex.js` → `stampShadowInks` |
| Theme wiring | `static/js/theme.js` |
| Tools / Chats collapse cascade | `static/js/section-management.js` + `.section-just-expanded` / `.section-just-collapsing` (includes `.tool-subgroup-label` / `.tool-subgroup-sep`) |

## Lock-in tests

```bash
node --test tests/ui/blueprint-buttons.test.mjs
node --test tests/ui/stamp-shadow.test.mjs
node --test tests/ui/typography.test.mjs
```

If you change the stamp recipe, update these tests in the same PR.

## PR checklist (visual)

See [CONTRIBUTING.md](../CONTRIBUTING.md) and the PR template: run the app, attach a screenshot, reuse tokens/classes, no emoji, no parallel components.
