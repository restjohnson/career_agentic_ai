from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.state import (
    EvidenceItem,
    GapItem,
    GapReport,
    KnowledgePrerequisite,
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


def compute_gaps_selfreport(
    selfreport_scores: Dict[str, float],
    role_spec: RoleSpecModel,
) -> List[GapItem]:
    """
    Compute gaps for the selfreport condition.

    student_level comes from the holistic LLM assessment (no evidence items).
    gap_type reflects holistic score magnitude rather than evidence type:
      met          — raw_gap < _MET_THRESHOLD
      partial      — student_level >= 1.0 (substantial mention)
      claimed_only — 0 < student_level < 1.0 (minimal mention)
      no_evidence  — student_level == 0.0 (not mentioned)
    """
    gap_items: List[GapItem] = []

    for req in role_spec.requirements:
        student_level = selfreport_scores.get(req.req_summary, 0.0)
        raw_gap      = max(0.0, round(req.required_level - student_level, 4))
        weighted_gap = round(req.importance * raw_gap, 4)

        if raw_gap < _MET_THRESHOLD:
            gap_type = "met"
        elif student_level >= 1.0:
            gap_type = "partial"
        elif student_level > 0.0:
            gap_type = "claimed_only"
        else:
            gap_type = "no_evidence"

        gap_items.append(GapItem(
            summary=req.req_summary,
            category=req.category,
            required_level=req.required_level,
            student_level=student_level,
            raw_gap=raw_gap,
            weighted_gap=weighted_gap,
            proficiency=0,
            confidence=0.0,
            gap_type=gap_type,
            evidence_item_ids=[],
        ))

    gap_items.sort(key=lambda g: g.weighted_gap, reverse=True)
    return gap_items


# ---------------------------------------------------------------------------
# knowledge decomposition (LLM call)
# ---------------------------------------------------------------------------

class _KnowledgePrereqRaw(BaseModel):
    concept: str
    parent_skill_gap: str
    is_foundational: bool


class _DecompositionResult(BaseModel):
    prerequisites: List[_KnowledgePrereqRaw]


_DECOMP_SYSTEM = """You are an expert in career skills and conceptual knowledge requirements.

You are given a list of skill gaps for a student targeting a specific role, and a list of evidence items the student has submitted.

For each skill gap, identify the specific conceptual/theoretical knowledge concepts that underpin it.
Then assess whether the student's evidence implies any understanding of each concept.

Rules:
1. Produce specific, role-grounded knowledge concepts — not generic categories.
   Good: "Backpropagation and gradient descent", "CAP theorem", "SQL query optimisation"
   Bad: "Mathematics", "Computer Science", "Databases"
2. is_foundational = true if the concept is a hard prerequisite (the skill cannot be
   learned without it). is_foundational = false if it is supporting or deepening knowledge.
3. Deduplicate: if the same concept underpins multiple skill gaps, produce it once under
   the most relevant parent.
4. Limit to at most 4 prerequisites per skill gap. Focus on the most impactful ones.
"""


def decompose_knowledge_prerequisites(
    gap_items: List[GapItem],
    evidence_items: List[EvidenceItem],
    role_title: str,
    top_n: int = 8,
) -> List[KnowledgePrerequisite]:
    """
    For the top-N gaps by weighted_gap, call the LLM to decompose each into
    knowledge prerequisites. Returns deduplicated KnowledgePrerequisite list
    with needs_self_assessment flagged.
    """
    qualifying = [g for g in gap_items if g.raw_gap > 0.5 and g.gap_type not in ("optional_gap", "met")]
    qualifying = qualifying[:top_n]

    if not qualifying:
        return []

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    llm_struct = llm.with_structured_output(_DecompositionResult, method="json_schema", strict=True)

    evidence_summaries = [item.summary for item in evidence_items]

    gap_lines = "\n".join(
        f"- [{g.category}] {g.summary} (raw_gap={g.raw_gap}, weighted_gap={g.weighted_gap})"
        for g in qualifying
    )

    prompt = f"""\
Role: {role_title}

Skill gaps to decompose:
{gap_lines}

Student evidence (summaries):
{chr(10).join(f"- {s}" for s in evidence_summaries)}

Identify the knowledge prerequisites for each gap and assess evidence-based confidence.
"""

    result: _DecompositionResult = llm_struct.invoke(
        [{"role": "system", "content": _DECOMP_SYSTEM}, {"role": "user", "content": prompt}]
    )

    # deduplicate by concept (case-insensitive), keep highest-weighted-gap parent
    # Use normalised keys so trailing punctuation drift from the LLM doesn't break lookup.
    def _norm(s: str) -> str:
        return s.lower().strip().rstrip(".,;:")

    gap_weight: Dict[str, float] = {_norm(g.summary): g.weighted_gap for g in qualifying}
    seen: Dict[str, _KnowledgePrereqRaw] = {}
    for p in result.prerequisites:
        key = p.concept.lower().strip()
        if key not in seen:
            seen[key] = p
        else:
            # keep the one whose parent has higher weighted_gap
            existing_weight = gap_weight.get(_norm(seen[key].parent_skill_gap), 0)
            new_weight = gap_weight.get(_norm(p.parent_skill_gap), 0)
            if new_weight > existing_weight:
                seen[key] = p

    deduped = list(seen.values())

    prerequisites: List[KnowledgePrerequisite] = []
    for p in deduped:
        prerequisites.append(KnowledgePrerequisite(
            concept=p.concept,
            parent_skill_gap=p.parent_skill_gap,
            is_foundational=p.is_foundational,
        ))

    return prerequisites


# ---------------------------------------------------------------------------
# Phase 2 — student level reasoning (LLM call, batched)
# ---------------------------------------------------------------------------

class _GapReasoning(BaseModel):
    req_summary: str
    reasoning: str


class _ReasoningResult(BaseModel):
    gaps: List[_GapReasoning]


_REASONING_SYSTEM = """\
You are a career skills analyst. For each student skill gap you are given:
- The requirement being assessed
- The student's proficiency level (0=claim only, 1=coursework, 2=project, 3=experience) and Bayesian-combined confidence
- The resulting student_level and gap_type classification
- Each evidence item the student submitted for this requirement, with the LLM's reason for its individual confidence score

Write a concise 2–3 sentence reasoning explaining WHY the student_level is what it is for this requirement.
Reference the actual evidence — what it shows, what is missing or weak. Do not restate the numbers. Explain what the evidence reveals about the student's real capability."""


def generate_student_level_reasoning(
    gap_items: List[GapItem],
    evidence_items: List[EvidenceItem],
    role_title: str,
) -> Dict[str, str]:
    """
    Batched LLM call: for each gap item with evidence, synthesise a human-readable
    reasoning string explaining why the student_level is what it is.

    Uses confidence_reason strings from EvidenceItems as context signals alongside
    proficiency, gap_type, and student_level. Returns dict of req_summary -> reasoning.
    """
    item_by_id: Dict[str, EvidenceItem] = {item.id: item for item in evidence_items if item.id}

    qualifying = [g for g in gap_items if g.evidence_item_ids or g.gap_type != "no_evidence"]
    if not qualifying:
        return {}

    gap_blocks: List[str] = []
    for g in qualifying:
        matching = [item_by_id[i] for i in g.evidence_item_ids if i in item_by_id]
        evidence_lines = "\n".join(
            f"  - [{item.item_type}] {item.summary}"
            + (f": {item.confidence_reason}" if item.confidence_reason else "")
            for item in matching
        ) or "  (no evidence items)"
        gap_blocks.append(
            f"Requirement: {g.summary}\n"
            f"Proficiency: {g.proficiency} | Confidence: {g.confidence} | "
            f"Student level: {g.student_level} | Gap type: {g.gap_type}\n"
            f"Evidence:\n{evidence_lines}"
        )

    prompt = f"Role: {role_title}\n\n" + "\n---\n".join(gap_blocks)

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    llm_struct = llm.with_structured_output(_ReasoningResult, method="json_schema", strict=True)
    result: _ReasoningResult = llm_struct.invoke(
        [{"role": "system", "content": _REASONING_SYSTEM}, {"role": "user", "content": prompt}]
    )
    return {r.req_summary: r.reasoning for r in result.gaps}


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
