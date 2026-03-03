from __future__ import annotations

from typing import Any, Dict

from app.state import AgentState
from app.tools.gap_analysis_tools import (
    finalise_knowledge_confidence,
    derive_root_causes,
    build_gap_report,
)


def gap_analysis_phase2_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Phase 2 of gap analysis (runs after optional knowledge self-assessment interrupt):
    1. Finalise knowledge confidence per prerequisite using user_knowledge_inputs.
    2. Derive gap_root_cause rule-based from student_score + knowledge confidence.
    3. Build and write the final GapReport to state.
    """
    s = AgentState.model_validate(state)
    s.step = "gap_analysis_phase2"

    if not s.gap_report or not s.gap_report.gaps:
        s.errors.append("gap_analysis_phase2: no gap_items found from phase 1.")
        return s.model_dump(exclude_none=True)

    gap_items = s.gap_report.gaps

    # collect all prerequisites across all gap items
    all_prerequisites = [
        prereq
        for gap in gap_items
        for prereq in gap.knowledge_prerequisites
    ]

    # Step 1 — finalise confidence
    finalised = finalise_knowledge_confidence(all_prerequisites)

    # write finalised prerequisites back — they are mutated in place but
    # re-attach to be explicit
    def _norm(s: str) -> str:
        return s.lower().strip().rstrip(".,;:")

    prereqs_by_parent: Dict[str, list] = {}
    for p in finalised:
        prereqs_by_parent.setdefault(_norm(p.parent_skill_gap), []).append(p)
    for gap in gap_items:
        gap.knowledge_prerequisites = prereqs_by_parent.get(_norm(gap.summary), [])

    # Step 2 — derive root causes
    gap_items = derive_root_causes(gap_items, finalised)

    # Step 3 — build final report
    s.gap_report = build_gap_report(gap_items)

    return s.model_dump(exclude_none=True)
