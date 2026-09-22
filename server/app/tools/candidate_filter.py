"""
candidate_filter.py — Gap Analysis Step 1: embedding-based candidate prefilter.

Rating every (item, requirement) pair for relevance is quadratic and mostly wasteful.
This drops a pair before relevance rating if its embedding similarity is
below CANDIDATE_PREFILTER_SIMILARITY — deliberately biased toward recall

The similarity math is separated from the embedding call itself so it can
be unit-tested without hitting the OpenAI API 
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np
from langchain_openai import OpenAIEmbeddings

from app.compass_config import CANDIDATE_PREFILTER_SIMILARITY
from app.state import EvidenceItem, Requirement


def _normalize(vecs: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-9, norms)
    return vecs / norms


def filter_pairs_by_similarity(
    item_vecs: Sequence[Sequence[float]],
    requirement_vecs: Sequence[Sequence[float]],
    threshold: float = CANDIDATE_PREFILTER_SIMILARITY,
) -> List[Tuple[int, int]]:
    """
    Pure cosine-similarity threshold over precomputed embeddings.
    Returns (item_index, requirement_index) pairs whose similarity >= threshold.
    """
    if not item_vecs or not requirement_vecs:
        return []

    items_np = _normalize(np.array(item_vecs, dtype="float32"))
    reqs_np = _normalize(np.array(requirement_vecs, dtype="float32"))
    sims = items_np @ reqs_np.T  # (n_items, n_requirements)

    pairs: List[Tuple[int, int]] = []
    for i in range(sims.shape[0]):
        for r in range(sims.shape[1]):
            if sims[i, r] >= threshold:
                pairs.append((i, r))
    return pairs


def candidate_pairs(
    evidence_items: Sequence[EvidenceItem],
    requirements: Sequence[Requirement],
    threshold: float = CANDIDATE_PREFILTER_SIMILARITY,
) -> List[Tuple[str, str]]:
    """
    Embeds item text (snippet, falling back to summary) and requirement
    descriptions, then returns surviving (item_id, requirement_id) pairs.

    On embedding failure, falls back to the full cross-product — the safe
    direction given the deliberate recall bias (an unfiltered pair only
    costs an extra relevance-rating call; a wrongly dropped one silently
    starves a posterior).
    """
    if not evidence_items or not requirements:
        return []

    all_pairs = [(item.id, req.id) for item in evidence_items for req in requirements]

    try:
        embedder = OpenAIEmbeddings(model="text-embedding-3-small")
        item_texts = [item.snippet or item.summary for item in evidence_items]
        req_texts = [req.description for req in requirements]
        item_vecs = embedder.embed_documents(item_texts)
        req_vecs = embedder.embed_documents(req_texts)
    except Exception:
        return all_pairs

    index_pairs = filter_pairs_by_similarity(item_vecs, req_vecs, threshold)
    return [(evidence_items[i].id, requirements[r].id) for i, r in index_pairs]
