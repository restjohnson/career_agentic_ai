from __future__ import annotations

from typing import Dict, List

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.state import RoleSpecModel


class _ReqAssessment(BaseModel):
    req_index: int = Field(description="0-based index of the requirement in the list provided")
    student_level: float = Field(ge=0.0, le=3.0)
    reasoning: str


class _HolisticResult(BaseModel):
    assessments: List[_ReqAssessment]


_SYSTEM = """\
You are a career counselor estimating a student's competency for a target role.

You will be given a resume and a numbered list of role requirements. For each requirement,
estimate the student's current competency on a 0.0–3.0 scale based on EVERYTHING they have
written — work history, projects, coursework, and skill claims — without distinguishing
between evidence types. Treat a skill mentioned in a job description the same as one listed
in a skills section.

Scale:
  3.0  Extensively described across multiple contexts with clear outcomes
  2.0  Clearly mentioned with some detail or context
  1.0  Briefly mentioned or peripheral exposure only
  0.0  Not mentioned or entirely unrelated

Return one assessment per requirement using its 0-based index. Cover every requirement.
"""


def assess_student_holistic(
    markdown_content: str,
    role_spec: RoleSpecModel,
) -> Dict[str, float]:
    """
    Single LLM call that holistically estimates student_level per requirement
    from Docling-parsed resume markdown, without differentiating evidence types.

    Returns Dict[req_summary -> student_level (0.0–3.0)].
    Missing requirements default to 0.0.
    """
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    llm_struct = llm.with_structured_output(
        _HolisticResult, method="json_schema", strict=True
    )

    req_index: List[str] = [r.req_summary for r in role_spec.requirements]
    req_list = "\n".join(
        f"{i}. [{r.category}] {r.req_summary}"
        for i, r in enumerate(role_spec.requirements)
    )

    user_msg = (
        f"Target role: {role_spec.canonical_role_title}\n\n"
        f"Requirements (use the 0-based index in your response):\n{req_list}\n\n"
        f"Resume:\n{markdown_content}"
    )

    result: _HolisticResult = llm_struct.invoke(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": user_msg},
        ]
    )

    scores: Dict[str, float] = {}
    for a in result.assessments:
        if 0 <= a.req_index < len(req_index):
            scores[req_index[a.req_index]] = round(min(3.0, max(0.0, a.student_level)), 4)

    for req_summary in req_index:
        scores.setdefault(req_summary, 0.0)

    return scores
