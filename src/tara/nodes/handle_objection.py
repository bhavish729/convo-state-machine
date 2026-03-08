from __future__ import annotations

from tara.state.schema import ConversationPhase


def handle_objection(state: dict) -> dict:
    """Process the current objection. Log it and update phase."""
    routing = state.get("routing_decision", {})
    objection_type = routing.get("extracted_info", {}).get("objection_type", "unknown")

    return {
        "conversation_phase": ConversationPhase.OBJECTION_HANDLING,
        "current_objection": objection_type,
        "objections_raised": [objection_type],  # appended via operator.add reducer
    }
