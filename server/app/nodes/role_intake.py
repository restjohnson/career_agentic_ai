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


def _summary_from_onet_item(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for key in ["title", "name", "description", "label", "example", "commodity_title"]:
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def _ablation1_role_spec_from_onet(
    *,
    role_title: str,
    onet_code: str,
    tech_payload: Dict[str, Any],
    hot_tech_payload: Dict[str, Any],
) -> RoleSpecModel:
    reqs: List[RoleSpecRequirement] = []

    seen: set[str] = set()
    if isinstance(tech_payload, dict):
        for _, examples in tech_payload.items():
            if not isinstance(examples, list):
                continue
            for item in examples:
                summary = _summary_from_onet_item(item)
                if not summary:
                    continue
                key = summary.lower()
                if key in seen:
                    continue
                seen.add(key)
                reqs.append(
                    RoleSpecRequirement(
                        req_summary=summary,
                        category="tech",
                        provenance=[],
                        optional=False,
                    )
                )

    hot_items: List[Any] = []
    if isinstance(hot_tech_payload, dict):
        for k in ["hot_technology", "hotTechnology", "technology", "tool", "tools"]:
            if isinstance(hot_tech_payload.get(k), list):
                hot_items = hot_tech_payload[k]
                break

    for item in hot_items:
        summary = _summary_from_onet_item(item)
        if not summary:
            continue
        key = summary.lower()
        if key in seen:
            continue
        seen.add(key)
        reqs.append(
            RoleSpecRequirement(
                req_summary=summary,
                category="hot_technology",
                provenance=[],
                optional=False,
            )
        )

    return RoleSpecModel(
        canonical_role_title=role_title,
        matched_onet_code=onet_code,
        confidence_role_match=0.7,
        requirements=reqs,
        assumptions=[],
    )


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

    client = OnetClient()
    repo = SupabaseRepo()

    # Ablation 1 baseline: direct O*NET keyword search (top result),
    # raw structural mapping, and no provenance attribution.
    if s.ablation_mode == "ablation1_no_role_grounding":
        try:
            hits = client.search_occupations(s.desired_role, limit=5)
        except Exception as e:
            s.errors.append(f"Ablation1 O*NET search failed: {type(e).__name__}: {e}")
            return s.model_dump(exclude_none=True)

        if not hits:
            s.errors.append("Ablation1: no O*NET keyword matches found.")
            return s.model_dump(exclude_none=True)

        top = hits[0]
        onet_code = top.get("code") or top.get("onet_code") or top.get("id")
        role_title = top.get("title") or top.get("name") or s.desired_role

        if not onet_code:
            s.errors.append("Ablation1: top O*NET keyword result missing occupation code.")
            return s.model_dump(exclude_none=True)

        try:
            tech = client.get_occupation_technology(onet_code)
            hot_tech = client.get_hot_technology_skills(onet_code)
            s.role_spec = _ablation1_role_spec_from_onet(
                role_title=role_title,
                onet_code=onet_code,
                tech_payload=tech if isinstance(tech, dict) else {},
                hot_tech_payload=hot_tech if isinstance(hot_tech, dict) else {},
            )
        except Exception as e:
            s.errors.append(f"Ablation1 role spec build failed: {type(e).__name__}: {e}")

        return s.model_dump(exclude_none=True)

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
