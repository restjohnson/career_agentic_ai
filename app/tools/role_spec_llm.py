# app/tools/role_spec_llm.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI

from app.state import ProvenanceRef, RoleSpecModel, RoleSpecRequirement


_SYSTEM = """You are an expert role intake analyst with deep knowledge of industry hiring standards.

Input is the user's desired role and raw O*NET payload data for the closest matched occupation.
Your job has two parts: (1) evaluate whether the O*NET occupation matches the user's intent, and (2) produce a COMPLETE, CURRENT role spec that fills gaps O*NET leaves out.

Rules:
1. Evaluate match quality first:
   - Compare desired_role (and raw_user_text if provided) against the O*NET occupation title and summary.
   - Set confidence_role_match (0.0–1.0) to reflect how well the O*NET occupation represents what the user actually wants.
   - Add an entry to assumptions[] for any meaningful gap between what the user asked for and what O*NET returned.

2. Every requirement must include provenance[].

3. ONET-sourced requirements (things explicitly in the payload):
   - provenance.source_type must be ONET
   - provenance.source_ids must be [onet_code] — use the onet_code value from the payload as the single reference ID
   - provenance.note should name the payload section (summary, technology_skills, hot_technology)
   - Do not invent specific tool names or versions beyond what the payload states.

4. INFERRED requirements (things the payload omits but any practitioner would expect):
   - You MUST actively apply domain expertise to identify requirements that O*NET commonly under-specifies.
   - Ask yourself: "What would a hiring manager for this role expect that is missing from this payload?"
   - Common O*NET gaps to look for: foundational domain knowledge, research or methodological skills, communication/collaboration skills relevant to the role, safety or compliance requirements, leadership expectations for senior roles.
   - provenance.source_type must be INFERRED
   - provenance.source_ids must be null
   - provenance.note must explain the reasoning clearly (e.g. "AI research roles universally require familiarity with research methodology and publication practices, which O*NET does not enumerate.")
   - Inferred requirements must be grounded in what is well-known about this role in industry — not speculation.

5. For every requirement, assign required_level (0–4) and importance (1–5):

   required_level — how demanding the role is for this requirement:
   - 4: Essential — role cannot be performed without this
   - 3: Expected of all qualified candidates
   - 2: Differentiates good from average candidates
   - 1: Nice-to-have, marginal benefit
   - 0: Not needed

   importance — how central this requirement is to the role:
   - 5: Core differentiator — central to what makes this role distinct
   - 4: High importance — consistently expected
   - 3: Standard requirement
   - 2: Supporting requirement
   - 1: Peripheral

   - Core requirements should be optional=false.
   - Nice-to-have requirements should be optional=true.
   - Order requirements from most to least important.
   - Prioritize hot technology evidence when deciding order.

6. Use categories from this set only: [skill, task, tech, hot_technology, knowledge].
"""


def _extract_list(payload: Dict[str, Any], keys: List[str]) -> List[Any]:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, list):
            return v
    return []


def _item_summary(item: Any) -> str:
    if isinstance(item, str):
        return item.strip() or "unknown"
    if isinstance(item, dict):
        for key in ["title", "name", "description", "label", "example", "commodity_title"]:
            v = item.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return str(item)


def build_role_spec_from_onet_raw(
    *,
    role_title: str,
    onet_code: str,
    tech_payload: Optional[Dict[str, Any]] = None,
    hot_tech_payload: Optional[Dict[str, Any]] = None,
) -> RoleSpecModel:
    reqs: List[RoleSpecRequirement] = []

    tech_items = _extract_list(
        tech_payload or {},
        ["technology_skills", "technology", "tools", "tool"],
    )
    for item in tech_items:
        reqs.append(
            RoleSpecRequirement(
                req_summary=_item_summary(item),
                category="tech",
                provenance=[
                    ProvenanceRef(
                        source_type="ONET",
                        source_ids=[onet_code],
                        note="derived from O*NET technology_skills payload",
                    )
                ],
                optional=False,
            )
        )

    hot_items = _extract_list(
        hot_tech_payload or {},
        ["hot_technology", "hotTechnology", "technology", "tool", "tools"],
    )
    for item in hot_items:
        reqs.append(
            RoleSpecRequirement(
                req_summary=_item_summary(item),
                category="hot_technology",
                provenance=[
                    ProvenanceRef(
                        source_type="ONET",
                        source_ids=[onet_code],
                        note="derived from O*NET hot_technology payload",
                    )
                ],
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


def llm_refactor_role_spec_from_onet_raw(
    *,
    desired_role: str,
    role_title: str,
    onet_code: str,
    version: Optional[str],
    summary: Dict[str, Any],
    tech_payload: Optional[Dict[str, Any]] = None,
    hot_tech_payload: Optional[Dict[str, Any]] = None,
    raw_user_text: Optional[str] = None,
) -> RoleSpecModel:
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    llm_struct = llm.with_structured_output(RoleSpecModel, method="json_schema", strict=True)

    raw_payload = {
        "desired_role": desired_role,
        "raw_user_text": raw_user_text,
        "onet_matched_title": role_title,
        "onet_code": onet_code,
        "onet_version": version,
        "summary": summary,
        "technology_skills_payload": tech_payload or {},
        "hot_technology_payload": hot_tech_payload or {},
    }

    prompt = f"""
The user's desired role and the raw O*NET payload for the closest matched occupation are below.

{json.dumps(raw_payload, ensure_ascii=True, default=str)}

Task:
1. Evaluate how well the O*NET occupation (onet_matched_title) matches desired_role. Set confidence_role_match accordingly and add assumptions[] entries for any meaningful gaps.
2. Select canonical_role_title.
3. Produce requirements[] for RoleSpecModel.
4. Rank importance by requirement order and optional flag.
5. For any requirement directly supported by payload, set provenance source_type=ONET, source_ids=[onet_code], and include a short note naming the payload section.
6. For inferred requirements, set provenance source_type=INFERRED, source_ids=null, and give a short provenance.note.
"""
    return llm_struct.invoke(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}]
    )
