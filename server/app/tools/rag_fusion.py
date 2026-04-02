"""
rag_fusion.py — Pure RRF and semantic deduplication utilities.
No dependency on Supabase, ONET, or any other project I/O module.
"""
from __future__ import annotations

from typing import Any, Dict, List

from langchain_openai import OpenAIEmbeddings


def reciprocal_rank_fusion(
    ranked_lists: List[List[Dict[str, Any]]],
    k: int = 60,
) -> List[Dict[str, Any]]:
    """
    Merge multiple ranked result lists using Reciprocal Rank Fusion.

    Identity key: (source, title.lower().strip()) — collapses same-source duplicates
    that surface across different sub-queries, but keeps Kaggle vs ONET as separate
    evidence (a Kaggle "Data Scientist" and an ONET "Data Scientist" are genuinely
    different evidence sources).

    Attaches _rrf_score to each returned doc. Result is sorted descending by score.
    k=60 is the standard RRF parameter from Cormack et al. (2009).
    """
    from collections import defaultdict

    scores: Dict[tuple, float] = defaultdict(float)
    doc_store: Dict[tuple, Dict[str, Any]] = {}

    for ranked_list in ranked_lists:
        for rank_idx, doc in enumerate(ranked_list, start=1):
            key = (doc.get("source", ""), doc.get("title", "").lower().strip())
            scores[key] += 1.0 / (k + rank_idx)
            if key not in doc_store:
                doc_store[key] = doc

    sorted_keys = sorted(scores.keys(), key=lambda kk: scores[kk], reverse=True)
    result = []
    for key in sorted_keys:
        doc = dict(doc_store[key])
        doc["_rrf_score"] = scores[key]
        result.append(doc)
    return result


def semantic_deduplicate(
    docs: List[Dict[str, Any]],
    threshold: float = 0.82,
) -> List[Dict[str, Any]]:
    """
    Greedily deduplicate docs by semantic similarity of their title fields.

    Embeds all titles in a single batch call, then iterates in RRF score order
    (highest first). Drops any doc whose title cosine-similarity to an already-kept
    doc exceeds threshold. Order of kept docs is preserved.

    Falls back to returning docs unchanged if embedding fails — downstream LLM
    gets slightly redundant examples but the pipeline does not crash.
    """
    if not docs:
        return []

    embedder = OpenAIEmbeddings(model="text-embedding-3-small")
    titles = [doc.get("title", "") for doc in docs]

    try:
        vecs = embedder.embed_documents(titles)
    except Exception:
        return docs

    import numpy as np

    vecs_np = np.array(vecs, dtype="float32")
    norms = np.linalg.norm(vecs_np, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-9, norms)
    vecs_norm = vecs_np / norms

    kept: List[int] = []
    for i in range(len(docs)):
        is_dup = any(
            float(np.dot(vecs_norm[i], vecs_norm[j])) > threshold
            for j in kept
        )
        if not is_dup:
            kept.append(i)

    return [docs[i] for i in kept]