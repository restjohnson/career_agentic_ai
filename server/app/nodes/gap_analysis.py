from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from app.state import AgentState, GapReport, KnowledgePrerequisite
from app.tools.gap_analysis_tools import (
    build_gap_report,
    compute_gaps,
    compute_gaps_selfreport,
    compute_student_scores,
    decompose_knowledge_prerequisites,
    generate_student_level_reasoning,
)

# ---------------------------------------------------------------------------
# Agent system prompt
# ---------------------------------------------------------------------------

_AGENT_SYSTEM = """\
You are a career skills gap analyst assessing a student's readiness for the role: {role_title}.

Your goal is to produce a complete GapReport using the tools available. Call them in logical order:

1. compute_student_scores  — always call first; computes proficiency, confidence, and student_level per requirement
2. compute_gaps            — always call after scores; classifies each requirement and computes raw/weighted gaps
3. generate_student_level_reasoning — call when there are actionable gaps (gap_type != "met"); produces human-readable explanations for downstream agents
4. decompose_prerequisites — call when gaps with raw_gap > 0.5 exist; identifies foundational knowledge concepts needed before tackling gaps; skip if all gaps are met
5. build_gap_report        — always call last to finalise the assessment

Make decisions based on what the tools reveal. Do not call tools you do not need.\
"""


# ---------------------------------------------------------------------------
# Helper: attach prerequisites to gap items
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    return s.lower().strip().rstrip(".,;:")


def _attach_prerequisites(
    gap_items: list,
    prerequisites: List[KnowledgePrerequisite],
) -> None:
    gap_by_norm = {_norm(g.summary): g for g in gap_items}
    prereqs_by_parent: Dict[str, list] = {}
    for p in prerequisites:
        canonical_gap = gap_by_norm.get(_norm(p.parent_skill_gap))
        if canonical_gap:
            prereqs_by_parent.setdefault(canonical_gap.summary, []).append(p)
    for gap in gap_items:
        gap.knowledge_prerequisites = prereqs_by_parent.get(gap.summary, [])


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

def gap_analysis_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Gap analysis node — ReAct tool-calling agent.

    The agent decides which tools to call and in what order based on what it
    observes from each tool result. Tools are closure-based: state data is
    captured from AgentState and shared via a mutable `results` dict.

    Tools available:
      compute_student_scores_tool        — always needed
      compute_gaps_tool                  — always needed
      generate_student_level_reasoning_tool — when actionable gaps exist
      decompose_prerequisites_tool       — when raw_gap > 0.5 gaps exist
      build_gap_report_tool              — always last
    """
    s = AgentState.model_validate(state)
    s.step = "gap_analysis"

    print(f"[GAP_ANALYSIS] Starting. evidence_items={len(s.evidence_items or [])}, role_spec={'present' if s.role_spec else 'MISSING'}, student_model={'present' if s.student_model else 'MISSING'}", flush=True)

    if not s.role_spec:
        print("[GAP_ANALYSIS] ERROR: role_spec missing.", flush=True)
        s.errors.append("gap_analysis: role_spec missing from state.")
        return s.model_dump(exclude_none=True)

    if not s.student_model:
        print("[GAP_ANALYSIS] ERROR: student_model missing.", flush=True)
        s.errors.append("gap_analysis: student_model missing from state.")
        return s.model_dump(exclude_none=True)

    # ------------------------------------------------------------------
    # ABLATION 2 fast path — bypass the ReAct agent entirely.
    # student_level estimates come from selfreport_scores (holistic LLM
    # assessment); compute_student_scores is not called.
    # ------------------------------------------------------------------
    if s.condition == "ablation2" and s.selfreport_scores:
        print(f"[GAP_ANALYSIS] Ablation2 path: using holistic scores for {len(s.selfreport_scores)} requirements.", flush=True)

        gap_items = compute_gaps_selfreport(s.selfreport_scores, s.role_spec)
        n_met = sum(1 for g in gap_items if g.gap_type == "met")
        print(f"[GAP_ANALYSIS] compute_gaps_selfreport: {len(gap_items)} total, {n_met} met.", flush=True)

        actionable = [g for g in gap_items if g.gap_type != "met"]

        reasoning_map = generate_student_level_reasoning(gap_items, s.evidence_items, s.role_spec.canonical_role_title)
        for gap in gap_items:
            gap.student_level_reasoning = reasoning_map.get(gap.summary)
        print(f"[GAP_ANALYSIS] generate_student_level_reasoning: {len(reasoning_map)} gaps explained.", flush=True)

        if any(g.raw_gap > 0.5 for g in gap_items):
            prerequisites = decompose_knowledge_prerequisites(
                gap_items=actionable,
                evidence_items=s.evidence_items,
                role_title=s.role_spec.canonical_role_title,
            )
            _attach_prerequisites(gap_items, prerequisites)
            print(f"[GAP_ANALYSIS] decompose_prerequisites: {len(prerequisites)} concepts.", flush=True)

        gap_report = build_gap_report(gap_items)
        print(f"[GAP_ANALYSIS] Done (ablation2). {len(gap_report.gaps)} gaps ({n_met} met).", flush=True)
        s.gap_report = gap_report
        return s.model_dump(exclude_none=True)

    # Shared mutable container for tool results (accessed via closure)
    results: Dict[str, Any] = {
        "scores": None,
        "gap_items": None,
        "gap_report": None,
    }

    # ------------------------------------------------------------------
    # Tool definitions (closures over `s` and `results`)
    # ------------------------------------------------------------------

    @tool
    def compute_student_scores_tool() -> str:
        """Compute proficiency, confidence, and student_level per role requirement from the student's evidence. Always call first."""
        results["scores"] = compute_student_scores(s.evidence_items, s.student_model, s.role_spec)
        print(f"[GAP_ANALYSIS] compute_student_scores: {len(results['scores'])} requirements scored.", flush=True)
        return f"Computed scores for {len(results['scores'])} requirements."

    @tool
    def compute_gaps_tool() -> str:
        """Compute raw_gap, weighted_gap, and gap_type for all requirements. Call after compute_student_scores. Reports how many gaps exist and their types."""
        if results["scores"] is None:
            return "Error: call compute_student_scores_tool first."
        gap_items = compute_gaps(results["scores"], s.role_spec, s.evidence_items)
        results["gap_items"] = gap_items
        n_met = sum(1 for g in gap_items if g.gap_type == "met")
        n_actionable = len(gap_items) - n_met
        gap_summary = ", ".join(
            f"{g.gap_type}({g.summary[:30]})" for g in gap_items[:5]
        )
        print(f"[GAP_ANALYSIS] compute_gaps: {len(gap_items)} total, {n_met} met, {n_actionable} actionable.", flush=True)
        return (
            f"{len(gap_items)} requirements assessed: {n_met} met, {n_actionable} with gaps. "
            f"Sample: {gap_summary}"
        )

    @tool
    def generate_student_level_reasoning_tool() -> str:
        """Generate human-readable reasoning explaining why each student level is what it is, using evidence signals and confidence reasons as context. Call when actionable gaps (gap_type != 'met') exist."""
        if results["gap_items"] is None:
            return "Error: call compute_gaps_tool first."
        reasoning_map = generate_student_level_reasoning(
            results["gap_items"], s.evidence_items, s.role_spec.canonical_role_title
        )
        for gap in results["gap_items"]:
            gap.student_level_reasoning = reasoning_map.get(gap.summary)
        print(f"[GAP_ANALYSIS] generate_student_level_reasoning: {len(reasoning_map)} gaps explained.", flush=True)
        return f"Generated reasoning for {len(reasoning_map)} gaps."

    @tool
    def decompose_prerequisites_tool() -> str:
        """Identify foundational knowledge concepts required before tackling each actionable gap. Call when gaps with raw_gap > 0.5 exist; skip if all gaps are met."""
        if results["gap_items"] is None:
            return "Error: call compute_gaps_tool first."
        actionable = [g for g in results["gap_items"] if g.gap_type != "met"]
        prerequisites = decompose_knowledge_prerequisites(
            gap_items=actionable,
            evidence_items=s.evidence_items,
            role_title=s.role_spec.canonical_role_title,
        )
        _attach_prerequisites(results["gap_items"], prerequisites)
        print(f"[GAP_ANALYSIS] decompose_prerequisites: {len(prerequisites)} prerequisite concepts.", flush=True)
        return f"Decomposed {len(prerequisites)} knowledge prerequisite concepts across {len(actionable)} actionable gaps."

    @tool
    def build_gap_report_tool() -> str:
        """Finalise the gap assessment and produce the GapReport. Always call this last."""
        if results["gap_items"] is None:
            return "Error: call compute_gaps_tool first."
        results["gap_report"] = build_gap_report(results["gap_items"])
        print(f"[GAP_ANALYSIS] build_gap_report: {results['gap_report'].summary}", flush=True)
        return results["gap_report"].summary

    # ------------------------------------------------------------------
    # Run the ReAct agent
    # ------------------------------------------------------------------

    agent = create_react_agent(
        model=ChatOpenAI(model="gpt-4o-mini", temperature=0),
        tools=[
            compute_student_scores_tool,
            compute_gaps_tool,
            generate_student_level_reasoning_tool,
            decompose_prerequisites_tool,
            build_gap_report_tool,
        ],
        prompt=_AGENT_SYSTEM.format(role_title=s.role_spec.canonical_role_title),
    )

    try:
        agent.invoke({"messages": [HumanMessage(content="Run the full gap assessment.")]})
    except Exception as e:
        print(f"[GAP_ANALYSIS] Agent ERROR: {type(e).__name__}: {e}", flush=True)
        s.errors.append(f"gap_analysis agent error: {type(e).__name__}: {e}")

    gap_report = results["gap_report"] or GapReport(summary="No gaps assessed.", gaps=[])
    n_gaps = len(gap_report.gaps)
    n_met = sum(1 for g in gap_report.gaps if g.gap_type == "met")
    print(f"[GAP_ANALYSIS] Done. {n_gaps} gaps in report ({n_met} met, {n_gaps - n_met} actionable).", flush=True)
    s.gap_report = gap_report
    return s.model_dump(exclude_none=True)
