"""Optional Obsidian plugin search integrations (hybrid mode only).

Smart Connections and Omnisearch provide semantic *similarity* boosts from on-disk
caches — they are not used for [[wikilink]] resolution (see vault_graph.py).
Local REST API requires Obsidian running; skipped in filesystem mode.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from src.obsidian_vault import VaultConfig

logger = logging.getLogger(__name__)

SC_MODEL = "TaylorAI/bge-micro-v2"
_sc_cache: Dict[str, Tuple[float, Dict[str, Any]]] = {}


def detect_obsidian_plugins(config: VaultConfig) -> Dict[str, bool]:
    obsidian = config.root / ".obsidian"
    enabled: set = set()
    try:
        raw = (obsidian / "community-plugins.json").read_text(encoding="utf-8")
        enabled = set(json.loads(raw))
    except Exception:
        pass

    plugins_dir = obsidian / "plugins"
    installed = {p.name for p in plugins_dir.iterdir()} if plugins_dir.is_dir() else set()

    return {
        "dataview": "dataview" in enabled or "dataview" in installed,
        "smart_connections": "smart-connections" in enabled or "smart-connections" in installed,
        "omnisearch": "omnisearch" in enabled or "omnisearch" in installed,
        "local_rest_api": "obsidian-local-rest-api" in enabled or "obsidian-local-rest-api" in installed,
    }


def _load_local_rest_config(config: VaultConfig) -> Optional[dict]:
    path = config.root / ".obsidian" / "plugins" / "obsidian-local-rest-api" / "data.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def search_local_rest_api(
    config: VaultConfig,
    query: str,
    *,
    limit: int = 10,
    timeout: float = 3.0,
) -> List[Tuple[str, float, str]]:
    """Query Obsidian Local REST API /search/simple/ when Obsidian is running."""
    cfg = _load_local_rest_config(config)
    if not cfg:
        return []
    api_key = (cfg.get("apiKey") or "").strip()
    port = int(cfg.get("port") or 27124)
    if not api_key:
        return []

    url = f"https://127.0.0.1:{port}/search/simple/"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        import httpx

        with httpx.Client(verify=False, timeout=timeout) as client:
            resp = client.post(url, headers=headers, json={"query": query, "contextLength": 100})
            if resp.status_code != 200:
                return []
            data = resp.json()
    except Exception as e:
        logger.debug(f"Local REST API search unavailable: {e}")
        return []

    hits: List[Tuple[str, float, str]] = []
    files = data if isinstance(data, list) else data.get("files") or data.get("results") or []
    for i, item in enumerate(files[:limit]):
        if isinstance(item, str):
            rel = item.replace("\\", "/")
            hits.append((rel, max(0.5, 1.0 - i * 0.05), ""))
            continue
        if not isinstance(item, dict):
            continue
        rel = (item.get("path") or item.get("filename") or item.get("file") or "").replace("\\", "/")
        if not rel:
            continue
        snippet = (item.get("content") or item.get("snippet") or item.get("match") or "")[:200]
        score = float(item.get("score") or max(0.5, 1.0 - i * 0.05))
        hits.append((rel, score, snippet.replace("\n", " ").strip()))
    return hits


def _smart_env_path(config: VaultConfig) -> Path:
    return config.root / ".smart-env"


def _load_smart_connections_index(config: VaultConfig) -> Dict[str, Any]:
    key = str(config.root)
    env = _smart_env_path(config)
    mtime = env.stat().st_mtime if env.is_dir() else 0.0
    cached = _sc_cache.get(key)
    if cached and cached[0] == mtime:
        return cached[1]

    index: Dict[str, Any] = {}
    multi = env / "multi"
    if not multi.is_dir():
        _sc_cache[key] = (mtime, index)
        return index

    vec_re = re.compile(r'"vec":\[([^\]]+)\]')
    path_re = re.compile(r'"path":"([^"]+)"')

    for ajson in multi.glob("*.ajson"):
        try:
            text = ajson.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        pm = path_re.search(text)
        vm = vec_re.search(text)
        if not pm or not vm:
            continue
        rel = pm.group(1).replace("\\", "/")
        try:
            import numpy as np

            vec = np.array([float(x) for x in vm.group(1).split(",")], dtype=np.float32)
        except (ValueError, ImportError):
            continue
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        index[rel] = vec

    _sc_cache[key] = (mtime, index)
    logger.info(f"Smart Connections index loaded: {len(index)} notes")
    return index


def _embed_query_bge_micro(query: str) -> Optional[Any]:
    try:
        import numpy as np
        from fastembed import TextEmbedding

        model = TextEmbedding(model_name=SC_MODEL)
        vec = next(model.embed([query]))
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        return arr / norm if norm > 0 else arr
    except Exception as e:
        logger.debug(f"Smart Connections query embed failed: {e}")
        return None


def search_smart_connections(
    config: VaultConfig,
    query: str,
    *,
    limit: int = 10,
) -> List[Tuple[str, float, str]]:
    """Semantic search using Smart Connections' precomputed embeddings."""
    plugins = detect_obsidian_plugins(config)
    if not plugins.get("smart_connections"):
        return []
    index = _load_smart_connections_index(config)
    if not index:
        return []
    qvec = _embed_query_bge_micro(query)
    if qvec is None:
        return []

    try:
        import numpy as np
    except ImportError:
        return []

    scored: List[Tuple[str, float]] = []
    for rel, vec in index.items():
        if getattr(vec, "shape", None) is None or vec.shape[0] != qvec.shape[0]:
            continue
        sim = float(np.dot(qvec, vec))
        if sim > 0.25:
            scored.append((rel, sim))
    scored.sort(key=lambda x: (-x[1], x[0].lower()))
    return [(rel, sc, "smart-connections semantic match") for rel, sc in scored[:limit]]


def _load_omnisearch_index(config: VaultConfig) -> List[dict]:
    plugin_dir = config.root / ".obsidian" / "plugins" / "omnisearch"
    candidates = [
        plugin_dir / "data.json",
        plugin_dir / "cache.json",
        plugin_dir / "index.json",
        config.root / ".obsidian" / "omnisearch-cache.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            for key in ("documents", "files", "index", "cache"):
                val = data.get(key)
                if isinstance(val, list):
                    return [x for x in val if isinstance(x, dict)]
    return []


def search_omnisearch_cache(
    config: VaultConfig,
    query: str,
    *,
    limit: int = 10,
) -> List[Tuple[str, float, str]]:
    """Search Omnisearch on-disk cache when the plugin is installed."""
    if not detect_obsidian_plugins(config).get("omnisearch"):
        return []
    docs = _load_omnisearch_index(config)
    if not docs:
        return []

    q = query.lower().strip()
    tokens = [t for t in re.split(r"\W+", q) if len(t) >= 3]
    hits: List[Tuple[str, float, str]] = []

    for doc in docs:
        rel = (doc.get("path") or doc.get("file") or doc.get("basename") or "").replace("\\", "/")
        title = (doc.get("title") or doc.get("basename") or Path(rel).stem if rel else "")
        body = (doc.get("content") or doc.get("text") or doc.get("excerpt") or "")
        hay = f"{title} {body}".lower()
        score = 0.0
        if q and q in hay:
            score += 2.0
        for tok in tokens:
            if tok in hay:
                score += 1.0
        if rel and score > 0:
            hits.append((rel, score, body[:160].replace("\n", " ")))

    hits.sort(key=lambda x: (-x[1], x[0].lower()))
    max_sc = hits[0][1] if hits else 1.0
    return [(rel, sc / max_sc, sn) for rel, sc, sn in hits[:limit]]


def search_plugin_sources(
    config: VaultConfig,
    query: str,
    *,
    limit: int = 8,
) -> Dict[str, List[Tuple[str, float, str]]]:
    """Run all available plugin search backends."""
    out: Dict[str, List[Tuple[str, float, str]]] = {}
    plugins = detect_obsidian_plugins(config)
    if plugins.get("local_rest_api"):
        rest = search_local_rest_api(config, query, limit=limit)
        if rest:
            out["local_rest_api"] = rest
    if plugins.get("smart_connections"):
        sc = search_smart_connections(config, query, limit=limit)
        if sc:
            out["smart_connections"] = sc
    if plugins.get("omnisearch"):
        omni = search_omnisearch_cache(config, query, limit=limit)
        if omni:
            out["omnisearch"] = omni
    return out
