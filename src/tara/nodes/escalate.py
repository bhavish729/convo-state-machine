from __future__ import annotations

import logging

from tara.state.schema import ConversationPhase

logger = logging.getLogger(__name__)


def escalate(state: dict) -> dict:
    """Mark the conversation for escalation to a human agent."""
    routing = state.get("routing_decision", {})
    reason = routing.get("reasoning", "Unspecified escalation reason")
    turn = state.get("turn_count", 0)

    logger.warning(
        f"[ESCALATE] TERMINAL at turn {turn}: reason='{reason}', "
        f"next_node='{routing.get('next_node', '?')}'"
    )

    return {
        "conversation_phase": ConversationPhase.ESCALATION,
        "escalation_reason": reason,
        "is_terminal": True,
    }
