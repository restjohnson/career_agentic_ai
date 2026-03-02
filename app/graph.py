from __future__ import annotations
from langgraph.graph import StateGraph, END
from langgraph.types import interrupt
from langgraph.checkpoint.memory import MemorySaver
from app.state import AgentState
from app.tools.supabase_repo import SupabaseRepo
from app.nodes.role_intake import role_intake_node
from app.nodes.evidence_ingestion import evidence_ingestion_node
from app.nodes.gap_analysis_phase1 import gap_analysis_phase1_node
from app.nodes.gap_analysis_phase2 import gap_analysis_phase2_node

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

    def gap_analysis_phase1(state: dict) -> dict:
        out = gap_analysis_phase1_node(state)
        s = AgentState.model_validate(out)
        snapshot(repo, s, "gap_analysis_phase1")
        return out

    def knowledge_self_assessment(state: dict) -> dict:
        """
        Interrupt node: pauses the graph and surfaces knowledge_needing_assessment
        to the student. Resumes once user_knowledge_inputs is populated via API.
        """
        s = AgentState.model_validate(state)
        if s.knowledge_needing_assessment:
            interrupt({
                "type": "knowledge_self_assessment",
                "concepts": s.knowledge_needing_assessment,
            })
        return state

    def gap_analysis_phase2(state: dict) -> dict:
        out = gap_analysis_phase2_node(state)
        s = AgentState.model_validate(out)
        snapshot(repo, s, "gap_analysis_phase2")
        return out

    def explanation(state: AgentState) -> AgentState:
        state.step = "explanation"
        snapshot(repo, state, "explanation")
        state.status = "done"
        return state

    g.add_node("role_intake", role_intake)
    g.add_node("evidence_ingestion", evidence_ingestion)
    g.add_node("gap_analysis_phase1", gap_analysis_phase1)
    g.add_node("knowledge_self_assessment", knowledge_self_assessment)
    g.add_node("gap_analysis_phase2", gap_analysis_phase2)
    g.add_node("explanation", explanation)

    g.set_entry_point("role_intake")
    g.add_edge("role_intake", "evidence_ingestion")
    g.add_edge("evidence_ingestion", "gap_analysis_phase1")

    # conditional edge: bypass interrupt if no concepts need self-assessment
    g.add_conditional_edges(
        "gap_analysis_phase1",
        lambda state: (
            "knowledge_self_assessment"
            if AgentState.model_validate(state).knowledge_needing_assessment
            else "gap_analysis_phase2"
        ),
        {
            "knowledge_self_assessment": "knowledge_self_assessment",
            "gap_analysis_phase2": "gap_analysis_phase2",
        },
    )

    g.add_edge("knowledge_self_assessment", "gap_analysis_phase2")
    g.add_edge("gap_analysis_phase2", "explanation")
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
