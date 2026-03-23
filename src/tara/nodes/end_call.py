from __future__ import annotations

import logging

from tara.state.schema import ConversationPhase

logger = logging.getLogger(__name__)


def end_call(state: dict) -> dict:
    """Terminal handler for end_agreement, end_refusal, and end_callback.

    Previously these routes went directly to END with no state tracking.
    Now they set the proper phase, is_terminal, and record the call outcome.
    """
    routing = state.get("routing_decision", {})
    next_node = routing.get("next_node", "end_refusal")
    turn = state.get("turn_count", 0)

    logger.warning(
        f"[END_CALL] TERMINAL at turn {turn}: next_node='{next_node}', "
        f"reasoning='{routing.get('reasoning', '')[:100]}'"
    )

    phase_map = {
        "end_agreement": ConversationPhase.COMPLETED_AGREEMENT,
        "end_refusal": ConversationPhase.COMPLETED_REFUSAL,
        "end_callback": ConversationPhase.COMPLETED_CALLBACK,
    }

    outcome_map = {
        "end_agreement": "payment_committed",
        "end_refusal": "firm_refusal",
        "end_callback": "callback_scheduled",
    }

    return {
        "conversation_phase": phase_map.get(next_node, ConversationPhase.COMPLETED_REFUSAL),
        "is_terminal": True,
        "call_progress": {
            "call_outcome": outcome_map.get(next_node, "unknown"),
        },
    }
