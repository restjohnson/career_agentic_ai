from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from app.state import (
    AgentState,
    CareerPlan,
    CritiqueReport,
    GapReport,
    PlanPhase,
    StudentConstraints,
)

# ---------------------------------------------------------------------------
# Rubric thresholds — conjunctive satisficing (Simon, 1955)
# No dimension's score can compensate for another's failure.
# ---------------------------------------------------------------------------

_THRESHOLDS: Dict[str, int] = {
    "gap_coverage":          3,
    "prerequisite_ordering": 4,   # high bar — KST compliance
    "feasibility":           3,
    "level_appropriateness": 3,
    "internship_readiness":  4,   # high bar — structural gate
}

# ---------------------------------------------------------------------------
# Dimension 1: Gap coverage
# Are all gaps from the report addressed by at least one phase?
# ---------------------------------------------------------------------------

def _check_gap_coverage(
    plan: CareerPlan,
    gap_report: GapReport,
) -> Tuple[int, List[str], List[str]]:
    addressed: Set[str] = {
        g.lower().strip()
        for phase in plan.phases
        for g in phase.addresses_gaps
    }
    all_gaps: Set[str] = {g.summary.lower().strip() for g in gap_report.gaps}
    missing = all_gaps - addressed

    if not missing:
        return 5, [], []

    issues = [f"Gap not addressed by any phase: '{g}'" for g in missing]
    fixes  = [f"Extend an existing phase or add a new phase to cover: '{g}'" for g in missing]
    score  = max(1, round(5 * (1 - len(missing) / len(all_gaps))))
    return score, issues, fixes


# ---------------------------------------------------------------------------
# Dimension 2: Prerequisite ordering
# Foundational prerequisites must appear in an earlier phase than their parent gap.
# ---------------------------------------------------------------------------

def _check_prereq_ordering(
    plan: CareerPlan,
    gap_report: GapReport,
) -> Tuple[int, List[str], List[str]]:
    # Map normalised gap label → phase index (0-based)
    phase_index: Dict[str, int] = {
        g.lower().strip(): i
        for i, phase in enumerate(plan.phases)
        for g in phase.addresses_gaps
    }

    violations: List[Tuple[str, str, int, int]] = []

    for gap in gap_report.gaps:
        parent_idx = phase_index.get(gap.summary.lower().strip())
        if parent_idx is None:
            continue  # gap_coverage handles missing gaps

        for prereq in gap.knowledge_prerequisites:
            if not prereq.is_foundational or prereq.final_confidence >= 0.5:
                continue  # student likely has it; skip ordering check

            prereq_idx = phase_index.get(prereq.concept.lower().strip())

            if prereq_idx is None:
                if prereq.final_confidence < 0.3:
                    # If the parent gap is already in Phase 1 (index 0), the prerequisite
                    # is implicitly covered there — it cannot be front-loaded any further.
                    # Only flag if the parent gap is in a later phase where an explicit
                    # earlier phase could have addressed the prerequisite.
                    if parent_idx > 0:
                        violations.append((prereq.concept, gap.summary, -1, parent_idx))
            elif prereq_idx >= parent_idx:
                violations.append((prereq.concept, gap.summary, prereq_idx, parent_idx))

    if not violations:
        return 5, [], []

    issues: List[str] = []
    fixes:  List[str] = []
    for prereq, parent, pi, parent_i in violations:
        if pi == -1:
            issues.append(
                f"Foundational prerequisite '{prereq}' for '{parent}' "
                f"is not addressed anywhere in the plan."
            )
            fixes.append(
                f"Add resources for '{prereq}' in a phase before the phase that covers '{parent}'."
            )
        else:
            issues.append(
                f"Prerequisite '{prereq}' (Phase {pi + 1}) must precede "
                f"its parent gap '{parent}' (Phase {parent_i + 1})."
            )
            fixes.append(
                f"Move '{prereq}' resources to a phase earlier than Phase {parent_i + 1}."
            )

    n_absent   = sum(1 for v in violations if v[2] == -1)
    n_ordering = len(violations) - n_absent
    score = max(1, 5 - n_absent * 2 - n_ordering)
    return score, issues, fixes


# ---------------------------------------------------------------------------
# Dimension 3: Feasibility
# Does the plan's total hour demand fit within the student's timeline?
# ---------------------------------------------------------------------------

def _check_feasibility(
    plan: CareerPlan,
    constraints: StudentConstraints,
) -> Tuple[int, List[str], List[str]]:
    total_hours = sum(
        r.estimated_hours
        for phase in plan.phases
        for r in phase.resources
        if r.estimated_hours is not None and r.resource_type != "internship"
    )

    if total_hours == 0:
        return 3, ["Resource hour estimates are missing; feasibility cannot be fully assessed."], []

    required_weeks   = total_hours / constraints.hours_per_week
    delta            = required_weeks - constraints.target_weeks
    overshoot_pct    = delta / constraints.target_weeks if constraints.target_weeks > 0 else 0

    if delta <= 0:
        return 5, [], []

    issues = [
        f"Plan requires ~{round(required_weeks)}w but target is {constraints.target_weeks}w "
        f"({round(overshoot_pct * 100)}% over budget — ~{round(delta)}w excess)."
    ]
    fixes: List[str] = []
    if plan.phases:
        last = plan.phases[-1]
        fixes.append(
            f"Consider deferring Phase {len(plan.phases)} ('{last.title}') "
            f"to reduce timeline by ~{last.weeks}w."
        )

    if overshoot_pct <= 0.10:
        score = 3
    elif overshoot_pct <= 0.25:
        score = 2
    else:
        score = 1

    return score, issues, fixes


# ---------------------------------------------------------------------------
# Dimension 4: Level appropriateness
# Resources must suit the student's academic level; internships not in Phase 1–2.
# ---------------------------------------------------------------------------

def _check_level_appropriateness(
    plan: CareerPlan,
    constraints: StudentConstraints,
) -> Tuple[int, List[str], List[str]]:
    issues: List[str] = []
    fixes:  List[str] = []
    level = constraints.academic_level

    # Early undergrads need conceptual resources in Phase 1
    if level in ("freshman", "sophomore") and plan.phases:
        phase1_rtypes = {r.resource_type for r in plan.phases[0].resources}
        if not phase1_rtypes & {"tutorial", "online_course", "documentation"}:
            issues.append(
                "Phase 1 has no tutorial, course, or documentation resources — "
                "required for an early-stage undergraduate to build conceptual grounding."
            )
            fixes.append(
                "Add at least one tutorial or online_course resource to Phase 1."
            )

    score = max(1, 5 - len(issues))
    return score, issues, fixes


# ---------------------------------------------------------------------------
# Dimension 5: Internship readiness
# Three structural checks: evidence gate, resume update, level-tier alignment.
# ---------------------------------------------------------------------------

def _projected_proficiency(
    gap_summary: str,
    phases_before: List[PlanPhase],
    base_proficiency: int,
) -> int:
    """Estimate proficiency after completing prior phases: +1 per project resource."""
    project_count = sum(
        1
        for phase in phases_before
        for r in phase.resources
        if r.resource_type == "project"
        and r.addresses_gap.lower().strip() == gap_summary.lower().strip()
    )
    return min(4, base_proficiency + project_count)


def _tier_aligned(level: str, projected_proficiency: int) -> bool:
    """True if the internship difficulty tier is within the student's ZPD."""
    if level in ("freshman", "sophomore"):
        return projected_proficiency >= 1
    if level in ("junior", "senior"):
        return projected_proficiency >= 2
    if level == "grad":
        return True
    if level in ("bootcamp", "self_taught"):
        return projected_proficiency >= 2
    return False


def _check_internship_readiness(
    plan: CareerPlan,
    gap_report: GapReport,
    constraints: StudentConstraints,
) -> Tuple[int, List[str], List[str]]:
    issues: List[str] = []
    fixes:  List[str] = []

    base_proficiency: Dict[str, int] = {
        g.summary.lower().strip(): g.proficiency for g in gap_report.gaps
    }

    internship_found = False

    for i, phase in enumerate(plan.phases):
        for resource in phase.resources:
            if resource.resource_type != "internship":
                continue
            internship_found = True
            gap_key          = resource.addresses_gap.lower().strip()
            phases_before    = plan.phases[:i]

            # Check 1 — Evidence gate: prior project or tutorial for this gap
            prior_practice = any(
                r.resource_type in ("project", "tutorial")
                and r.addresses_gap.lower().strip() == gap_key
                for pb in phases_before
                for r in pb.resources
            )
            if not prior_practice:
                issues.append(
                    f"Internship '{resource.title}' (Phase {i + 1}) has no prior project or tutorial "
                    f"for '{resource.addresses_gap}'. Student has no demonstrated evidence to present."
                )
                fixes.append(
                    f"Add a project or tutorial resource for '{resource.addresses_gap}' "
                    f"in a phase before Phase {i + 1}."
                )
                # Hard violation — return immediately with score 1
                return 1, issues, fixes

            # Check 2 — Resume update declared in the immediately preceding phase
            if i > 0:
                preceding = plan.phases[i - 1]
                declared  = any(
                    gap_key in ru.lower() or resource.addresses_gap.lower() in ru.lower()
                    for ru in preceding.resume_updates
                )
                if not preceding.resume_updates or not declared:
                    issues.append(
                        f"Phase {i} ('{preceding.title}') has no resume_updates for "
                        f"'{resource.addresses_gap}' before the internship in Phase {i + 1}."
                    )
                    fixes.append(
                        f"Add resume_updates to Phase {i} specifying that the student should add "
                        f"'{resource.addresses_gap}' skills/projects to their resume before applying."
                    )

            # Check 3 — Level-tier alignment (ZPD)
            base  = base_proficiency.get(gap_key, 0)
            proj  = _projected_proficiency(resource.addresses_gap, phases_before, base)
            level = constraints.academic_level

            if not _tier_aligned(level, proj):
                issues.append(
                    f"Internship '{resource.title}' may exceed the ZPD for a {level} student "
                    f"with projected proficiency {proj}/4 in '{resource.addresses_gap}'."
                )
                fixes.append(
                    f"Add more project resources for '{resource.addresses_gap}' before this internship, "
                    f"or replace with an entry-level/accommodating opportunity."
                )

    if not internship_found:
        return 5, [], []

    if not issues:
        return 5, [], []

    score = max(1, 5 - len(issues) * 2)
    return score, issues, fixes


# ---------------------------------------------------------------------------
# Main critique node
# ---------------------------------------------------------------------------

def critique_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Critique:
    1. Capture previous critique issues at the start (for stall detection by the router).
    2. Run all five rubric dimensions independently.
    3. Apply conjunctive satisficing: all dimensions must meet their threshold.
    4. Track best_plan across iterations (best mean rubric score).
    5. Increment critique_iterations.
    """
    s = AgentState.model_validate(state)
    s.step = "critique"

    if not s.plan or not s.student_constraints or not s.gap_report:
        s.errors.append("critique: plan, student_constraints, or gap_report missing.")
        return s.model_dump(exclude_none=True)

    # Capture previous issues BEFORE overwriting (router uses prev vs current for stall detection)
    s.prev_critique_issues = list(s.critique.issues) if s.critique else []

    rubric_scores: Dict[str, int] = {}
    issues: List[str] = []
    fixes:  List[str] = []

    for dim_fn, dim_key in [
        (_check_gap_coverage,          "gap_coverage"),
        (_check_prereq_ordering,       "prerequisite_ordering"),
        (_check_feasibility,           "feasibility"),
        (_check_level_appropriateness, "level_appropriateness"),
        (_check_internship_readiness,  "internship_readiness"),
    ]:
        if dim_key == "internship_readiness":
            score, dim_issues, dim_fixes = dim_fn(s.plan, s.gap_report, s.student_constraints)
        elif dim_key in ("feasibility", "level_appropriateness"):
            score, dim_issues, dim_fixes = dim_fn(s.plan, s.student_constraints)
        else:
            score, dim_issues, dim_fixes = dim_fn(s.plan, s.gap_report)

        rubric_scores[dim_key] = score
        issues.extend(dim_issues)
        fixes.extend(dim_fixes)

    # Conjunctive satisficing — every dimension must meet its threshold
    satisfactory = all(
        rubric_scores.get(k, 0) >= v for k, v in _THRESHOLDS.items()
    )

    s.critique = CritiqueReport(
        rubric_scores=rubric_scores,
        issues=issues,
        fixes=fixes,
        satisfactory=satisfactory,
    )

    # Best-plan tracking — retain the plan with the highest mean rubric score
    mean_score = sum(rubric_scores.values()) / len(rubric_scores)
    if mean_score > s.best_critique_score:
        s.best_plan          = s.plan
        s.best_critique_score = mean_score

    s.critique_iterations += 1

    return s.model_dump(exclude_none=True)
