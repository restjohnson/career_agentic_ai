"""
Few-shot example retrieval from Supabase vector DB for role intake LLM calibration.

The job_examples table stores job descriptions extracted from Kaggle datasets,
embedded by (job_title + responsibilities + keywords). This module retrieves
semantically similar examples to inject into the LLM prompt as calibration.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_openai import OpenAIEmbeddings

from app.tools.supabase_repo import SupabaseRepo


def retrieve_few_shot_examples(desired_role: str, k: int = 2) -> List[Dict[str, Any]]:
    """
    Retrieve k job examples most similar to desired_role from the Supabase vector DB.

    Returns a list of formatted examples ready for LLM injection. Each example has:
    - role: job title
    - requirements: list of requirement dicts with category, required_level, importance

    Returns an empty list if the table is empty, retrieval fails, or any error occurs.
    """
    try:
        embedder = OpenAIEmbeddings(model="text-embedding-3-small")
        query_vec = embedder.embed_query(desired_role)

        repo = SupabaseRepo()
        results = repo.sb.rpc(
            "match_job_examples",
            {"query_embedding": query_vec, "match_count": k},
        ).execute()

        examples = []
        for row in results.data or []:
            # Format skills as requirement dicts
            requirements = []

            # Add skills
            for skill in (row.get("key_skills") or []):
                requirements.append(
                    {
                        "req_summary": skill,
                        "category": "skill",
                        "required_level": 3,
                        "importance": 4,
                        "optional": False,
                    }
                )

            # Add keywords as knowledge items
            for kw in (row.get("key_knowledge") or []):
                requirements.append(
                    {
                        "req_summary": kw,
                        "category": "knowledge",
                        "required_level": 2,
                        "importance": 3,
                        "optional": True,
                    }
                )

            examples.append(
                {
                    "role": row.get("job_title", ""),
                    "requirements": requirements,
                }
            )

        return examples

    except Exception as e:
        print(f"⚠ Few-shot retrieval failed: {type(e).__name__}: {e}")
        return []
