# app/tools/role_spec_llm.py
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from pydantic import BaseModel
from langchain_openai import ChatOpenAI

from app.state import ProvenanceRef, RoleSpecModel, RoleSpecRequirement


_SYSTEM = """You are an expert role intake analyst with deep knowledge of industry hiring standards.

Input is the user's desired role and raw O*NET payload data for the closest matched occupation.
Your job has two parts: (1) evaluate whether the O*NET occupation matches the user's intent, and (2) produce a CURATED, CURRENT role spec by synthesizing the O*NET evidence with your own domain expertise.

CRITICAL — You are a curator, not a transcriber:
- Do NOT map each O*NET item directly to one requirement. O*NET is a reference corpus, not a spec template.
- Consolidate overlapping O*NET items into a single, precise requirement (e.g. if skills_payload lists both "Active Learning" and "Learning Strategies", merge them into one requirement if they represent the same practitioner expectation for this role).
- Translate O*NET's generic occupational labels into role-specific, actionable language (e.g. "Mathematics" from knowledge_payload → "Applied probability and statistics for model evaluation and uncertainty quantification").
- Drop O*NET items that are not genuinely differentiating for this specific role — inclusion requires a clear hiring signal, not just taxonomic presence.
- At least 3 requirements must be INFERRED (source_type=INFERRED), meaning they reflect practitioner expectations that O*NET does not enumerate. A spec with fewer than 3 inferred requirements has not applied domain expertise.

Rules:
1. Evaluate match quality first:
   - Compare desired_role (and raw_user_text if provided) against the O*NET occupation title and summary.
   - Set confidence_role_match (0.0–1.0) to reflect how well the O*NET occupation represents what the user actually wants.
   - Add an entry to assumptions[] for any meaningful gap between what the user asked for and what O*NET returned.

2. Every requirement must include provenance[].

3. ONET-sourced requirements (things grounded in the payload):
   - provenance.source_type must be ONET
   - provenance.source_ids must be [onet_code] — use the onet_code value from the payload as the single reference ID
   - provenance.note should name the specific payload section:
     * "O*NET technology_skills" for items from technology_skills_payload
     * "O*NET hot_technology" for items from hot_technology_payload
     * "O*NET skills taxonomy" for items from skills_payload
     * "O*NET tasks" for items from tasks_payload
     * "O*NET knowledge domains" for items from knowledge_payload
     * "O*NET occupation summary" for items drawn from the summary text
   - Do not invent specific tool names or versions beyond what the payload states.
   - If you consolidate multiple O*NET items into one requirement, name all contributing sections in the note.

4. INFERRED requirements (practitioner expectations the payload omits):
   - You MUST actively apply domain expertise to identify at least 3 requirements O*NET under-specifies.
   - Ask yourself: "What would a hiring manager for this role expect that is missing from this payload?"
   - Common O*NET gaps: current tooling not yet in ONET (e.g. recent frameworks), research or methodological rigor, cross-functional communication, MLOps/deployment practices, experimentation culture expectations.
   - provenance.source_type must be INFERRED
   - provenance.source_ids must be null
   - provenance.note must explain the reasoning clearly.
   - Inferred requirements must be grounded in well-known industry practice, not speculation.

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

6. Use categories from this set only, with these exact definitions:
   - tech          : Specific tools, platforms, libraries, or languages (e.g. Python, AWS, SQL)
   - hot_technology: Emerging or in-demand tools with high current market signal (e.g. MLflow, Kubernetes, Spark)
   - skill         : Soft or cross-functional abilities (e.g. communication, collaboration, problem-solving)
   - knowledge     : Domain understanding or conceptual expertise (e.g. statistics, ML theory, system design, ethics)
   - task          : Concrete job responsibilities or activities performed in the role (e.g. data preprocessing, model evaluation, code review)
"""


# ---------------------------------------------------------------------------
# Dimensional decomposition (RAG-Fusion)
# ---------------------------------------------------------------------------

class _QueryList(BaseModel):
    """Internal model for LLM structured output of query decomposition."""

    queries: List[str]


def decompose_role_into_dimensions(desired_role: str) -> List[str]:
    """
    Generate 3-5 sub-queries each covering a DIFFERENT dimension of the role.

    NOT keyword variants — each sub-query probes a genuinely different facet:
    technical skills, domain knowledge, core responsibilities, credentials,
    collaboration/leadership expectations.

    Falls back to [desired_role] on any error so the pipeline always has
    at least one sub-query to retrieve from.
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    llm_struct = llm.with_structured_output(
        _QueryList, method="json_schema", strict=True
    )

    system = (
        "You are a role analysis assistant. "
        "Given a job role title, decompose it into 3-5 distinct search queries "
        "where EACH query captures a DIFFERENT dimension of the role. "
        "Dimensions to consider: technical skills, domain knowledge, core responsibilities, "
        "required credentials/education, and soft skills or collaboration expectations. "
        "Each query should be a phrase (3-8 words) that would retrieve job postings "
        "emphasising that specific dimension. "
        "Do NOT produce keyword variants of the same idea — each must cover a "
        "genuinely different aspect of the role."
    )

    try:
        result: _QueryList = llm_struct.invoke([
            {"role": "system", "content": system},
            {"role": "user", "content": f'Desired role: "{desired_role}"'},
        ])
        queries = [q.strip() for q in result.queries if q.strip()]
    except Exception:
        queries = []

    if not queries:
        return [desired_role]

    # Dimensions come first; original role title appended as a safety-net fallback
    seen: set[str] = set()
    deduped: List[str] = []
    for q in queries + [desired_role]:
        if q.lower() not in seen:
            seen.add(q.lower())
            deduped.append(q)
    return deduped[:5]


def _title_similarity(a: str, b: str) -> float:
    """
    Jaccard token-overlap similarity between two job title strings.
    Range [0.0, 1.0]; higher = more similar.
    """
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def rank_onet_candidates(
    candidates: List[Dict[str, Any]], desired_role: str
) -> List[Dict[str, Any]]:
    """
    Deduplicate ONET candidates by onet_code and rank by title Jaccard similarity.

    Returns candidates sorted descending by similarity to desired_role.
    """
    seen_codes: set[str] = set()
    unique: List[Dict[str, Any]] = []
    for c in candidates:
        code = c.get("code") or c.get("onet_code") or c.get("id")
        if code and code not in seen_codes:
            seen_codes.add(code)
            unique.append(c)

    def score(c: Dict[str, Any]) -> float:
        title = c.get("title") or c.get("name") or ""
        return _title_similarity(title, desired_role)

    return sorted(unique, key=score, reverse=True)


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


_SYSTEM_LLM_ONLY = """You are an expert role intake analyst with deep knowledge of industry hiring standards.

Your task is to generate a curated role specification for a given job title using only your knowledge of what employers actually expect for this role.

CRITICAL — You are a curator, not an enumerator:
- Do NOT generate requirements to achieve category coverage. Only include a requirement if it reflects a genuine hiring signal for this specific role.
- Consolidate overlapping expectations into a single, precise requirement rather than listing related items separately.
- Use role-specific, actionable language — not generic occupational labels.
- Do not pad the spec. A focused spec of 8–12 well-chosen requirements is better than an exhaustive list of 15+.

Rules:
1. Produce a complete and accurate role specification that reflects what a hiring manager would genuinely evaluate candidates against.
2. All provenance entries must have source_type=INFERRED, source_ids=null, and a brief note explaining why the requirement is a well-known industry expectation for this role.
3. Set matched_onet_code to null.
4. Set confidence_role_match between 0.4 and 0.6 to reflect uncertainty without external grounding.
5. For every requirement, assign required_level (0–4) and importance (1–5):
   - required_level 4: Essential — role cannot be performed without this
   - required_level 3: Expected of all qualified candidates
   - required_level 2: Differentiates good from average candidates
   - required_level 1: Nice-to-have
   - importance 5: Core differentiator — central to what makes this role distinct
   - importance 4: High importance — consistently expected
   - importance 3: Standard requirement
   - importance 2: Supporting requirement
   - importance 1: Peripheral
6. Use categories from this set only, with these exact definitions:
   - tech          : Specific tools, platforms, libraries, or languages (e.g. Python, AWS, SQL)
   - hot_technology: Emerging or in-demand tools with high current market signal (e.g. MLflow, Kubernetes, Spark)
   - skill         : Soft or cross-functional abilities (e.g. communication, collaboration, problem-solving)
   - knowledge     : Domain understanding or conceptual expertise (e.g. statistics, ML theory, system design, ethics)
   - task          : Concrete job responsibilities or activities performed in the role (e.g. data preprocessing, model evaluation, code review)
7. Core requirements must be optional=false; nice-to-have must be optional=true.
8. Order requirements from most to least important.
"""


def llm_only_role_spec(desired_role: str) -> RoleSpecModel:
    """
    Generate a RoleSpecModel using LLM parametric knowledge only.
    No O*NET data is provided. All requirements are INFERRED.
    Used for Ablation 1 (ablation1_llm_only condition).
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.2)
    llm_struct = llm.with_structured_output(RoleSpecModel, method="json_schema", strict=True)

    prompt = (
        f'Generate a curated role specification for: "{desired_role}"\n\n'
        "Include only requirements that reflect genuine hiring expectations for this specific role. "
        "Use only your training knowledge — do not reference external sources."
    )

    result: RoleSpecModel = llm_struct.invoke([
        {"role": "system", "content": _SYSTEM_LLM_ONLY},
        {"role": "user", "content": prompt},
    ])

    result.matched_onet_code = None
    return result


def llm_refactor_role_spec_from_onet_raw(
    *,
    desired_role: str,
    role_title: str,
    onet_code: str,
    version: Optional[str],
    summary: Dict[str, Any],
    tech_payload: Optional[Dict[str, Any]] = None,
    hot_tech_payload: Optional[Dict[str, Any]] = None,
    skills_payload: Optional[List[Dict[str, Any]]] = None,
    tasks_payload: Optional[List[Dict[str, Any]]] = None,
    knowledge_payload: Optional[List[Dict[str, Any]]] = None,
    raw_user_text: Optional[str] = None,
    few_shot_examples: Optional[List[Dict[str, Any]]] = None,
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
        "skills_payload": skills_payload or [],
        "tasks_payload": tasks_payload or [],
        "knowledge_payload": knowledge_payload or [],
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

    # Build messages: system → few-shot examples (if any) → real user prompt
    messages = [{"role": "system", "content": _SYSTEM}]

    if few_shot_examples:
        for ex in few_shot_examples:
            # Synthetic user turn: minimal prompt mimicking the real one
            example_user = (
                f'Desired role: "{ex.get("role", "Unknown")}"\n'
                f"[Example O*NET payload omitted — calibration example only]"
            )

            # Synthetic assistant turn: abbreviated role spec skeleton
            example_assistant = json.dumps(
                {
                    "canonical_role_title": ex.get("role", "Unknown"),
                    "matched_onet_code": None,
                    "confidence_role_match": 0.85,
                    "requirements": ex.get("requirements", []),
                    "assumptions": [],
                },
                ensure_ascii=True,
            )

            messages.append({"role": "user", "content": example_user})
            messages.append({"role": "assistant", "content": example_assistant})

    # Real user prompt
    messages.append({"role": "user", "content": prompt})

    return llm_struct.invoke(messages)
