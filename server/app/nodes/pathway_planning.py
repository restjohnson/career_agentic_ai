from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.state import AgentState, GapItem, LearningResource, StudentConstraints
from app.tools.resource_retrieval import (
    determine_resource_types,
    retrieve_resources_for_gap,
)
from app.tools.pathway_llm import assemble_plan, synthesise_phases, synthesise_internship_opportunities
from app.tools.supabase_repo import SupabaseRepo


# ---------------------------------------------------------------------------
# Step 1: Convert actionable gaps to the ordered dict format
# ---------------------------------------------------------------------------

def _ordered_gaps(gaps: List[GapItem]) -> List[Dict[str, Any]]:
    """
    Convert actionable GapItems to the ordered dict format expected by
    resource retrieval and phase synthesis. Ordered by weighted_gap
    descending (already sorted by gap_analysis).
    """
    return [
        {
            "summary":      gap.summary,
            "label":        gap.summary,
            "gap_type":     gap.gap_type,
            "proficiency":  gap.proficiency,
            "weighted_gap": gap.weighted_gap,
        }
        for gap in gaps
    ]


# ---------------------------------------------------------------------------
# Step 2: Retrieve resources for every item in the ordered list
# ---------------------------------------------------------------------------

def _retrieve_all_resources(
    ordered_items: List[Dict[str, Any]],
    constraints: StudentConstraints,
    repo: SupabaseRepo,
) -> Dict[str, List[LearningResource]]:
    """
    For each ordered item, determine appropriate resource types and retrieve them.
    Returns a dict keyed by item label -> list of LearningResource.
    """
    resources_by_gap: Dict[str, List[LearningResource]] = {}

    for item in ordered_items:
        label       = item["label"]
        proficiency = item.get("proficiency", 0)

        # Build a minimal GapItem proxy for the helper
        gap_proxy = GapItem(
            summary=label,
            category="skill",
            required_level=4.0,
            student_level=0.0,
            raw_gap=4.0,
            weighted_gap=item.get("weighted_gap", 4.0),
            proficiency=proficiency,
            confidence=0.0,
            gap_type=item.get("gap_type", "no_evidence"),
        )
        rtypes = determine_resource_types(gap_proxy, constraints)

        resources_by_gap[label] = retrieve_resources_for_gap(
            gap_summary=label,
            proficiency=proficiency,
            resource_types=rtypes,
            constraints=constraints,
            repo=repo,
        )

    return resources_by_gap


# ---------------------------------------------------------------------------
# Main node
# ---------------------------------------------------------------------------

def pathway_planning_node(state: Dict[str, Any], repo: SupabaseRepo) -> Dict[str, Any]:
    """
    Pathway planning:
    1. Convert actionable gaps to ordered item list.
    2. Retrieve resources per item (Tavily + Supabase cache).
    3. LLM synthesises phases; on replanning, critique fixes are injected.
    4. Assemble and store CareerPlan.
    """
    s = AgentState.model_validate(state)
    s.step = "pathway_planning"

    if not s.gap_report:
        s.errors.append("pathway_planning: gap_report missing.")
        return s.model_dump(exclude_none=True)

    if not s.student_constraints:
        s.errors.append("pathway_planning: student_constraints missing.")
        return s.model_dump(exclude_none=True)

    # Step 1 — exclude met requirements; they need no plan
    actionable_gaps = [g for g in s.gap_report.gaps if g.gap_type != "met"]
    ordered_items   = _ordered_gaps(actionable_gaps)

    # Step 2 — resource retrieval
    try:
        resources_by_gap = _retrieve_all_resources(ordered_items, s.student_constraints, repo)
    except Exception as e:
        s.errors.append(f"pathway_planning: resource retrieval failed: {type(e).__name__}: {e}")
        resources_by_gap = {}

    # Step 3 — LLM phase synthesis
    # Pass critique only on replanning iterations so fixes are incorporated
    active_critique = s.critique if s.critique_iterations > 0 else None
    try:
        plan_spec = synthesise_phases(
            ordered_items=ordered_items,
            resources_by_gap=resources_by_gap,
            constraints=s.student_constraints,
            role_spec=s.role_spec,
            student_model=s.student_model,
            evidence_items=s.evidence_items,
            critique=active_critique,
        )
    except Exception as e:
        s.errors.append(f"pathway_planning: phase synthesis failed: {type(e).__name__}: {e}")
        return s.model_dump(exclude_none=True)

    # Step 3b — assemble plan temporarily to generate internship recommendations
    temp_plan = assemble_plan(plan_spec, resources_by_gap)

    # Step 3c — synthesise internship opportunity recommendations
    try:
        internship_specs = synthesise_internship_opportunities(
            ordered_items=ordered_items,
            plan=temp_plan,
            constraints=s.student_constraints,
            gap_report=s.gap_report,
            student_model=s.student_model,
            evidence_items=s.evidence_items,
        )
    except Exception as e:
        s.errors.append(f"pathway_planning: internship synthesis failed: {type(e).__name__}: {e}")
        internship_specs = {}

    # Step 4 — assemble final plan with internship recommendations
    s.plan = assemble_plan(plan_spec, resources_by_gap, internship_specs)
    print(f"[PATHWAY_PLANNING] Plan created: {len(s.plan.phases)} phases, {s.plan.timeline_weeks} weeks total", flush=True)
    if s.plan.phases:
        print(f"[PATHWAY_PLANNING] Phase 0: {s.plan.phases[0].title} ({s.plan.phases[0].weeks} weeks, {len(s.plan.phases[0].learning_actions)} actions)", flush=True)

    # Step 5 — normalise addresses_gap values to canonical gap summary strings
    # The LLM may paraphrase labels or use prerequisite concept labels.
    # We map back to the exact gap summaries that the critique node compares against.
    gap_labels_lower = {g.summary.lower().strip(): g.summary for g in s.gap_report.gaps}

    def _canonical(label: str) -> str:
        norm = label.lower().strip()
        if norm in gap_labels_lower:
            return gap_labels_lower[norm]
        # Substring fallback
        for key, canonical in gap_labels_lower.items():
            if norm in key or key in norm:
                return canonical
        return label  # unchanged if no match found

    for phase in s.plan.phases:
        for action in phase.learning_actions:
            # Canonicalize each gap in the addresses_gaps list
            action.addresses_gaps = [_canonical(g) for g in action.addresses_gaps]
            # Set resource.addresses_gap to the first canonical gap for resource matching
            if action.addresses_gaps:
                for r in action.example_resources:
                    r.addresses_gap = action.addresses_gaps[0]
        # Re-derive addresses_gaps and phase.resources from normalised actions
        phase.addresses_gaps = list(dict.fromkeys(
            g for a in phase.learning_actions for g in a.addresses_gaps
        ))
        seen: set = set()
        phase.resources = []
        for action in phase.learning_actions:
            for r in action.example_resources:
                key = (r.title, r.resource_type)
                if key not in seen:
                    seen.add(key)
                    phase.resources.append(r)

    return s.model_dump(exclude_none=True)
