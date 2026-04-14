from __future__ import annotations

from typing import Dict, List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.state import EvidenceItem, GapItem, RoleSpecModel


# ---------------------------------------------------------------------------
# Structured output schema
# ---------------------------------------------------------------------------

class _GapAnnotation(BaseModel):
    req_summary: str
    reasoning: str
    adjusted_student_level: Optional[float] = None
    # None      = formula is correct; do not override
    # 0.0–3.0   = LLM-assessed level based on evidence quality
    # 3.0–4.0   = demonstrated mastery; use sparingly


class _AnnotationBatch(BaseModel):
    annotations: List[_GapAnnotation] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are a career evidence analyst. For each role requirement, you receive the \
formula-computed student level and the evidence items that produced that score.

Your task: for each requirement, write a 1–2 sentence reasoning annotation AND \
decide whether the formula's student_level accurately reflects what the evidence \
actually demonstrates.

SCORING RULES:
- The formula maps item type to proficiency: experience=3, project=2, coursework=1, claim=0
  then multiplies by a confidence score (0–1).
- The formula is blind to evidence QUALITY — a "Hello World app" and a "distributed ML \
pipeline" both score proficiency=2 as projects.
- Provide adjusted_student_level ONLY when evidence content clearly warrants a different score.
- Scale: 0.0–3.0 matches the formula range; push above 3.0 (up to 4.0) ONLY for \
demonstrated mastery (e.g. production deployment, measurable outcomes at scale).
- When in doubt, leave adjusted_student_level as null and let the formula stand.

ANNOTATION RULES:
1. Be specific about evidence content — distinguish depth and quality.
2. No evidence mapped → state clearly that none was found for this requirement.
3. Claims only → note it is listed but not demonstrated through work.
4. Coursework → note the guided/academic context versus independent work.
5. When you adjust the score, explain why the formula misrepresents the evidence.
6. 1–2 sentences max per requirement. Be direct.
7. Copy req_summary strings character-for-character as provided — do not paraphrase.
"""


def _format_requirement_block(
    gap: GapItem,
    evidence_items: List[EvidenceItem],
    index: int,
) -> str:
    lines = [
        f"[{index}] Requirement: \"{gap.summary}\"",
        f"     Formula score: proficiency={gap.proficiency}/3, "
        f"confidence={gap.confidence:.2f}, student_level={gap.student_level:.4f}",
        f"     Gap type: {gap.gap_type}",
    ]

    if evidence_items:
        lines.append(f"     Evidence ({len(evidence_items)} item(s)):")
        for item in evidence_items:
            line = f"       [{item.item_type}] (confidence={item.confidence:.2f}) {item.summary}"
            if item.snippet:
                line += f' — excerpt: "{item.snippet[:120]}"'
            lines.append(line)
    else:
        lines.append("     Evidence (0 items): (none)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def annotate_gap_items(
    gap_items: List[GapItem],
    evidence_by_req: Dict[str, List[EvidenceItem]],
    role_spec: Optional[RoleSpecModel] = None,
) -> Dict[str, _GapAnnotation]:
    """
    Single batched LLM call that annotates each GapItem with:
    - reasoning: 1–2 sentences explaining why the student's level is what it is
    - adjusted_student_level: optional override when evidence quality differs from formula assumption

    Returns dict mapping req_summary → _GapAnnotation.
    Caller is responsible for try/except — this function lets exceptions propagate.
    """
    if not gap_items:
        return {}

    role_title = role_spec.canonical_role_title if role_spec else "the target role"

    req_blocks = [
        _format_requirement_block(gap, evidence_by_req.get(gap.summary, []), i)
        for i, gap in enumerate(gap_items, 1)
    ]

    user_prompt = (
        f"Role: {role_title}\n\n"
        "Annotate each requirement below.\n\n"
        + "\n\n".join(req_blocks)
        + "\n\nReturn exactly one annotation per requirement in the same order."
    )

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    llm_struct = llm.with_structured_output(_AnnotationBatch, method="json_schema", strict=True)

    result = llm_struct.invoke([
        {"role": "system", "content": _SYSTEM},
        {"role": "user",   "content": user_prompt},
    ])

    return {ann.req_summary: ann for ann in result.annotations}
