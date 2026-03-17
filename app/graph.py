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


def snapshot(repo: SupabaseRepo, state: AgentState,
             step: str, contains_free_text: bool = False) -> None:
    """
    Persist a compact snapshot. Keep it structured and small.
    """
    repo.append_run_state(
        session_id=state.session_id,
        run_id=state.run_id,
        step=step,
        state_json=AgentState.model_validate(state).model_dump(exclude_none=True),
        contains_free_text=contains_free_text,
    )


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

        # Ideal termination: plan passes all rubric thresholds
        if s.critique and s.critique.satisfactory:
            return "explanation"

        # Convergence stall: same issues as the previous iteration — more loops won't help
        stalled = (
            s.critique_iterations > 1
            and s.critique is not None
            and set(s.prev_critique_issues) == set(s.critique.issues)
        )

        # Cap (3 iterations) or stall → fall back to best plan and finish
        if stalled or s.critique_iterations >= 3:
            return "finalise"

        # Still within budget and making progress → replan
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
