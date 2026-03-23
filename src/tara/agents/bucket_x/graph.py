"""Bucket X agent graph — firm recovery for 31-90 DPD accounts.

Similar to NPA but WITHOUT settlement/installment nodes.
Uses confirm_full_payment instead (full amount only).
"""

from __future__ import annotations

from typing import Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from tara.agents.bucket_x.nodes import confirm_full_payment
from tara.agents.bucket_x.prompts import build_bucket_x_prompt
from tara.nodes.central_intelligence import make_central_intelligence
from tara.nodes.end_call import end_call
from tara.nodes.escalate import escalate
from tara.nodes.handle_objection import handle_objection
from tara.nodes.identify_borrower import identify_borrower
from tara.nodes.load_context import load_context
from tara.nodes.state_purpose import state_purpose
from tara.state.schema import TaraState

# Bucket X CI node wired to the firm recovery prompt
bucket_x_central_intelligence = make_central_intelligence(build_bucket_x_prompt)

ACTION_NODES = {
    "identify_borrower",
    "state_purpose",
    "handle_objection",
    "confirm_full_payment",
    "escalate",
}


def route_from_ci(
    state: TaraState,
) -> Literal[
    "identify_borrower",
    "state_purpose",
    "handle_objection",
    "confirm_full_payment",
    "escalate",
    "end_call",
]:
    """Routing function for Bucket X graph."""
    decision = state.get("routing_decision", {})
    next_node = decision.get("next_node", "escalate")

    # Terminal conditions
    if next_node in ("end_agreement", "end_refusal", "end_callback"):
        return "end_call"

    # Guard: force escalation if too many turns
    if state.get("turn_count", 0) > 30:
        return "escalate"

    # Map NPA node names to Bucket X equivalents
    if next_node in ("validate_commitment", "present_options"):
        return "confirm_full_payment"

    if next_node in ACTION_NODES:
        return next_node

    return "escalate"


def build_bucket_x_graph() -> StateGraph:
    """Construct the Bucket X firm recovery graph."""
    builder = StateGraph(TaraState)

    # Nodes
    builder.add_node("load_context", load_context)
    builder.add_node("central_intelligence", bucket_x_central_intelligence)
    builder.add_node("identify_borrower", identify_borrower)
    builder.add_node("state_purpose", state_purpose)
    builder.add_node("handle_objection", handle_objection)
    builder.add_node("confirm_full_payment", confirm_full_payment)
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
            "confirm_full_payment": "confirm_full_payment",
            "escalate": "escalate",
            "end_call": "end_call",
        },
    )

    # All action nodes → END
    for action_node in [
        "identify_borrower",
        "state_purpose",
        "handle_objection",
        "confirm_full_payment",
        "escalate",
        "end_call",
    ]:
        builder.add_edge(action_node, END)

    memory = MemorySaver()
    return builder.compile(checkpointer=memory)
