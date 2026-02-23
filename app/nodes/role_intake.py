from __future__ import annotations
from typing import Any, Dict
from app.state import AgentState
from app.tools.onet_client import OnetClient
from app.tools.onet_normalize import normalize_onet_to_role_model
from app.tools.role_spec_llm import llm_refactor_role_spec, build_role_spec_from_onet
from app.tools.supabase_repo import SupabaseRepo


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

    #onet details
    summary = client.get_occupation_summary(onet_code)
    skills = client.get_occupation_skills(onet_code)
    tasks = client.get_occupation_tasks(onet_code)
    tech = client.get_occupation_technology(onet_code)
    hot_tech = client.get_hot_technology_skills(onet_code)
    version = client.get_onet_version()

    #normalize the above information to RoleModel
    s.role_model = normalize_onet_to_role_model(
        role_title=role_title,
        onet_code=onet_code,
        version=version,
        summary=summary if isinstance(summary, dict) else {"raw": summary},
        skills_payload=skills,
        tasks_payload=tasks,
        tech_payload=tech,
        hot_tech_payload=hot_tech,
    )

    #save the information in database
    try:
        role_id = repo.upsert_role(
            role_title=s.role_model.role_title,
            onet_code=s.role_model.onet_code,
            version=s.role_model.version,
            summary=s.role_model.summary,
        )
        repo.replace_role_requirement(
            role_id=role_id,
            requirements=[
                {
                    "req_type": r.req_type,
                    "label": r.label,
                    "importance": r.importance,
                    "metadata": {**(r.metadata or {}), "source_id": r.source_id},
                }
                for r in s.role_model.requirements
            ],
        )
    except Exception as e:
        s.errors.append(f"Baseline role cache write failed: {type(e).__name__}: {e}")

    #LLM mapping
    try:
        s.role_spec = llm_refactor_role_spec(s.role_model)
    except Exception as e:
        s.errors.append(f"LLM role spec failed; using baseline mapping: Error: {type(e).__name__}: {e}")
        s.role_spec = build_role_spec_from_onet(s.role_model)

    #Keep ONET-backed categories aligned with baseline req_type.
    baseline_type_by_source_id = {
        r.source_id: r.req_type for r in s.role_model.requirements if r.source_id
    }
    for req in s.role_spec.requirements:
        onet_types = set()
        for prov in req.provenance:
            if prov.source_type != "ONET":
                continue
            for sid in prov.source_ids:
                t = baseline_type_by_source_id.get(sid)
                if t:
                    onet_types.add(t)
        if len(onet_types) == 1:
            req.category = next(iter(onet_types))

    #to validate that the ONET source ids given by the LLM actually exist
    baseline_ids = {r.source_id for r in s.role_model.requirements if r.source_id}
    for req in s.role_spec.requirements:
        for prov in req.provenance:
            if prov.source_type == "ONET":
                for sid in prov.source_ids:
                    if sid and sid not in baseline_ids:
                        s.errors.append(f"RoleSpec references unknown ONET source_id: {sid}")

    return s.model_dump(exclude_none=True)
