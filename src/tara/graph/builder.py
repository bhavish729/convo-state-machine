from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from tara.nodes.central_intelligence import central_intelligence
from tara.nodes.end_call import end_call
from tara.nodes.escalate import escalate
from tara.nodes.handle_objection import handle_objection
from tara.nodes.identify_borrower import identify_borrower
from tara.nodes.load_context import load_context
from tara.nodes.present_options import present_options
from tara.nodes.state_purpose import state_purpose
from tara.nodes.validate_commitment import validate_commitment
from tara.state.schema import TaraState

# Valid action node names
ACTION_NODES = {
    "identify_borrower",
    "state_purpose",
    "handle_objection",
    "present_options",
    "validate_commitment",
    "escalate",
}


def route_from_ci(
    state: TaraState,
) -> Literal[
    "identify_borrower",
    "state_purpose",
    "handle_objection",
    "present_options",
    "validate_commitment",
    "escalate",
    "end_call",
]:
    """
    Routing function for conditional edges from central_intelligence.
    Inspects the routing_decision set by the LLM and returns the next node.
    """
    decision = state.get("routing_decision", {})
    next_node = decision.get("next_node", "escalate")

    # Terminal conditions — route through end_call node for state tracking
    if next_node in ("end_agreement", "end_refusal", "end_callback"):
        return "end_call"

    # Guard: force escalation if too many turns
    if state.get("turn_count", 0) > 30:
        return "escalate"

    if next_node in ACTION_NODES:
        return next_node

    # Fallback to escalation for unknown routes
    return "escalate"


def build_graph() -> StateGraph:
    """
    Construct and compile the Tara conversation graph.

    Flow:
        START -> load_context -> central_intelligence
        central_intelligence --(conditional)--> action nodes | END
        each action node -> END  (completes the turn; next user input re-enters via checkpoint)
    """
    builder = StateGraph(TaraState)

    # Add nodes
    builder.add_node("load_context", load_context)
    builder.add_node("central_intelligence", central_intelligence)
    builder.add_node("identify_borrower", identify_borrower)
    builder.add_node("state_purpose", state_purpose)
    builder.add_node("handle_objection", handle_objection)
    builder.add_node("present_options", present_options)
    builder.add_node("validate_commitment", validate_commitment)
    builder.add_node("escalate", escalate)
    builder.add_node("end_call", end_call)

    # Entry edge
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "central_intelligence")

    # Conditional edges from central_intelligence
    builder.add_conditional_edges(
        "central_intelligence",
        route_from_ci,
        {
            "identify_borrower": "identify_borrower",
            "state_purpose": "state_purpose",
            "handle_objection": "handle_objection",
            "present_options": "present_options",
            "validate_commitment": "validate_commitment",
            "escalate": "escalate",
            "end_call": "end_call",
        },
    )

    # Action nodes complete the turn — return to user and wait for next input.
    # CI already generated the response; the action just updates internal state.
    # Next user message will re-enter at central_intelligence via the graph's
    # checkpointed state.
    for action_node in [
        "identify_borrower",
        "state_purpose",
        "handle_objection",
        "present_options",
        "validate_commitment",
        "escalate",
        "end_call",
    ]:
        builder.add_edge(action_node, END)

    # Compile with in-memory checkpointing
    memory = MemorySaver()
    graph = builder.compile(checkpointer=memory)

    return graph
