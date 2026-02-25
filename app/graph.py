from __future__ import annotations
from langgraph.graph import StateGraph, END
from app.state import AgentState
from app.tools.supabase_repo import SupabaseRepo
from app.nodes.role_intake import role_intake_node
from app.nodes.evidence_ingestion import evidence_ingestion_node

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

    def explanation(state: AgentState) -> AgentState:
        state.step = "explanation"
        snapshot(repo, state, "explanation")
        state.status = "done"
        return state

    g.add_node("role_intake", role_intake)
    g.add_node("evidence_ingestion", evidence_ingestion)
    g.add_node("explanation", explanation)

    g.set_entry_point("role_intake")
    g.add_edge("role_intake", "evidence_ingestion")
    g.add_edge("evidence_ingestion", "explanation")
    g.add_edge("explanation", END)

    return g.compile()
