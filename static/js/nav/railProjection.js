// Renders the icon-rail tool launchers from the single-source-of-truth tool
// registry. Loaded before app.js so the generated rail buttons exist by the
// time app.js wires their delegation and other modules query them by id.
import { mountRailTools, checkNavParity } from './toolRegistry.js';
import { initTooltips } from '../ui/tooltip.js';

mountRailTools();

// Sidebar owners are parsed before these bottom-of-body module scripts run, so
// the parity check is meaningful at this point.
checkNavParity();

// U6: the icon rail is icon-only, so give every rail button the shared,
// touch-friendly tooltip (consumes each button's `title`) and an aria-label.
const rail = document.getElementById('icon-rail');
if (rail) initTooltips(rail);
