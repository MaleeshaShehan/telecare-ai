"""Dense, BM25 and hybrid (RRF) retrieval + the sufficiency judgement.   Owner: M2

Contract used by main.py and eval/run_ir_eval.py:
    dense_search(query, k=10, category=None) -> list[Chunk]
    bm25_search(query, k=10, category=None)  -> list[Chunk]
    hybrid_search(query, k=4, category=None) -> list[Chunk]   # RRF, score = sum 1/(60+rank)
    is_sufficient(chunks) -> bool   # best cosine >= settings.retrieval_min_similarity

Chunk = dict with: chunk_id, ref_id, doc_id, title, category, url, text, score
"""
from __future__ import annotations

import pickle
from typing import Any, Optional

import numpy as np

from agents.knowledge_agent.ingest import (
    BM25_PATH,
    CHROMA_DIR,
    COLLECTION_NAME,
    EMBEDDING_MODEL_NAME,
    tokenize_bm25,
)
from shared.config import settings

# Lazy singletons
_model: Any = None
_chroma_coll: Any = None
_bm25_data: Optional[dict[str, Any]] = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _model


def _get_chroma_collection():
    global _chroma_coll
    if _chroma_coll is None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        client = chromadb.PersistentClient(
            path=str(CHROMA_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        _chroma_coll = client.get_collection(COLLECTION_NAME)
    return _chroma_coll


def _get_bm25_data() -> dict[str, Any]:
    global _bm25_data
    if _bm25_data is None:
        with open(BM25_PATH, "rb") as f:
            _bm25_data = pickle.load(f)
    return _bm25_data


# ------------------------------------------------------------------ Dense Search
def dense_search(query: str, k: int = 10, category: Optional[str] = None) -> list[dict[str, Any]]:
    """Retrieve top-k chunks using dense embedding similarity (all-MiniLM-L6-v2)."""
    model = _get_model()
    coll = _get_chroma_collection()

    q_emb = model.encode([query], normalize_embeddings=True).tolist()
    where = {"category": category} if category else None

    count = coll.count()
    if count == 0:
        return []

    n_results = min(k, count)
    results = coll.query(
        query_embeddings=q_emb,
        n_results=n_results,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    chunks: list[dict[str, Any]] = []
    if not results or not results["ids"] or not results["ids"][0]:
        return chunks

    ids = results["ids"][0]
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    dists = results["distances"][0]

    for i in range(len(ids)):
        dist = dists[i]
        sim = float(1.0 - dist)
        meta = metas[i]
        chunks.append({
            "chunk_id": meta.get("chunk_id", ids[i]),
            "ref_id": meta.get("ref_id", ids[i]),
            "doc_id": meta.get("doc_id", ""),
            "title": meta.get("title", ""),
            "category": meta.get("category", ""),
            "url": meta.get("url") or None,
            "text": docs[i],
            "score": sim,
            "dense_similarity": sim,
        })

    return chunks


# ------------------------------------------------------------------ BM25 Search
def bm25_search(query: str, k: int = 10, category: Optional[str] = None) -> list[dict[str, Any]]:
    """Retrieve top-k chunks using BM25 with telco tokenization."""
    bm25_pkg = _get_bm25_data()
    bm25 = bm25_pkg["bm25"]
    corpus = bm25_pkg["chunks"]

    q_tokens = tokenize_bm25(query)
    if not q_tokens:
        return []

    scores = bm25.get_scores(q_tokens)

    # Filter by category if requested
    candidates: list[tuple[int, float]] = []
    for idx, score in enumerate(scores):
        if category and corpus[idx].get("category") != category:
            continue
        candidates.append((idx, float(score)))

    candidates.sort(key=lambda x: x[1], reverse=True)
    top_candidates = candidates[:k]

    results: list[dict[str, Any]] = []
    for idx, score in top_candidates:
        c = corpus[idx]
        results.append({
            "chunk_id": c["chunk_id"],
            "ref_id": c["ref_id"],
            "doc_id": c["doc_id"],
            "title": c["title"],
            "category": c["category"],
            "url": c.get("url"),
            "text": c["text"],
            "score": score,
        })

    return results


# ------------------------------------------------------------------ Hybrid Search (RRF)
def _hybrid_search_impl(query: str, k: int = 4, category: Optional[str] = None) -> list[dict[str, Any]]:
    """Internal hybrid search using Reciprocal Rank Fusion over Dense top-10 and BM25 top-10."""
    dense_hits = dense_search(query, k=10, category=category)
    bm25_hits = bm25_search(query, k=10, category=category)

    if not dense_hits and not bm25_hits:
        return []

    k_rrf = 60.0
    rrf_scores: dict[str, float] = {}
    chunk_map: dict[str, dict[str, Any]] = {}
    dense_sim_map: dict[str, float] = {}

    for rank, item in enumerate(dense_hits, start=1):
        cid = item["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (k_rrf + rank))
        chunk_map[cid] = item
        dense_sim_map[cid] = item["score"]

    for rank, item in enumerate(bm25_hits, start=1):
        cid = item["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + (1.0 / (k_rrf + rank))
        if cid not in chunk_map:
            chunk_map[cid] = item

    # Encode query once to compute dense similarity for BM25-only hits
    model = _get_model()
    q_vec: Optional[np.ndarray] = None

    for cid in rrf_scores:
        if cid not in dense_sim_map:
            if q_vec is None:
                q_vec = model.encode(query, normalize_embeddings=True)
            doc_vec = model.encode(chunk_map[cid]["text"], normalize_embeddings=True)
            sim = float(np.dot(q_vec, doc_vec))
            dense_sim_map[cid] = sim

    sorted_cids = sorted(rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True)[:k]

    results: list[dict[str, Any]] = []
    for cid in sorted_cids:
        chunk = dict(chunk_map[cid])
        chunk["score"] = rrf_scores[cid]
        chunk["dense_similarity"] = dense_sim_map[cid]
        results.append(chunk)

    return results


def hybrid_search(query: str, k: int = 4, category: Optional[str] = None) -> list[dict[str, Any]]:
    """Hybrid search with automatic category-filter relaxation if evidence is insufficient."""
    chunks = _hybrid_search_impl(query, k=k, category=category)

    # If category filter yielded insufficient results, retry once without category filter
    if category is not None and not is_sufficient(chunks):
        relaxed = _hybrid_search_impl(query, k=k, category=None)
        for c in relaxed:
            c["filter_relaxed"] = True
        return relaxed

    return chunks


# ------------------------------------------------------------------ Sufficiency
def is_sufficient(chunks: list[dict[str, Any]]) -> bool:
    """Best dense cosine similarity must meet settings.retrieval_min_similarity."""
    if not chunks:
        return False
    best_sim = max((c.get("dense_similarity", c.get("score", 0.0)) for c in chunks), default=0.0)
    return best_sim >= settings.retrieval_min_similarity
