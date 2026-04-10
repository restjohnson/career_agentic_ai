"""
role_few_shot_examples.py — Hybrid RAG-Fusion retrieval for role intake calibration.

Per sub-query: search Kaggle vector DB + ONET. Fuse with RRF. Semantically deduplicate.
Returns both calibration examples for the LLM and the best canonical ONET code.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TypedDict

from langchain_openai import OpenAIEmbeddings

from app.tools.onet_client import OnetClient
from app.tools.rag_fusion import reciprocal_rank_fusion, semantic_deduplicate
from app.tools.role_spec_llm import decompose_role_into_dimensions
from app.tools.supabase_repo import SupabaseRepo


class RetrievedDoc(TypedDict):
    """Common schema for both Kaggle and ONET retrieved documents."""

    source: str  # "kaggle" | "onet"
    title: str
    skills: List[str]  # key_skills (kaggle) — empty for onet (no extra API calls)
    knowledge: List[str]  # key_knowledge (kaggle) — empty for onet
    onet_code: Optional[str]
    sub_query: str


def search_kaggle_for_subquery(
    query: str, repo: SupabaseRepo, k: int = 5
) -> List[RetrievedDoc]:
    """Search Kaggle job examples table by embedding the sub-query."""
    try:
        embedder = OpenAIEmbeddings(model="text-embedding-3-small")
        query_vec = embedder.embed_query(query)

        results = repo.sb.rpc(
            "match_job_examples",
            {"query_embedding": query_vec, "match_count": k},
        ).execute()

        return [
            RetrievedDoc(
                source="kaggle",
                title=row.get("job_title", ""),
                skills=row.get("key_skills") or [],
                knowledge=row.get("key_knowledge") or [],
                onet_code=None,
                sub_query=query,
            )
            for row in (results.data or [])
            if row.get("job_title")
        ]
    except Exception as e:
        print(f"⚠ Kaggle retrieval failed for '{query}': {type(e).__name__}: {e}")
        return []


def search_onet_for_subquery(
    client: OnetClient, query: str, limit: int = 3
) -> List[RetrievedDoc]:
    """Search ONET by keyword. Only uses occupations endpoint (no extra detail fetches)."""
    try:
        occupations = client.search_occupations(query, limit=limit)

        return [
            RetrievedDoc(
                source="onet",
                title=occ.get("title") or occ.get("name") or "",
                skills=[],  # No extra API calls — only use what search_occupations returns
                knowledge=[],
                onet_code=occ.get("code") or occ.get("onet_code") or occ.get("id"),
                sub_query=query,
            )
            for occ in occupations
            if occ.get("title") or occ.get("name")
        ]
    except Exception as e:
        print(f"⚠ ONET retrieval failed for '{query}': {type(e).__name__}: {e}")
        return []


def _format_as_few_shot(doc: RetrievedDoc) -> Dict[str, Any]:
    """Convert RetrievedDoc to {role, requirements} shape for LLM injection."""
    requirements = [
        {
            "req_summary": s,
            "category": "skill",
            "required_level": 3,
            "importance": 4,
            "optional": False,
        }
        for s in doc["skills"]
    ] + [
        {
            "req_summary": k,
            "category": "knowledge",
            "required_level": 2,
            "importance": 3,
            "optional": True,
        }
        for k in doc["knowledge"]
    ]

    return {
        "role": doc["title"],
        "requirements": requirements,
        "source": doc["source"],  # extra metadata
        "sub_query": doc["sub_query"],  # extra metadata
    }


def hybrid_retrieve_fused(
    desired_role: str,
    client: OnetClient,
    k_examples: int = 3,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str]]:
    """
    Full RAG-Fusion pipeline for role intake.

    1. Decompose desired_role into 3-5 dimensional sub-queries
    2. Per sub-query: search Kaggle + ONET independently
    3. RRF fusion across all results
    4. Semantic deduplication
    5. Extract top-k for few-shot + best ONET code for anchoring

    Returns:
        fused_examples:  List[Dict] formatted for LLM few_shot injection (top-k after RRF + dedup)
        best_onet_code:  Canonical ONET code (highest-RRF-scored ONET result), or None
        best_onet_title: Canonical ONET title for the best match, or None
    """
    repo = SupabaseRepo()

    # 1. Dimensional decomposition
    sub_queries = decompose_role_into_dimensions(desired_role)

    # 2. Per-subquery retrieval from both sources
    all_ranked_lists: List[List[Dict[str, Any]]] = []

    for query in sub_queries:
        kaggle_results = search_kaggle_for_subquery(query, repo, k=5)
        onet_results = search_onet_for_subquery(client, query, limit=3)

        # Each sub-query contributes ranked lists (one per source if results exist)
        if kaggle_results:
            all_ranked_lists.append(kaggle_results)
        if onet_results:
            all_ranked_lists.append(onet_results)

    # Graceful degradation: if all retrievals failed, return empty
    if not all_ranked_lists:
        return [], None, None

    # 3. RRF across all sub-query result lists
    fused: List[Dict[str, Any]] = reciprocal_rank_fusion(all_ranked_lists)

    # 4. Semantic deduplication
    deduped = semantic_deduplicate(fused, threshold=0.82)

    # 5. Extract best ONET code: highest-RRF-scored doc with source=="onet"
    best_onet_code: Optional[str] = None
    best_onet_title: Optional[str] = None
    for doc in deduped:  # already sorted by RRF score descending
        if doc.get("source") == "onet" and doc.get("onet_code"):
            best_onet_code = doc["onet_code"]
            best_onet_title = doc.get("title")
            break

    # 6. Format top-k for LLM injection
    fused_examples = [_format_as_few_shot(doc) for doc in deduped[:k_examples]]

    return fused_examples, best_onet_code, best_onet_title
