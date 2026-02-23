# app/tools/role_spec_llm.py
from __future__ import annotations
from typing import List
from langchain_openai import ChatOpenAI
from app.state import RoleModel, RoleSpecModel, ProvenanceRef, RoleSpecRequirement


_SYSTEM = """You are an expert role intake analyst.

Input is a baseline RoleModel derived from O*NET. You MUST NOT overwrite baseline.
You must produce a CURRENT role spec in RoleSpecModel.

Rules:
1. Every requirement must include provenance[].
2. Evaluate importance implicitly:
   - Core requirements should be optional=false.
   - Nice-to-have requirements should be optional=true.
   - Order requirements from most to least important.
   - Take Precedence to requirements with labels = "hot_technology"
3. If a requirement is supported by baseline, include provenance with:
   - source_type = ONET
   - source_ids = [the baseline requirement source_id(s)]
4. If you add a requirement not supported by baseline:
   - evaluation whether optional=false or optional=true and return appropraitely
   - provenance source_type must be INFERRED
   - source_ids must be empty
   - include a short provenance.note explaining why inferred
5. Sustain the labels [skills, tasks, tech, hot_technology] as gotten from ONET
6. Do not hallucinate tools/skills. Prefer leaving items out over inventing them.
"""


def build_role_spec_from_onet(role_model: RoleModel) -> RoleSpecModel:
    reqs: List[RoleSpecRequirement] = []
    for r in role_model.requirements:
        if not r.source_id:
            src_ids = []
            note = "Missing baseline source_id"
        else:
            src_ids = [r.source_id]
            note = None

        reqs.append(
            RoleSpecRequirement(
                label=r.label,
                category=r.req_type,
                provenance=[ProvenanceRef(source_type="ONET", source_ids=src_ids, note=note)],
                optional=False,
            )
        )
    return RoleSpecModel(
        canonical_role_title=role_model.role_title,
        matched_onet_code=role_model.onet_code,
        confidence_role_match=0.8,
        requirements=reqs,
        assumptions=[],
    )


def llm_refactor_role_spec(role_model: RoleModel) -> RoleSpecModel:
    llm = ChatOpenAI(model="gpt-4o", temperature=0.2)
    llm_struct = llm.with_structured_output(RoleSpecModel)

    baseline = role_model.model_dump()

    prompt = f"""
Baseline RoleModel (O*NET-derived). Use the baseline requirement source_id values for ONET provenance.

{baseline}

Task:
1. Select canonical_role_title.
2. Produce requirements[] for RoleSpecModel.
3. Rank importance by requirement order and optional flag (no numeric priority field).
4. For each requirement supported by baseline: provenance must include source_type=ONET and source_ids containing the matching baseline source_id(s).
5. For inferred requirements: optional=true, source_type=INFERRED, source_ids=[], and give a short provenance.note.
"""
    return llm_struct.invoke(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": prompt}]
    )
