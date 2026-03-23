"""Pre-due agent graph — friendly reminder for 0-30 DPD accounts.

Simpler graph than NPA: no present_options, no validate_commitment.
Uses confirm_payment_date instead (full EMI only, no negotiation).
"""

from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from tara.agents.pre_due.nodes import confirm_payment_date
from tara.agents.pre_due.prompts import build_pre_due_prompt
from tara.nodes.central_intelligence import make_central_intelligence
from tara.nodes.end_call import end_call
from tara.nodes.escalate import escalate
from tara.nodes.handle_objection import handle_objection
from tara.nodes.identify_borrower import identify_borrower
from tara.nodes.load_context import load_context
from tara.nodes.state_purpose import state_purpose
from tara.state.schema import TaraState

# Pre-due CI node wired to the warm reminder prompt
pre_due_central_intelligence = make_central_intelligence(build_pre_due_prompt)

ACTION_NODES = {
    "identify_borrower",
    "state_purpose",
    "handle_objection",
    "confirm_payment_date",
    "escalate",
}


def route_from_ci(
    state: TaraState,
) -> Literal[
    "identify_borrower",
    "state_purpose",
    "handle_objection",
    "confirm_payment_date",
    "escalate",
    "end_call",
]:
    """Routing function for pre-due graph."""
    decision = state.get("routing_decision", {})
    next_node = decision.get("next_node", "escalate")

    # Terminal conditions
    if next_node in ("end_agreement", "end_refusal", "end_callback"):
        return "end_call"

    # Guard: force end after 20 turns (pre-due has shorter patience)
    if state.get("turn_count", 0) > 20:
        return "escalate"

    # Map NPA node names to pre-due equivalents
    # If LLM tries to route to validate_commitment or present_options,
    # redirect to confirm_payment_date
    if next_node in ("validate_commitment", "present_options"):
        return "confirm_payment_date"

    if next_node in ACTION_NODES:
        return next_node

    return "escalate"


def build_pre_due_graph() -> StateGraph:
    """Construct the pre-due friendly reminder graph."""
    builder = StateGraph(TaraState)

    # Nodes
    builder.add_node("load_context", load_context)
    builder.add_node("central_intelligence", pre_due_central_intelligence)
    builder.add_node("identify_borrower", identify_borrower)
    builder.add_node("state_purpose", state_purpose)
    builder.add_node("handle_objection", handle_objection)
    builder.add_node("confirm_payment_date", confirm_payment_date)
    builder.add_node("escalate", escalate)
    builder.add_node("end_call", end_call)

    # Entry
    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "central_intelligence")

    # Conditional routing from CI
    builder.add_conditional_edges(
        "central_intelligence",
        route_from_ci,
        {
            "identify_borrower": "identify_borrower",
            "state_purpose": "state_purpose",
            "handle_objection": "handle_objection",
            "confirm_payment_date": "confirm_payment_date",
            "escalate": "escalate",
            "end_call": "end_call",
        },
    )

    # All action nodes → END
    for action_node in [
        "identify_borrower",
        "state_purpose",
        "handle_objection",
        "confirm_payment_date",
        "escalate",
        "end_call",
    ]:
        builder.add_edge(action_node, END)

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)
