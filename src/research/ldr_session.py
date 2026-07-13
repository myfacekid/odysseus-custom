"""Handler-compatible session object for LDR research runs."""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Set

from src.research_evidence import EvidenceRegistry


class LdrResearchSession:
    """Mimics DeepResearcher surface used by ResearchHandler persistence."""

    def __init__(
        self,
        *,
        llm_model: str,
        include_preprints: bool = True,
        include_zotero: bool = True,
        owner: str = "",
    ):
        self.llm_model = llm_model
        self.include_preprints = include_preprints
        self.include_zotero = include_zotero
        self.owner = owner
        self.evidence_registry = EvidenceRegistry()
        self.findings: List[dict] = []
        self.evolving_report: str = ""
        self.urls_fetched: Set[str] = set()
        self.dois_seen: Set[str] = set()
        self.queries_used: Set[str] = set()
        self.providers_used: List[str] = []
        self.round_count: int = 0
        self.verification_summary: Optional[Dict] = None
        self._start_time = time.time()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def get_stats(self) -> Dict:
        elapsed = time.time() - self._start_time
        stats = {
            "Duration": f"{elapsed:.1f}s",
            "Rounds": self.round_count,
            "Queries": len(self.queries_used),
            "URLs": len(self.urls_fetched),
            "Sources": len(self.evidence_registry),
            "Model": self.llm_model,
            "Engine": "LDR LangGraph",
        }
        if self.providers_used:
            stats["Search"] = ", ".join(self.providers_used)
        stats["Mode"] = "Academic"
        if not self.include_preprints:
            stats["Preprints"] = "Excluded"
        if self.include_zotero and self.owner:
            try:
                from src.zotero_client import resolve_zotero_credentials

                if resolve_zotero_credentials(self.owner):
                    stats["Zotero"] = "Included"
            except Exception:
                pass
        return stats
