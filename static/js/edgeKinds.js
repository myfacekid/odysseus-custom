/**
 * Shared visual vocabulary for knowledge-graph edge kinds.
 *
 * A single source of truth so the graph canvas, the legend, the detail link
 * rows, and the add-link picker all use the same colour + motif (glyph) for a
 * given relationship kind. Keeping this here avoids the colour/label drift that
 * comes from redefining the mapping in each surface.
 */

// color: shared by the edge line, its arrow, the midpoint glyph, and the badge
//        drawn on connected nodes.
// glyph: a compact motif drawn on the canvas and shown in the legend / chips.
// label: human-facing name.
export const EDGE_KINDS = {
  relates:       { label: 'Relates',      color: '#8aa0c0', glyph: '~' },
  derives_from:  { label: 'Derives from', color: '#e8974f', glyph: '↳' },
  supports:      { label: 'Supports',     color: '#4dd4ac', glyph: '+' },
  refutes:       { label: 'Refutes',      color: '#e06c75', glyph: '×' },
  depends_on:    { label: 'Depends on',   color: '#c084fc', glyph: '→' },
  summarizes:    { label: 'Summarizes',   color: '#6b8cff', glyph: '≡' },
  in_collection: { label: 'Collection',   color: '#f4d160', glyph: '▤' },
  parent:        { label: 'Parent',       color: '#66bb88', glyph: '↑' },
  wikilink:      { label: 'Wikilink',     color: '#57b0d4', glyph: '※' },
  link:          { label: 'Link',         color: '#8aa0c0', glyph: '·' },
  related:       { label: 'Related',      color: '#8aa0c0', glyph: '·' },
};

export const DEFAULT_EDGE_KIND = { label: 'Link', color: '#8aa0c0', glyph: '·' };

/** Resolve an edge kind string to its {label, color, glyph} descriptor. */
export function edgeKind(kind) {
  return EDGE_KINDS[(kind || '').toLowerCase()] || DEFAULT_EDGE_KIND;
}

export default { EDGE_KINDS, DEFAULT_EDGE_KIND, edgeKind };
