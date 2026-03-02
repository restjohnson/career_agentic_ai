from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

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
    """Apply the proficiency rubric to a collection of evidence items."""
    n_professional = sum(1 for i in items if i.proficiency_score == 4)
    n_experience   = sum(1 for i in items if i.item_type == "experience")
    n_projects     = sum(
        1 for i in items if i.item_type == "project" and (i.proficiency_score or 0) >= 2
    )
    n_coursework   = sum(
        1 for i in items
        if (i.item_type in ("coursework", "skill") and (i.proficiency_score or 0) >= 1)
        or (i.item_type == "project" and (i.proficiency_score or 0) == 1)
    )

    if n_professional >= 1:                    return 4
    if n_experience >= 1 or n_projects >= 2:   return 3
    if n_projects >= 1:                        return 2
    if n_coursework >= 1:                      return 1
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
    a student score.

    Returns a dict keyed by req_summary with:
      proficiency, confidence, student_score, evidence_item_ids
    """
    item_by_id: Dict[str, EvidenceItem] = {
        item.id: item for item in evidence_items if item.id
    }

    scores: Dict[str, Dict[str, Any]] = {}
    for req in role_spec.requirements:
        ids = student_model.evidence_map.get(req.req_summary, [])
        matching = [item_by_id[i] for i in ids if i in item_by_id]

        proficiency = aggregate_proficiency(matching)
        confidence  = aggregate_confidence(matching)
        student_score = round(proficiency * confidence, 4)

        scores[req.req_summary] = {
            "proficiency": proficiency,
            "confidence": confidence,
            "student_score": student_score,
            "evidence_item_ids": ids,
        }

    return scores


def compute_gaps(
    scores: Dict[str, Dict[str, Any]],
    role_spec: RoleSpecModel,
) -> List[GapItem]:
    """
    Compute raw_gap and weighted_gap per requirement. Return only requirements
    where raw_gap > 0, ranked by weighted_gap descending.
    """
    gap_items: List[GapItem] = []

    for req in role_spec.requirements:
        s = scores.get(req.req_summary, {})
        student_score = s.get("student_score", 0.0)
        proficiency   = s.get("proficiency", 0)
        confidence    = s.get("confidence", 0.0)
        ids           = s.get("evidence_item_ids", [])

        raw_gap = max(0.0, round(req.required_level - student_score, 4))
        if raw_gap == 0.0:
            continue

        weighted_gap = round(req.importance * raw_gap, 4)

        # classify gap_type
        if not ids:
            gap_type = "missing"
        elif student_score < 0.5:
            gap_type = "not_evidenced"
        elif req.optional and raw_gap < 0.5:
            gap_type = "irrelevant"
        else:
            gap_type = "weak"

        gap_items.append(GapItem(
            summary=req.req_summary,
            category=req.category,
            required_level=req.required_level,
            student_score=student_score,
            raw_gap=raw_gap,
            weighted_gap=weighted_gap,
            proficiency=proficiency,
            confidence=confidence,
            gap_type=gap_type,
            evidence_item_ids=ids,
        ))

    gap_items.sort(key=lambda g: g.weighted_gap, reverse=True)
    return gap_items


# ---------------------------------------------------------------------------
# Phase 1 — knowledge decomposition (LLM call)
# ---------------------------------------------------------------------------

class _KnowledgePrereqRaw(BaseModel):
    concept: str
    parent_skill_gap: str
    is_foundational: bool
    inferred_confidence: float = Field(ge=0.0, le=1.0)
    inference_tier: str   # "direct" | "skill_implied" | "degree_baseline" | "none"
    inference_basis: List[str] = Field(default_factory=list)


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
2. is_foundational = true if the concept is a hard prerequisite (the skill cannot be learned without it).
   is_foundational = false if it is supporting or deepening knowledge.
3. inferred_confidence (0.0–1.0): how confident are you that the student already understands this concept,
   based solely on the evidence provided?
   - 0.8–1.0: Directly evidenced (explicit mention of course, cert, or clear demonstration)
   - 0.5–0.79: Strongly implied by a project or experience that requires this knowledge
   - 0.2–0.49: Weakly implied — could be a degree baseline or tangential mention
   - 0.0–0.19: No evidence basis — concept is not supported by any submitted evidence
4. inference_tier:
   - "direct": explicitly mentioned in evidence (course name, certification, explicit statement)
   - "skill_implied": inferred from a demonstrated skill or project that requires this knowledge
   - "degree_baseline": only basis is the student's degree title suggesting exposure
   - "none": no evidence basis at all
5. inference_basis: list the exact evidence item summaries (from the provided list) that support your inference.
   Empty list if inference_tier is "none".
6. Deduplicate: if the same concept underpins multiple skill gaps, produce it once under the most relevant parent.
7. Limit to at most 4 prerequisites per skill gap. Focus on the most impactful ones.
"""


def decompose_knowledge_prerequisites(
    gap_items: List[GapItem],
    evidence_items: List[EvidenceItem],
    role_title: str,
    top_n: int = 8,
    self_assessment_threshold: float = 0.5,
    max_self_assessment: int = 6,
) -> List[KnowledgePrerequisite]:
    """
    For the top-N gaps by weighted_gap, call the LLM to decompose each into
    knowledge prerequisites. Returns deduplicated KnowledgePrerequisite list
    with needs_self_assessment flagged.
    """
    qualifying = [g for g in gap_items if g.raw_gap > 0.5 and g.gap_type != "irrelevant"]
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

    # flag for self-assessment
    needs_assessment = [
        p for p in deduped
        if p.is_foundational and p.inferred_confidence <= self_assessment_threshold
    ]
    # cap at max_self_assessment, sorted by parent weighted_gap descending
    needs_assessment.sort(key=lambda p: gap_weight.get(p.parent_skill_gap, 0), reverse=True)
    flagged_concepts = {p.concept.lower().strip() for p in needs_assessment[:max_self_assessment]}

    valid_tiers = {"direct", "skill_implied", "degree_baseline", "none"}

    prerequisites: List[KnowledgePrerequisite] = []
    for p in deduped:
        tier = p.inference_tier if p.inference_tier in valid_tiers else "none"
        prerequisites.append(KnowledgePrerequisite(
            concept=p.concept,
            parent_skill_gap=p.parent_skill_gap,
            is_foundational=p.is_foundational,
            inferred_confidence=p.inferred_confidence,
            inference_tier=tier,
            inference_basis=p.inference_basis,
            needs_self_assessment=p.concept.lower().strip() in flagged_concepts,
        ))

    return prerequisites


# ---------------------------------------------------------------------------
# Phase 2 — finalise confidence and derive root cause
# ---------------------------------------------------------------------------

def finalise_knowledge_confidence(
    prerequisites: List[KnowledgePrerequisite],
    user_knowledge_inputs: Dict[str, int],
) -> List[KnowledgePrerequisite]:
    """
    Combine inferred_confidence with student self-assessment (0–3) to produce
    final_confidence per prerequisite.
    """
    for prereq in prerequisites:
        rating = user_knowledge_inputs.get(prereq.concept)
        if rating is not None:
            # evidence-capped: self-assessment can raise confidence, not exceed cap
            self_norm = rating / 3.0
            prereq.final_confidence = round(min(self_norm + 0.2, 1.0), 4)
        else:
            prereq.final_confidence = prereq.inferred_confidence
    return prerequisites


def derive_root_causes(
    gap_items: List[GapItem],
    prerequisites: List[KnowledgePrerequisite],
) -> List[GapItem]:
    """
    Attach knowledge_prerequisites to each GapItem and derive gap_root_cause.
    Rule-based — no LLM call.
    """
    def _norm(s: str) -> str:
        return s.lower().strip().rstrip(".,;:")

    prereqs_by_parent: Dict[str, List[KnowledgePrerequisite]] = {}
    for p in prerequisites:
        prereqs_by_parent.setdefault(_norm(p.parent_skill_gap), []).append(p)

    for gap in gap_items:
        gap_prereqs = prereqs_by_parent.get(_norm(gap.summary), [])
        gap.knowledge_prerequisites = gap_prereqs

        if not gap_prereqs:
            continue

        foundational = [p for p in gap_prereqs if p.is_foundational]
        if not foundational:
            continue

        avg_knowledge = sum(
            (p.final_confidence or p.inferred_confidence) for p in foundational
        ) / len(foundational)

        if gap.student_score < 0.5 and avg_knowledge < 0.4:
            gap.gap_root_cause = "missing_entirely"
        elif gap.student_score < 0.5 and avg_knowledge >= 0.4:
            gap.gap_root_cause = "no_practice"
        elif gap.student_score >= 0.5 and avg_knowledge < 0.4:
            gap.gap_root_cause = "no_theory"
        # else: gap is in depth/level, root_cause stays None

    return gap_items


def build_gap_report(gap_items: List[GapItem]) -> GapReport:
    """Assemble the final GapReport from finalised GapItems."""
    n_critical = sum(1 for g in gap_items if g.gap_root_cause == "missing_entirely")
    n_weak     = sum(1 for g in gap_items if g.gap_type == "weak")
    n_theory   = sum(1 for g in gap_items if g.gap_root_cause == "no_theory")
    n_practice = sum(1 for g in gap_items if g.gap_root_cause == "no_practice")

    parts = [f"{len(gap_items)} gap(s) identified."]
    if n_critical: parts.append(f"{n_critical} missing entirely.")
    if n_weak:     parts.append(f"{n_weak} partially evidenced.")
    if n_theory:   parts.append(f"{n_theory} lacking conceptual grounding.")
    if n_practice: parts.append(f"{n_practice} with knowledge but no demonstrated practice.")

    return GapReport(summary=" ".join(parts), gaps=gap_items)
