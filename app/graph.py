from __future__ import annotations
from langgraph.graph import StateGraph, END
from app.state import AgentState
from app.tools.supabase_repo import SupabaseRepo

def snapshot(repo: SupabaseRepo, state: AgentState, 
             step: str, contains_free_text: bool = False) -> None:
    """
    Persist a compact snapshot. Keep it strcutured and small
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

    #current placeholder
    def role_intake(state: AgentState) -> AgentState:
        state.step = "role_intake"
        snapshot(repo, state, "role_intake")
        return state
    
    def evidence_ingestion(state: AgentState) -> AgentState:
        state.step = "evidence_ingestion"
        snapshot(repo, state, "evidence_ingestion", contains_free_text=bool(
            state.raw_user_text
        ))
        return state
    
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
