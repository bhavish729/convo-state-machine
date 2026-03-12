"""NPA agent graph — settlement negotiation for 91+ DPD accounts.

This is the current production graph refactored into the agents package.
It has the full node set including settlement/installment options.
"""

from __future__ import annotations

import logging
from typing import Literal

logger = logging.getLogger(__name__)

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from tara.agents.npa.prompts import build_npa_prompt
from tara.nodes.central_intelligence import make_central_intelligence
from tara.nodes.end_call import end_call
from tara.nodes.escalate import escalate
from tara.nodes.handle_objection import handle_objection
from tara.nodes.identify_borrower import identify_borrower
from tara.nodes.load_context import load_context
from tara.nodes.present_options import present_options
from tara.nodes.state_purpose import state_purpose
from tara.nodes.validate_commitment import validate_commitment
from tara.state.schema import TaraState

# NPA CI node wired to the NPA settlement prompt
npa_central_intelligence = make_central_intelligence(build_npa_prompt)

# Valid action node names for NPA
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
    """Routing function for conditional edges from central_intelligence."""
    decision = state.get("routing_decision", {})
    next_node = decision.get("next_node", "escalate")
    turn = state.get("turn_count", 0)

    # Terminal conditions — route through end_call node
    if next_node in ("end_agreement", "end_refusal", "end_callback"):
        logger.warning(f"[NPA_ROUTE] Turn {turn}: routing to end_call (next_node='{next_node}')")
        return "end_call"

    # Guard: force escalation if too many turns
    if turn > 30:
        logger.warning(f"[NPA_ROUTE] Turn {turn}: force escalation (turn limit)")
        return "escalate"

    if next_node in ACTION_NODES:
        logger.info(f"[NPA_ROUTE] Turn {turn}: routing to '{next_node}'")
        return next_node

    logger.warning(f"[NPA_ROUTE] Turn {turn}: unknown next_node='{next_node}', defaulting to escalate")
    return "escalate"


def build_npa_graph() -> StateGraph:
    """Construct the NPA settlement negotiation graph."""
    builder = StateGraph(TaraState)

    # Nodes
    builder.add_node("load_context", load_context)
    builder.add_node("central_intelligence", npa_central_intelligence)
    builder.add_node("identify_borrower", identify_borrower)
    builder.add_node("state_purpose", state_purpose)
    builder.add_node("handle_objection", handle_objection)
    builder.add_node("present_options", present_options)
    builder.add_node("validate_commitment", validate_commitment)
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
            "present_options": "present_options",
            "validate_commitment": "validate_commitment",
            "escalate": "escalate",
            "end_call": "end_call",
        },
    )

    # All action nodes → END (turn complete, wait for next user input)
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

    # Compile with checkpointing
    memory = MemorySaver()
    return builder.compile(checkpointer=memory)
