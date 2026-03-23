"""Agent factory — maps delinquency stage to graph builder.

Each agent has its own graph, nodes, and prompt. Auto-select from DPD
or manual override via agent_type parameter.
"""

from __future__ import annotations

from tara.agents.bucket_x.graph import build_bucket_x_graph
from tara.agents.npa.graph import build_npa_graph
from tara.agents.pre_due.graph import build_pre_due_graph

AGENT_BUILDERS = {
    "pre_due": build_pre_due_graph,
    "bucket_x": build_bucket_x_graph,
    "npa": build_npa_graph,
}

VALID_AGENT_TYPES = set(AGENT_BUILDERS.keys())


def resolve_agent_type(days_past_due: int) -> str:
    """Auto-select agent type from borrower's DPD."""
    if days_past_due <= 30:
        return "pre_due"
    elif days_past_due <= 90:
        return "bucket_x"
    return "npa"


def build_graph(agent_type: str = "npa"):
    """Build and compile the graph for the specified agent type."""
    if agent_type not in AGENT_BUILDERS:
        raise ValueError(
            f"Unknown agent_type '{agent_type}'. "
            f"Valid options: {', '.join(VALID_AGENT_TYPES)}"
        )
    return AGENT_BUILDERS[agent_type]()
