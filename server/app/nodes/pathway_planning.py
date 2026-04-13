from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.state import AgentState, GapItem, LearningResource, StudentConstraints
from app.tools.resource_retrieval import (
    determine_prereq_resource_types,
    determine_resource_types,
    retrieve_resources_for_gap,
)
from app.tools.pathway_llm import assemble_plan, synthesise_phases, synthesise_internship_opportunities
from app.tools.supabase_repo import SupabaseRepo


# ---------------------------------------------------------------------------
# Step 1: Extract foundational prerequisites that need dedicated resources
# ---------------------------------------------------------------------------

def _extract_prereq_items(gaps: List[GapItem]) -> List[Dict[str, Any]]:
    """
    Collect KnowledgePrerequisite items across all gaps where is_foundational=True.
    These need their own learning resources and must precede their parent gap.
    Deduplicated by concept (case-insensitive).
    """
    seen: Dict[str, Dict[str, Any]] = {}
    for gap in gaps:
        for prereq in gap.knowledge_prerequisites:
            if prereq.is_foundational:
                key = prereq.concept.lower().strip()
                if key not in seen:
                    seen[key] = {
                        "summary":    prereq.concept,
                        "label":      prereq.concept,
                        "parent_gap": prereq.parent_skill_gap,
                        "is_prereq":  True,
                        "gap_type":   "no_evidence",
                        "proficiency": 0,
                    }
    return list(seen.values())


# ---------------------------------------------------------------------------
# Step 2: Topological sort — prerequisites precede parent gaps
# ---------------------------------------------------------------------------

def _topological_sort(
    gaps: List[GapItem],
    prereq_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Produce a flat ordered list where each foundational prerequisite is emitted
    immediately before its parent gap.  Gaps without prerequisites are ordered
    purely by weighted_gap descending (the pre-existing sort from gap_analysis).
    """
    prereqs_by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for p in prereq_items:
        prereqs_by_parent.setdefault(p["parent_gap"].lower().strip(), []).append(p)

    ordered: List[Dict[str, Any]] = []
    emitted_prereqs: set = set()

    for gap in gaps:  # already sorted by weighted_gap desc
        parent_key = gap.summary.lower().strip()

        # Emit any unmet foundational prerequisites first
        for p in prereqs_by_parent.get(parent_key, []):
            pkey = p["summary"].lower().strip()
            if pkey not in emitted_prereqs:
                ordered.append(p)
                emitted_prereqs.add(pkey)

        # Emit the gap itself
        ordered.append({
            "summary":      gap.summary,
            "label":        gap.summary,
            "gap_type":     gap.gap_type,
            "proficiency":  gap.proficiency,
            "weighted_gap": gap.weighted_gap,
            "is_prereq":    False,
        })

    return ordered


# ---------------------------------------------------------------------------
# Step 3: Retrieve resources for every item in the ordered list
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
        label      = item["label"]
        is_prereq  = item.get("is_prereq", False)
        proficiency = item.get("proficiency", 0)

        if is_prereq:
            rtypes = determine_prereq_resource_types(constraints)
        else:
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
    1. Extract foundational prerequisite items needing dedicated resources.
    2. Topological sort: prerequisites precede parent gaps.
    3. Retrieve resources per item (Tavily + Supabase cache).
    4. LLM synthesises phases; on replanning, critique fixes are injected.
    5. Assemble and store CareerPlan.
    """
    s = AgentState.model_validate(state)
    s.step = "pathway_planning"

    if not s.gap_report:
        s.errors.append("pathway_planning: gap_report missing.")
        return s.model_dump(exclude_none=True)

    if not s.student_constraints:
        s.errors.append("pathway_planning: student_constraints missing.")
        return s.model_dump(exclude_none=True)

    # Steps 1 & 2 — exclude met requirements; they need no plan
    actionable_gaps = [g for g in s.gap_report.gaps if g.gap_type != "met"]
    prereq_items    = _extract_prereq_items(actionable_gaps)
    ordered_items   = _topological_sort(actionable_gaps, prereq_items)

    # Step 3 — resource retrieval
    try:
        resources_by_gap = _retrieve_all_resources(ordered_items, s.student_constraints, repo)
    except Exception as e:
        s.errors.append(f"pathway_planning: resource retrieval failed: {type(e).__name__}: {e}")
        resources_by_gap = {}

    # Step 4 — LLM phase synthesis
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

    # Step 4b — assemble plan temporarily to generate internship recommendations
    temp_plan = assemble_plan(plan_spec, resources_by_gap)

    # Step 4c — synthesise internship opportunity recommendations
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

    # Step 5 — assemble final plan with internship recommendations
    s.plan = assemble_plan(plan_spec, resources_by_gap, internship_specs)
    print(f"[PATHWAY_PLANNING] Plan created: {len(s.plan.phases)} phases, {s.plan.timeline_weeks} weeks total", flush=True)
    if s.plan.phases:
        print(f"[PATHWAY_PLANNING] Phase 0: {s.plan.phases[0].title} ({s.plan.phases[0].weeks} weeks, {len(s.plan.phases[0].learning_actions)} actions)", flush=True)

    # Step 6 — normalise addresses_gap values to canonical gap summary strings
    # The LLM may paraphrase labels or use prerequisite concept labels.
    # We map back to the exact gap summaries that the critique node compares against.
    gap_labels_lower   = {g.summary.lower().strip(): g.summary for g in s.gap_report.gaps}
    prereq_parent_lower = {p["label"].lower().strip(): p["parent_gap"] for p in prereq_items}

    def _canonical(label: str) -> str:
        norm = label.lower().strip()
        if norm in gap_labels_lower:
            return gap_labels_lower[norm]
        # Prerequisite concept → resolve to parent gap
        if norm in prereq_parent_lower:
            parent_norm = prereq_parent_lower[norm].lower().strip()
            if parent_norm in gap_labels_lower:
                return gap_labels_lower[parent_norm]
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
