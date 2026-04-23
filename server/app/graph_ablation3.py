from __future__ import annotations

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from app.state import AgentState
from app.tools.supabase_repo import SupabaseRepo
from app.nodes.critique import critique_node
from app.nodes.single_pass_ablation3 import single_pass_node
from app.run_events import publish


def snapshot(repo: SupabaseRepo, state: AgentState, step: str) -> None:
    """Publish a step snapshot event."""
    if state.run_id:
        publish(state.run_id, {"type": "step", "step": step, "status": "done"})


def build_ablation3_graph(repo: SupabaseRepo):
    """
    Ablation 3 graph: non-agentic single-pass baseline.

    Pipeline:
        single_pass → critique (once, measurement only) → explanation → END

    role_intake, evidence_ingestion, gap_analysis, and pathway_planning
    nodes are all bypassed. The critique node runs once to produce rubric
    scores for comparison against full COMPASS – it does not trigger
    replanning.
    """
    g = StateGraph(AgentState)

    def single_pass(state: dict) -> dict:
        """Run single-pass LLM pathway generation."""
        out = single_pass_node(state)
        s = AgentState.model_validate(out)
        snapshot(repo, s, "pathway_planning")
        return out

    def critique(state: dict) -> dict:
        """Run critique rubric (measurement only, no replanning)."""
        out = critique_node(state)
        s = AgentState.model_validate(out)
        snapshot(repo, s, "critique")
        return out

    def explanation(state: dict) -> dict:
        """Generate explanation (no-op for measurement)."""
        s = AgentState.model_validate(state)
        s.step = "explanation"
        s.status = "done"
        snapshot(repo, s, "explanation")
        return s.model_dump(exclude_none=True)

    def route_after_critique(state: dict) -> str:
        """Critique runs once for measurement – always route to explanation."""
        return "explanation"

    g.add_node("single_pass", single_pass)
    g.add_node("critique",    critique)
    g.add_node("explanation", explanation)

    g.set_entry_point("single_pass")
    g.add_edge("single_pass", "critique")
    g.add_edge("explanation", END)

    g.add_conditional_edges(
        "critique",
        route_after_critique,
        {"explanation": "explanation"},
    )

    return g.compile(checkpointer=MemorySaver())
