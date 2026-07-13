"""User preferences for learned graph connections (L1).

Mirrors Brain → Settings skills toggles. Producers enqueue and emit batch
pop-ups only when ``auto_learn_links`` is on. ``auto_approve_links`` is stored
for future use but must remain inert in v1 (no silent edge publication).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

DEFAULT_AUTO_LEARN_LINKS = True
DEFAULT_AUTO_APPROVE_LINKS = False
DEFAULT_LINK_MIN_CONFIDENCE = 0.85


def load_learned_link_prefs(owner: Optional[str] = None) -> Dict[str, Any]:
    try:
        from routes.prefs_routes import _load_for_user

        prefs = _load_for_user(owner) or {}
    except Exception:
        prefs = {}
    try:
        min_conf = float(prefs.get("link_min_confidence", DEFAULT_LINK_MIN_CONFIDENCE))
    except (TypeError, ValueError):
        min_conf = DEFAULT_LINK_MIN_CONFIDENCE
    return {
        "auto_learn_links": bool(prefs.get("auto_learn_links", DEFAULT_AUTO_LEARN_LINKS)),
        "auto_approve_links": bool(prefs.get("auto_approve_links", DEFAULT_AUTO_APPROVE_LINKS)),
        "link_min_confidence": max(0.0, min(1.0, min_conf)),
    }


def producer_enqueue_allowed(owner: Optional[str], *, user_initiated: bool = False) -> bool:
    """Whether automatic producers may enqueue or surface batch link proposals."""
    if user_initiated:
        return True
    return load_learned_link_prefs(owner)["auto_learn_links"]


def should_emit_batch_link_proposals(owner: Optional[str]) -> bool:
    """Whether agent/research SSE may dispatch graph_merge_proposals."""
    return producer_enqueue_allowed(owner)


def auto_approve_links_enabled(owner: Optional[str] = None) -> bool:
    """v1 policy: never auto-publish edges from proposals."""
    _ = owner
    return False
