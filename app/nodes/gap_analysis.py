from __future__ import annotations

from typing import Any, Dict

from app.state import AgentState, GapReport
from app.tools.gap_analysis_tools import (
    compute_student_scores,
    compute_gaps,
    decompose_knowledge_prerequisites,
    derive_root_causes,
    build_gap_report,
)


def _norm(s: str) -> str:
    return s.lower().strip().rstrip(".,;:")


def gap_analysis_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gap analysis:
    1. Compute student_score per RoleSpecRequirement by aggregating evidence.
    2. Compute raw_gap and weighted_gap; rank by weighted_gap descending.
    3. Decompose top gaps into knowledge prerequisites via LLM.
    4. Derive gap_root_cause rule-based from student_score + knowledge confidence.
    5. Build the final GapReport.
    """
    s = AgentState.model_validate(state)
    s.step = "gap_analysis"

    if not s.role_spec:
        s.errors.append("gap_analysis: role_spec missing from state.")
        return s.model_dump(exclude_none=True)

    if not s.student_model:
        s.errors.append("gap_analysis: student_model missing from state.")
        return s.model_dump(exclude_none=True)

    # Step 1 & 2 — scores and gaps
    scores = compute_student_scores(s.evidence_items, s.student_model, s.role_spec)
    gap_items = compute_gaps(scores, s.role_spec)

    if not gap_items:
        s.gap_report = GapReport(summary="No gaps identified.", gaps=[])
        return s.model_dump(exclude_none=True)

    # Step 3 — knowledge decomposition (LLM)
    try:
        prerequisites = decompose_knowledge_prerequisites(
            gap_items=gap_items,
            evidence_items=s.evidence_items,
            role_title=s.role_spec.canonical_role_title,
        )
    except Exception as e:
        s.errors.append(f"gap_analysis: knowledge decomposition failed: {type(e).__name__}: {e}")
        prerequisites = []

    # attach prerequisites to gap items using normalised matching
    gap_by_norm = {_norm(g.summary): g for g in gap_items}
    prereqs_by_parent: Dict[str, list] = {}
    for p in prerequisites:
        canonical_gap = gap_by_norm.get(_norm(p.parent_skill_gap))
        if canonical_gap:
            prereqs_by_parent.setdefault(canonical_gap.summary, []).append(p)
    for gap in gap_items:
        gap.knowledge_prerequisites = prereqs_by_parent.get(gap.summary, [])

    # Step 4 & 5 — root causes and final report
    gap_items = derive_root_causes(gap_items, prerequisites)
    s.gap_report = build_gap_report(gap_items)

    return s.model_dump(exclude_none=True)
