from __future__ import annotations
from typing import Any, Dict, List

from app.state import AgentState, ProvenanceRef, RoleSpecModel, RoleSpecRequirement
from app.tools.onet_client import OnetClient
from app.tools.role_spec_llm import (
    build_role_spec_from_onet_raw,
    llm_refactor_role_spec_from_onet_raw,
)
from app.tools.role_few_shot_examples import hybrid_retrieve_fused
from app.tools.supabase_repo import SupabaseRepo


def _role_spec_from_cache(role_title: str, onet_code: str, rows: list) -> RoleSpecModel:
    """Reconstruct a RoleSpecModel from cached role_requirements DB rows."""
    requirements = []
    for row in rows:
        meta = row.get("metadata") or {}
        provenance = [
            ProvenanceRef(**p) for p in meta.get("provenance", [])
        ]
        requirements.append(RoleSpecRequirement(
            req_summary=row["req_summary"],
            category=row["req_type"],
            provenance=provenance,
            optional=meta.get("optional", False),
            required_level=float(meta.get("required_level", 3.0)),
            importance=float(row.get("importance") or 3.0),
        ))
    return RoleSpecModel(
        canonical_role_title=role_title,
        matched_onet_code=onet_code,
        confidence_role_match=0.9,
        requirements=requirements,
    )


def role_intake_node(state: Dict[str, Any]) -> Dict[str, Any]:
    s = AgentState.model_validate(state)
    s.step = "role_intake"

    # Allow callers (e.g. ablation paired runs) to pre-inject a role_spec so
    # both conditions share identical requirements — required for valid divergence metrics.
    if s.role_spec:
        print(f"[ROLE_INTAKE] role_spec pre-injected ({len(s.role_spec.requirements)} reqs) — skipping intake.", flush=True)
        return s.model_dump(exclude_none=True)

    client = OnetClient()
    repo = SupabaseRepo()

    # --- Hybrid RAG-Fusion: dimensional retrieval + RRF + deduplication ---
    # Returns calibration examples for the LLM AND the best ONET code to anchor the spec.
    try:
        fused_examples, best_onet_code, best_onet_title = hybrid_retrieve_fused(
            s.desired_role, client, k_examples=3
        )
    except Exception as e:
        s.errors.append(f"RAG-Fusion pipeline failed: {type(e).__name__}: {e}")
        fused_examples, best_onet_code, best_onet_title = [], None, None

    if not best_onet_code:
        s.errors.append("No O*NET match found via RAG-Fusion.")
        return s.model_dump(exclude_none=True)

    onet_code = best_onet_code
    role_title = best_onet_title or s.desired_role

    # Check cache first — reuse existing role_spec to keep required_level and
    # importance stable across runs for the same ONET code.
    try:
        cached = repo.get_cached_role_spec(onet_code)
        if cached:
            role_id, req_rows = cached
            s.role_spec = _role_spec_from_cache(role_title, onet_code, req_rows)
            return s.model_dump(exclude_none=True)
    except Exception as e:
        s.errors.append(f"Cache lookup failed, regenerating: {type(e).__name__}: {e}")

    # Cache miss — fetch O*NET details and call the LLM.
    summary = client.get_occupation_summary(onet_code)
    tech = client.get_occupation_technology(onet_code)
    hot_tech = client.get_hot_technology_skills(onet_code)
    skills = client.get_occupation_skills(onet_code)
    tasks = client.get_occupation_tasks(onet_code)
    knowledge = client.get_occupation_knowledge(onet_code)
    version = client.get_onet_version()
    summary_dict = summary if isinstance(summary, dict) else {"raw": summary}

    try:
        role_id = repo.upsert_role(
            role_title=role_title,
            onet_code=onet_code,
            version=version,
            summary=summary_dict,
        )
    except Exception as e:
        role_id = None
        s.errors.append(f"Baseline role cache write failed: {type(e).__name__}: {e}")

    # --- Fused examples already computed above via RAG-Fusion ---
    try:
        s.role_spec = llm_refactor_role_spec_from_onet_raw(
            desired_role=s.desired_role,
            role_title=role_title,
            onet_code=onet_code,
            version=version,
            summary=summary_dict,
            tech_payload=tech,
            hot_tech_payload=hot_tech,
            skills_payload=skills,
            tasks_payload=tasks,
            knowledge_payload=knowledge,
            raw_user_text=s.raw_user_text,
            few_shot_examples=fused_examples,
        )
    except Exception as e:
        s.errors.append(
            f"LLM role spec failed; using raw O*NET fallback mapping: Error: {type(e).__name__}: {e}"
        )
        s.role_spec = build_role_spec_from_onet_raw(
            role_title=role_title,
            onet_code=onet_code,
            tech_payload=tech,
            hot_tech_payload=hot_tech,
        )

    if role_id:
        try:
            repo.replace_role_requirement(
                role_id=role_id,
                requirements=[
                    {
                        "req_type": r.category,
                        "req_summary": r.req_summary,
                        "importance": r.importance,
                        "metadata": {
                            "source": "role_spec_llm",
                            "required_level": r.required_level,
                            "provenance": [p.model_dump(exclude_none=True) for p in r.provenance],
                            "optional": r.optional,
                        },
                    }
                    for r in s.role_spec.requirements
                ],
            )
        except Exception as e:
            s.errors.append(f"RoleSpec requirement cache write failed: {type(e).__name__}: {e}")

    return s.model_dump(exclude_none=True)
