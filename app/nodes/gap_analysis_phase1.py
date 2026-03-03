from __future__ import annotations

from typing import Any, Dict

from app.state import AgentState
from app.tools.gap_analysis_tools import (
    compute_student_scores,
    compute_gaps,
    decompose_knowledge_prerequisites,
)


def _norm(s: str) -> str:
    return s.lower().strip().rstrip(".,;:")


def gap_analysis_phase1_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 1 of gap analysis:
    1. Compute student_score per RoleSpecRequirement by aggregating evidence.
    2. Compute raw_gap and weighted_gap; rank by weighted_gap descending.
    3. Decompose top gaps into knowledge prerequisites via LLM.
    """
    s = AgentState.model_validate(state)
    s.step = "gap_analysis_phase1"

    if not s.role_spec:
        s.errors.append("gap_analysis_phase1: role_spec missing from state.")
        return s.model_dump(exclude_none=True)

    if not s.student_model:
        s.errors.append("gap_analysis_phase1: student_model missing from state.")
        return s.model_dump(exclude_none=True)

    # Step 1 & 2 — scores and gaps
    scores = compute_student_scores(s.evidence_items, s.student_model, s.role_spec)
    gap_items = compute_gaps(scores, s.role_spec)

    if not gap_items:
        # no gaps found — write empty report and proceed
        from app.state import GapReport
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
        s.errors.append(f"gap_analysis_phase1: knowledge decomposition failed: {type(e).__name__}: {e}")
        prerequisites = []

    # store gap_items and prerequisites in gap_report.gaps temporarily
    # (root_cause and final_confidence not yet computed — done in phase 2)
    # attach prerequisites to gap items now so phase 2 can finalise them
    # Use normalised matching so minor LLM punctuation drift doesn't break lookup.
    gap_by_norm = {_norm(g.summary): g for g in gap_items}
    prereqs_by_parent: Dict[str, list] = {}
    for p in prerequisites:
        canonical_gap = gap_by_norm.get(_norm(p.parent_skill_gap))
        if canonical_gap:
            prereqs_by_parent.setdefault(canonical_gap.summary, []).append(p)

    for gap in gap_items:
        gap.knowledge_prerequisites = prereqs_by_parent.get(gap.summary, [])

    from app.state import GapReport
    s.gap_report = GapReport(summary="pending phase 2", gaps=gap_items)

    return s.model_dump(exclude_none=True)
