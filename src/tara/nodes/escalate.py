from __future__ import annotations

from tara.state.schema import ConversationPhase


def escalate(state: dict) -> dict:
    """Mark the conversation for escalation to a human agent."""
    routing = state.get("routing_decision", {})
    reason = routing.get("reasoning", "Unspecified escalation reason")

    return {
        "conversation_phase": ConversationPhase.ESCALATION,
        "escalation_reason": reason,
        "is_terminal": True,
    }
