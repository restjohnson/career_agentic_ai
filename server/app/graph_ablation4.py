from __future__ import annotations

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.state import AgentState
from app.tools.supabase_repo import SupabaseRepo
from app.nodes.role_intake import role_intake_node
from app.nodes.evidence_ingestion import evidence_ingestion_node
from app.nodes.gap_analysis import gap_analysis_node
from app.nodes.pathway_planning import pathway_planning_node
from app.nodes.critique import critique_node
from app.run_events import publish


def _snapshot(repo: SupabaseRepo, state: AgentState, step: str) -> None:
    if state.run_id:
        publish(state.run_id, {"type": "step", "step": step, "status": "done"})


def build_ablation4_graph(repo: SupabaseRepo):
    """
    Ablation 4: removes the Reflexion critique loop.

    Full COMPASS runs pathway_planning → critique → (replan up to 3x) with:
      - _reflect() narrative feedback explaining why the plan failed
      - prev_plan episodic memory of the prior plan structure
      - route_after_critique deciding whether to replan or terminate

    This ablation keeps everything identical except route_after_critique always
    terminates to finalise after the first critique run. Critique still executes
    once so rubric scores are available for comparison. No replanning occurs,
    so narrative_feedback and prev_plan are never consumed by the planner.
    """
    g = StateGraph(AgentState)

    def role_intake(state: dict) -> dict:
        out = role_intake_node(state)
        s = AgentState.model_validate(out)
        _snapshot(repo, s, "role_intake")
        return out

    def evidence_ingestion(state: dict) -> dict:
        out = evidence_ingestion_node(state)
        s = AgentState.model_validate(out)
        _snapshot(repo, s, "evidence_ingestion")
        return out

    def gap_analysis(state: dict) -> dict:
        out = gap_analysis_node(state)
        s = AgentState.model_validate(out)
        _snapshot(repo, s, "gap_analysis")
        return out

    def pathway_planning(state: dict) -> dict:
        out = pathway_planning_node(state, repo)
        s = AgentState.model_validate(out)
        _snapshot(repo, s, "pathway_planning")
        return out

    def critique(state: dict) -> dict:
        out = critique_node(state)
        s = AgentState.model_validate(out)
        _snapshot(repo, s, "critique")
        return out

    def finalise(state: dict) -> dict:
        s = AgentState.model_validate(state)
        # Only one plan exists in ablation4, but kept for structural parity
        if s.best_plan and not (s.critique and s.critique.satisfactory):
            s.plan = s.best_plan
        if s.plan:
            print(f"[ABLATION4][FINALISE] Plan: {len(s.plan.phases)} phases, {s.plan.timeline_weeks}w", flush=True)
        else:
            print("[ABLATION4][FINALISE] WARNING: No plan in state", flush=True)
        _snapshot(repo, s, "pathway_planning")
        return s.model_dump(exclude_none=True)

    def explanation(state: dict) -> dict:
        s = AgentState.model_validate(state)
        s.step = "explanation"
        s.status = "done"
        _snapshot(repo, s, "explanation")
        return s.model_dump(exclude_none=True)

    def route_after_critique_ablation4(state: dict) -> str:
        """
        Single-pass termination: always route to finalise regardless of score.
        Critique ran once for measurement only — its result never triggers replanning.
        """
        s = AgentState.model_validate(state)
        print(
            f"[ABLATION4][ROUTING] critique_iterations={s.critique_iterations} "
            f"satisfactory={s.critique.satisfactory if s.critique else False} "
            f"→ forcing finalise (no loop)",
            flush=True,
        )
        return "finalise"

    g.add_node("role_intake",        role_intake)
    g.add_node("evidence_ingestion", evidence_ingestion)
    g.add_node("gap_analysis",       gap_analysis)
    g.add_node("pathway_planning",   pathway_planning)
    g.add_node("critique",           critique)
    g.add_node("finalise",           finalise)
    g.add_node("explanation",        explanation)

    g.set_entry_point("role_intake")
    g.add_edge("role_intake",        "evidence_ingestion")
    g.add_edge("evidence_ingestion", "gap_analysis")
    g.add_edge("gap_analysis",       "pathway_planning")
    g.add_edge("pathway_planning",   "critique")
    g.add_edge("finalise",           "explanation")
    g.add_edge("explanation",        END)

    g.add_conditional_edges(
        "critique",
        route_after_critique_ablation4,
        {"finalise": "finalise"},
    )

    return g.compile(checkpointer=MemorySaver())
