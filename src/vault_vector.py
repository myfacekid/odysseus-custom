"""Vector semantic index for Obsidian vault notes (ChromaDB)."""
from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from src.obsidian_vault import VaultConfig, _iter_notes
from src.vault_note_parser import parse_note

logger = logging.getLogger(__name__)

COLLECTION_NAME = "odysseus_vault"
VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3


class VaultVectorIndex:
    """Chunked vector index scoped to one vault root."""

    def __init__(self):
        self._collection = None
        self._model = None
        self._healthy = False
        self._initialize()

    def _initialize(self) -> bool:
        try:
            from src.chroma_client import get_chroma_client
            from src.embeddings import get_embedding_client

            self._model = get_embedding_client()
            if self._model is None:
                return False
            client = get_chroma_client()
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            self._healthy = True
            return True
        except Exception as e:
            logger.debug(f"VaultVectorIndex unavailable: {e}")
            self._healthy = False
            return False

    @property
    def healthy(self) -> bool:
        return self._healthy and self._collection is not None

    def _embed(self, texts: List[str]) -> List[List[float]]:
        vecs = self._model.encode(texts, normalize_embeddings=True)
        return np.array(vecs, dtype=np.float32).tolist()

    @staticmethod
    def _split_chunks(text: str, chunk_size: int = 900, overlap: int = 150) -> List[str]:
        if not text:
            return []
        if len(text) <= chunk_size:
            return [text]
        sentences = re.split(r"(?<=[.!?])\s+|\n{2,}", text)
        sentences = [s.strip() for s in sentences if s.strip()]
        chunks: List[str] = []
        current: List[str] = []
        current_len = 0
        for sentence in sentences:
            slen = len(sentence)
            if slen > chunk_size:
                if current:
                    chunks.append(" ".join(current))
                    current, current_len = [], 0
                for start in range(0, slen, chunk_size - overlap):
                    chunks.append(sentence[start : start + chunk_size])
                continue
            if current_len + slen + 1 > chunk_size and current:
                chunks.append(" ".join(current))
                current, current_len = [], 0
            current.append(sentence)
            current_len += slen + 1
        if current:
            chunks.append(" ".join(current))
        return chunks or [text[:chunk_size]]

    def _chunk_id(self, vault_root: str, rel_path: str, chunk_idx: int) -> str:
        raw = f"{vault_root}::{rel_path}::{chunk_idx}"
        return "vault_" + hashlib.sha1(raw.encode()).hexdigest()[:20]

    def index_vault(self, config: VaultConfig, owner: str = "") -> Dict[str, Any]:
        if not self.healthy:
            return {"success": False, "message": "Vector index unavailable (Chroma/embeddings)"}

        vault_root = str(config.root)
        self._purge_vault(vault_root, owner)

        indexed = 0
        failed = 0
        batch_ids: List[str] = []
        batch_docs: List[str] = []
        batch_meta: List[dict] = []

        for rel, full in _iter_notes(config):
            try:
                text = full.read_text(encoding="utf-8", errors="replace")
            except OSError:
                failed += 1
                continue
            parsed = parse_note(rel, text)
            header = (
                f"Title: {parsed.title}\n"
                f"Tags: {', '.join(sorted(parsed.tags))}\n"
                f"Aliases: {', '.join(sorted(parsed.aliases))}\n\n"
            )
            for i, chunk in enumerate(self._split_chunks(parsed.body)):
                doc = header + chunk
                meta = {
                    "vault_root": vault_root,
                    "rel_path": rel,
                    "chunk_id": i,
                    "tags": ",".join(sorted(parsed.tags))[:500],
                    "mtime": int(full.stat().st_mtime),
                }
                if owner:
                    meta["owner"] = owner
                batch_ids.append(self._chunk_id(vault_root, rel, i))
                batch_docs.append(doc)
                batch_meta.append(meta)
                if len(batch_ids) >= 64:
                    if self._flush(batch_ids, batch_docs, batch_meta):
                        indexed += len(batch_ids)
                    else:
                        failed += len(batch_ids)
                    batch_ids, batch_docs, batch_meta = [], [], []

        if batch_ids:
            if self._flush(batch_ids, batch_docs, batch_meta):
                indexed += len(batch_ids)
            else:
                failed += len(batch_ids)

        return {
            "success": True,
            "indexed_count": indexed,
            "failed_count": failed,
            "message": f"Indexed {indexed} vault chunks from {vault_root}",
        }

    def _flush(self, ids: List[str], docs: List[str], metas: List[dict]) -> bool:
        try:
            embeddings = self._embed(docs)
            self._collection.upsert(
                ids=ids,
                embeddings=embeddings,
                documents=docs,
                metadatas=metas,
            )
            return True
        except Exception as e:
            logger.error(f"Vault vector flush failed: {e}")
            return False

    def _purge_note(self, vault_root: str, rel_path: str, owner: str = "") -> None:
        try:
            where: Dict[str, Any] = {"$and": [{"vault_root": vault_root}, {"rel_path": rel_path}]}
            if owner:
                where = {"$and": [{"vault_root": vault_root}, {"rel_path": rel_path}, {"owner": owner}]}
            existing = self._collection.get(where=where, include=[])
            if existing.get("ids"):
                self._collection.delete(ids=existing["ids"])
        except Exception as e:
            logger.debug(f"Vault vector note purge failed: {e}")

    def index_note(self, config: VaultConfig, rel_path: str, owner: str = "") -> bool:
        """Re-index a single note after create/edit."""
        if not self.healthy:
            return False
        vault_root = str(config.root)
        full = config.root / rel_path.replace("\\", "/")
        if not full.is_file():
            self._purge_note(vault_root, rel_path, owner)
            return True
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        self._purge_note(vault_root, rel_path, owner)
        parsed = parse_note(rel_path, text)
        header = (
            f"Title: {parsed.title}\n"
            f"Tags: {', '.join(sorted(parsed.tags))}\n"
            f"Aliases: {', '.join(sorted(parsed.aliases))}\n\n"
        )
        batch_ids, batch_docs, batch_meta = [], [], []
        for i, chunk in enumerate(self._split_chunks(parsed.body)):
            doc = header + chunk
            meta = {
                "vault_root": vault_root,
                "rel_path": rel_path,
                "chunk_id": i,
                "tags": ",".join(sorted(parsed.tags))[:500],
                "mtime": int(full.stat().st_mtime),
            }
            if owner:
                meta["owner"] = owner
            batch_ids.append(self._chunk_id(vault_root, rel_path, i))
            batch_docs.append(doc)
            batch_meta.append(meta)
        if not batch_ids:
            return True
        return self._flush(batch_ids, batch_docs, batch_meta)

    def _purge_vault(self, vault_root: str, owner: str = "") -> None:
        try:
            where: Dict[str, Any] = {"vault_root": vault_root}
            if owner:
                where = {"$and": [{"vault_root": vault_root}, {"owner": owner}]}
            existing = self._collection.get(where=where, include=[])
            if existing.get("ids"):
                self._collection.delete(ids=existing["ids"])
        except Exception as e:
            logger.warning(f"Vault vector purge failed: {e}")

    def search(
        self,
        query: str,
        config: VaultConfig,
        *,
        k: int = 10,
        owner: str = "",
        folder: str = "",
    ) -> List[Tuple[str, float, str]]:
        """Return [(rel_path, score 0-1, snippet), ...]."""
        if not self.healthy or not query.strip():
            return []
        if self._collection.count() == 0:
            return []

        vault_root = str(config.root)
        try:
            where: Dict[str, Any] = {"vault_root": vault_root}
            if owner:
                where = {"$and": [{"vault_root": vault_root}, {"owner": owner}]}

            q_emb = self._embed([query])
            fetch_k = min(max(k * 4, 12), self._collection.count())
            results = self._collection.query(
                query_embeddings=q_emb,
                n_results=fetch_k,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.debug(f"Vault vector search failed: {e}")
            return []

        if not results["ids"] or not results["ids"][0]:
            return []

        folder_prefix = folder.strip("/").lower() + "/" if folder else ""
        query_words = set(query.lower().split())
        by_path: Dict[str, Tuple[float, str]] = {}

        for idx in range(len(results["ids"][0])):
            meta = results["metadatas"][0][idx]
            rel = meta.get("rel_path") or ""
            if folder_prefix and not rel.lower().startswith(folder_prefix):
                continue
            doc = results["documents"][0][idx] or ""
            vector_sim = max(0.0, 1.0 - float(results["distances"][0][idx]))
            doc_words = set(doc.lower().split())
            overlap = len(query_words & doc_words)
            kw = overlap / len(query_words) if query_words else 0.0
            score = VECTOR_WEIGHT * vector_sim + KEYWORD_WEIGHT * kw
            prev = by_path.get(rel)
            if prev is None or score > prev[0]:
                snippet = doc[:200].replace("\n", " ").strip()
                by_path[rel] = (score, snippet)

        ranked = sorted(by_path.items(), key=lambda x: (-x[1][0], x[0].lower()))
        return [(rel, sc, snip) for rel, (sc, snip) in ranked[:k]]

    def stats(self, config: VaultConfig, owner: str = "") -> Dict[str, Any]:
        if not self.healthy:
            return {"healthy": False, "chunk_count": 0}
        try:
            vault_root = str(config.root)
            where: Dict[str, Any] = {"vault_root": vault_root}
            if owner:
                where = {"$and": [{"vault_root": vault_root}, {"owner": owner}]}
            got = self._collection.get(where=where, include=[])
            return {
                "healthy": True,
                "chunk_count": len(got.get("ids") or []),
                "embedding_model": getattr(self._model, "model", "unknown"),
            }
        except Exception as e:
            return {"healthy": False, "error": str(e)}


def reindex_vault_note(config: VaultConfig, rel_path: str, owner: str = "") -> bool:
    idx = get_vault_vector_index()
    if not idx.healthy:
        return False
    return idx.index_note(config, rel_path, owner=owner)


def get_vault_vector_index() -> VaultVectorIndex:
    return VaultVectorIndex()


def ensure_vault_index(config: VaultConfig, owner: str = "", *, max_age_hours: float = 24.0) -> bool:
    """Re-index if missing or vault mtime newer than last index metadata."""
    idx = get_vault_vector_index()
    if not idx.healthy:
        return False
    stats = idx.stats(config, owner=owner)
    if stats.get("chunk_count", 0) == 0:
        idx.index_vault(config, owner=owner)
        return True
    try:
        latest_mtime = 0.0
        for _rel, full in _iter_notes(config):
            try:
                latest_mtime = max(latest_mtime, full.stat().st_mtime)
            except OSError:
                pass
        vault_root = str(config.root)
        where: Dict[str, Any] = {"vault_root": vault_root}
        if owner:
            where = {"$and": [{"vault_root": vault_root}, {"owner": owner}]}
        got = idx._collection.get(where=where, include=["metadatas"])
        metas = got.get("metadatas") or []
        indexed_mtime = max((m.get("mtime") or 0 for m in metas), default=0)
        if latest_mtime > indexed_mtime + 60:
            logger.info("Vault changed since last index — re-indexing")
            idx.index_vault(config, owner=owner)
    except Exception as e:
        logger.debug(f"ensure_vault_index check failed: {e}")
    return True
