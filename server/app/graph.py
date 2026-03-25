from __future__ import annotations
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from app.state import AgentState
from app.tools.supabase_repo import SupabaseRepo
from app.nodes.role_intake import role_intake_node
from app.nodes.evidence_ingestion import evidence_ingestion_node
from app.nodes.gap_analysis import gap_analysis_node
from app.run_events import publish

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

    def explanation(state: AgentState) -> AgentState:
        state.step = "explanation"
        snapshot(repo, state, "explanation")
        state.status = "done"
        return state

    g.add_node("role_intake", role_intake)
    g.add_node("evidence_ingestion", evidence_ingestion)
    g.add_node("gap_analysis", gap_analysis)
    g.add_node("explanation", explanation)

    g.set_entry_point("role_intake")
    g.add_edge("role_intake", "evidence_ingestion")
    g.add_edge("evidence_ingestion", "gap_analysis")
    g.add_edge("gap_analysis", "explanation")
    g.add_edge("explanation", END)

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
