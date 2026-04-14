from __future__ import annotations

from typing import Any, Dict, List

from app.state import AgentState, EvidenceItem, GapReport
from app.tools.gap_analysis_tools import (
    compute_student_scores,
    compute_gaps,
    build_gap_report,
)
from app.tools.gap_analysis_llm import annotate_gap_items


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

    # Step 4 — LLM annotation and optional score adjustment (non-fatal)
    try:
        item_by_id: Dict[str, EvidenceItem] = {
            item.id: item for item in s.evidence_items if item.id
        }
        evidence_by_req: Dict[str, List[EvidenceItem]] = {
            req.req_summary: [
                item_by_id[i]
                for i in s.student_model.evidence_map.get(req.req_summary, [])
                if i in item_by_id
            ]
            for req in s.role_spec.requirements
        }

        annotation_map = annotate_gap_items(s.gap_report.gaps, evidence_by_req, s.role_spec)

        # Requirement lookup needed to recompute weighted_gap when score is adjusted
        req_by_summary = {req.req_summary: req for req in s.role_spec.requirements}

        for gap in s.gap_report.gaps:
            ann = annotation_map.get(gap.summary)
            if not ann:
                continue

            gap.reasoning = ann.reasoning

            if ann.adjusted_student_level is not None:
                adj = round(max(0.0, min(4.0, ann.adjusted_student_level)), 4)
                req = req_by_summary.get(gap.summary)
                if req:
                    gap.student_level = adj
                    gap.raw_gap       = max(0.0, round(req.required_level - adj, 4))
                    gap.weighted_gap  = round(req.importance * gap.raw_gap, 4)
                    # Only promote to "met" — other gap_type labels reflect evidence
                    # classification (no_evidence, claimed_only, etc.) which doesn't
                    # change because the LLM assessed the quality differently
                    if gap.raw_gap < 0.5:
                        gap.gap_type = "met"

        # Re-sort after any weighted_gap adjustments
        s.gap_report.gaps.sort(key=lambda g: g.weighted_gap, reverse=True)

    except Exception as e:
        s.errors.append(f"gap_analysis: annotation failed (non-fatal): {type(e).__name__}: {e}")

    return s.model_dump(exclude_none=True)
