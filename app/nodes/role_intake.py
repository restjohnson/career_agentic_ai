from __future__ import annotations
from typing import Any, Dict

from app.state import AgentState, ProvenanceRef, RoleSpecModel, RoleSpecRequirement
from app.tools.onet_client import OnetClient
from app.tools.role_spec_llm import build_role_spec_from_onet_raw, llm_refactor_role_spec_from_onet_raw
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

    client = OnetClient()
    repo = SupabaseRepo()
    candidates = client.search_occupations(s.desired_role, limit=5)
    if not candidates:
        s.errors.append("No O*NET occupation candidates found for your keywords.")
        return s.model_dump(exclude_none=True)

    top = candidates[0]
    onet_code = top.get("code") or top.get("onet_code") or top.get("id")
    role_title = top.get("title") or top.get("name") or s.desired_role
    if not onet_code:
        s.errors.append(f"Could not extract onet code from the candidate: {top}")
        return s.model_dump(exclude_none=True)

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
