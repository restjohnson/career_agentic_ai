from __future__ import annotations

from typing import Any, Dict

from app.state import AgentState, GapReport
from app.tools.gap_analysis_tools import (
    compute_student_scores,
    compute_gaps,
    build_gap_report,
)


def gap_analysis_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gap analysis:
    1. Compute student_level per RoleSpecRequirement by aggregating evidence.
    2. Compute raw_gap and weighted_gap for ALL requirements; rank by weighted_gap descending.
    3. Build the final GapReport.
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
    gap_items = compute_gaps(scores, s.role_spec, s.evidence_items)

    if not gap_items:
        s.gap_report = GapReport(summary="No requirements assessed.", gaps=[])
        return s.model_dump(exclude_none=True)

    # Step 3 — final report
    s.gap_report = build_gap_report(gap_items)

    return s.model_dump(exclude_none=True)
