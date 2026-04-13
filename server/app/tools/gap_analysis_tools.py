from __future__ import annotations

from typing import Any, Dict, List

from app.state import (
    EvidenceItem,
    GapItem,
    GapReport,
    RoleSpecModel,
    StudentModel,
)

# ---------------------------------------------------------------------------
# Phase 1 — student score computation
# ---------------------------------------------------------------------------

def aggregate_proficiency(items: List[EvidenceItem]) -> int:
    """
    Derive proficiency from item_type only.
    Proficiency is an emergent property of the evidence collection,
    not a per-item score.

    experience → 3 (professional/work context)
    project    → 2 (independent work)
    coursework → 1 (guided/academic)
    claim      → 0 (self-reported only, no demonstration)
    """
    if any(i.item_type == "experience" for i in items):
        return 3
    if any(i.item_type == "project" for i in items):
        return 2
    if any(i.item_type == "coursework" for i in items):
        return 1
    return 0


def aggregate_confidence(items: List[EvidenceItem]) -> float:
    """Bayesian combination of independent confidence signals."""
    if not items:
        return 0.0
    result = 1.0
    for item in items:
        result *= (1.0 - item.confidence)
    return round(1.0 - result, 4)


def compute_student_scores(
    evidence_items: List[EvidenceItem],
    student_model: StudentModel,
    role_spec: RoleSpecModel,
) -> Dict[str, Dict[str, Any]]:
    """
    For each RoleSpecRequirement, aggregate all matching EvidenceItems into
    a student level.

    Returns a dict keyed by req_summary with:
      proficiency, confidence, student_level, evidence_item_ids
    """
    item_by_id: Dict[str, EvidenceItem] = {
        item.id: item for item in evidence_items if item.id
    }

    scores: Dict[str, Dict[str, Any]] = {}
    for req in role_spec.requirements:
        ids = student_model.evidence_map.get(req.req_summary, [])
        matching = [item_by_id[i] for i in ids if i in item_by_id]

        proficiency   = aggregate_proficiency(matching)
        confidence    = aggregate_confidence(matching)
        student_level = round(proficiency * confidence, 4)

        scores[req.req_summary] = {
            "proficiency": proficiency,
            "confidence": confidence,
            "student_level": student_level,
            "evidence_item_ids": ids,
        }

    return scores


_MET_THRESHOLD = 0.5  # raw_gap below this is considered met

def compute_gaps(
    scores: Dict[str, Dict[str, Any]],
    role_spec: RoleSpecModel,
    evidence_items: List[EvidenceItem],
) -> List[GapItem]:
    """
    Compute raw_gap and weighted_gap for ALL requirements (no filter).
    Classify each with a gap_type label and sort by weighted_gap descending.
    Requirements the student has met naturally sink to the bottom due to low weighted_gap.

    gap_type labels:
      met          — raw_gap < _MET_THRESHOLD (student level meets requirement)
      no_evidence  — no evidence items mapped to this requirement
      claimed_only — all mapped items are claim type (listed but not demonstrated)
      partial      — demonstrated but below required level
      optional_gap — optional requirement with a gap
    """
    item_by_id: Dict[str, EvidenceItem] = {
        item.id: item for item in evidence_items if item.id
    }

    gap_items: List[GapItem] = []

    for req in role_spec.requirements:
        s             = scores.get(req.req_summary, {})
        student_level = s.get("student_level", 0.0)
        proficiency   = s.get("proficiency", 0)
        confidence    = s.get("confidence", 0.0)
        ids           = s.get("evidence_item_ids", [])

        raw_gap      = max(0.0, round(req.required_level - student_level, 4))
        weighted_gap = round(req.importance * raw_gap, 4)

        if raw_gap < _MET_THRESHOLD:
            gap_type = "met"
        elif not ids:
            gap_type = "no_evidence"
        elif all(item_by_id[i].item_type == "claim" for i in ids if i in item_by_id):
            gap_type = "claimed_only"
        elif req.optional:
            gap_type = "optional_gap"
        else:
            gap_type = "partial"

        gap_items.append(GapItem(
            summary=req.req_summary,
            category=req.category,
            required_level=req.required_level,
            student_level=student_level,
            raw_gap=raw_gap,
            weighted_gap=weighted_gap,
            proficiency=proficiency,
            confidence=confidence,
            gap_type=gap_type,
            evidence_item_ids=ids,
        ))

    gap_items.sort(key=lambda g: g.weighted_gap, reverse=True)
    return gap_items


def build_gap_report(gap_items: List[GapItem]) -> GapReport:
    """Assemble the final GapReport from finalised GapItems."""
    n_total        = len(gap_items)
    n_met          = sum(1 for g in gap_items if g.gap_type == "met")
    n_no_evidence  = sum(1 for g in gap_items if g.gap_type == "no_evidence")
    n_claimed_only = sum(1 for g in gap_items if g.gap_type == "claimed_only")
    n_partial      = sum(1 for g in gap_items if g.gap_type == "partial")
    n_optional     = sum(1 for g in gap_items if g.gap_type == "optional_gap")

    parts = [f"{n_total} requirement(s) assessed."]
    if n_met:          parts.append(f"{n_met} met.")
    if n_no_evidence:  parts.append(f"{n_no_evidence} with no evidence.")
    if n_claimed_only: parts.append(f"{n_claimed_only} claimed but not demonstrated.")
    if n_partial:      parts.append(f"{n_partial} partially evidenced.")
    if n_optional:     parts.append(f"{n_optional} optional gap(s).")

    return GapReport(summary=" ".join(parts), gaps=gap_items)
