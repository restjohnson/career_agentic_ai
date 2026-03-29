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

def snapshot(repo: SupabaseRepo, state: AgentState,
             step: str, contains_free_text: bool = False) -> None:
    """
    Persist a compact snapshot. Keep it structured and small.
    Skipping Supabase persistence due to connection issues.
    """
    # TODO: Re-enable Supabase snapshots once connection issues are resolved
    # try:
    #     repo.append_run_state(...)
    # except Exception as e:
    #     print(f"[SNAPSHOT WARNING] Failed to save state for step '{step}': {type(e).__name__}: {e}")

    if state.run_id:
        publish(state.run_id, {"type": "step", "step": step, "status": "done"})


def build_graph(repo: SupabaseRepo):
    g = StateGraph(AgentState)

    def role_intake(state: dict) -> dict:
        out = role_intake_node(state)
        s = AgentState.model_validate(out)
        snapshot(repo, s, "role_intake")
        return out

    def evidence_ingestion(state: dict) -> dict:
        out = evidence_ingestion_node(state)
        s = AgentState.model_validate(out)
        snapshot(repo, s, "evidence_ingestion", contains_free_text=bool(
            s.raw_user_text or s.evidence_documents
        ))
        return out

    def gap_analysis(state: dict) -> dict:
        out = gap_analysis_node(state)
        s = AgentState.model_validate(out)
        snapshot(repo, s, "gap_analysis")
        return out

    def pathway_planning(state: dict) -> dict:
        out = pathway_planning_node(state, repo)
        s = AgentState.model_validate(out)
        snapshot(repo, s, "pathway_planning")
        return out

    def critique(state: dict) -> dict:
        out = critique_node(state)
        s = AgentState.model_validate(out)
        snapshot(repo, s, "critique")
        return out

    def finalise(state: dict) -> dict:
        """
        Termination cleanup: fall back to best_plan when the loop ends without
        a satisfactory critique (cap hit or convergence stall).
        """
        s = AgentState.model_validate(state)
        if s.best_plan and not (s.critique and s.critique.satisfactory):
            s.plan = s.best_plan

        # Verify plan exists before moving to explanation
        if s.plan:
            print(f"[FINALISE] Plan confirmed: {len(s.plan.phases)} phases, {s.plan.timeline_weeks} weeks", flush=True)
        else:
            print(f"[FINALISE] WARNING: No plan found in state!", flush=True)

        snapshot(repo, s, "pathway_planning")
        return s.model_dump(exclude_none=True)

    def explanation(state: dict) -> dict:
        s = AgentState.model_validate(state)
        s.step = "explanation"
        s.status = "done"
        snapshot(repo, s, "explanation")
        return s.model_dump(exclude_none=True)

    # ---------------------------------------------------------------------------
    # Routing after critique
    # Implements the Self-Refine protocol with a 3-iteration cap (Madaan et al., 2023)
    # and convergence stall detection (Shinn et al., 2023).
    # ---------------------------------------------------------------------------

    def route_after_critique(state: dict) -> str:
        s = AgentState.model_validate(state)
        iters = s.critique_iterations

        print(f"[ROUTING] After iteration #{iters}: satisfactory={s.critique.satisfactory if s.critique else False}", flush=True)

        # FIRST: Hard stop at 3 iterations
        if iters >= 3:
            print(f"[ROUTING] STOP: Max 3 iterations reached", flush=True)
            return "finalise"

        # Check if satisfactory
        if s.critique and s.critique.satisfactory:
            print(f"[ROUTING] STOP: Plan is satisfactory", flush=True)
            return "explanation"

        # Check for convergence stall
        if iters > 0 and s.prev_critique_issues and s.critique:
            if set(s.prev_critique_issues) == set(s.critique.issues):
                print(f"[ROUTING] STOP: Convergence stall (same issues)", flush=True)
                return "finalise"

        # Continue looping
        print(f"[ROUTING] CONTINUE: Loop back to pathway_planning", flush=True)
        return "pathway_planning"

    # ---------------------------------------------------------------------------
    # Graph construction
    # ---------------------------------------------------------------------------

    g.add_node("role_intake",       role_intake)
    g.add_node("evidence_ingestion", evidence_ingestion)
    g.add_node("gap_analysis",      gap_analysis)
    g.add_node("pathway_planning",  pathway_planning)
    g.add_node("critique",          critique)
    g.add_node("finalise",          finalise)
    g.add_node("explanation",       explanation)

    g.set_entry_point("role_intake")
    g.add_edge("role_intake",        "evidence_ingestion")
    g.add_edge("evidence_ingestion", "gap_analysis")
    g.add_edge("gap_analysis",       "pathway_planning")
    g.add_edge("pathway_planning",   "critique")
    g.add_edge("finalise",           "explanation")
    g.add_edge("explanation",        END)

    g.add_conditional_edges(
        "critique",
        route_after_critique,
        {
            "pathway_planning": "pathway_planning",
            "finalise":         "finalise",
            "explanation":      "explanation",
        },
    )

    return g.compile(checkpointer=MemorySaver())


'''if __name__ == "__main__":
    import os, pathlib

    class _MockRepo:
        def append_run_state(self, **_): pass

    png_bytes = build_graph(_MockRepo())
    out = pathlib.Path("graph.png")
    out.write_bytes(png_bytes)
    print(f"Graph saved → {out.resolve()}")
    os.startfile(out) '''
