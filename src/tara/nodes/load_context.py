from __future__ import annotations

import uuid

from tara.data.mock_borrowers import BORROWER_DB
from tara.data.mock_history import NEGOTIATION_HISTORY_DB
from tara.state.schema import (
    ConversationPhase,
    ObjectionType,
    SentimentLevel,
)


def load_context(state: dict) -> dict:
    """
    First node in the graph. Initializes conversation state with
    borrower data and defaults. Expects borrower_id in borrower_profile
    or falls back to BRW-001.

    On subsequent turns (state already populated via MemorySaver checkpoint),
    skips re-initialization to preserve accumulated state.
    """
    # Guard: if state is already initialized, don't reset it
    if state.get("conversation_phase") is not None:
        return {}

    borrower_id = state.get("borrower_profile", {}).get("borrower_id", "BRW-001")
    profile = BORROWER_DB.get(borrower_id, BORROWER_DB["BRW-001"])

    return {
        "borrower_profile": profile,
        "session_id": state.get("session_id", str(uuid.uuid4())),
        "conversation_phase": ConversationPhase.INIT,
        "turn_count": 0,
        "identity_verified": False,
        "verification_attempts": 0,
        "negotiation": {
            "offers_presented": [],
            "borrower_counter_offers": [],
            "agreed_option": None,
            "rejection_reasons": [],
            "concessions_made": 0,
        },
        "current_sentiment": SentimentLevel.NEUTRAL,
        "sentiment_history": [],
        "current_objection": ObjectionType.NONE,
        "objections_raised": [],
        "tactical_memory": {
            "consequences_used": [],
            "tactics_used": [],
            "borrower_occupation": "unknown",
            "borrower_excuses": [],
            "partial_amount_offered": 0,
            "callback_attempts": 0,
            "promises_broken": 0,
        },
        "negotiation_history": NEGOTIATION_HISTORY_DB.get(borrower_id, []),
        "call_progress": {
            "partial_amount_committed": 0,
            "payment_mode_confirmed": "",
            "payment_locked": False,
            "remaining_amount": profile.get("debt_amount", 0),
            "identity_challenged": False,
            "identity_challenge_turn": 0,
            "claimed_identity": "",
            "objection_loop_count": 0,
            "last_objection": "",
            "unproductive_turns": 0,
            "call_outcome": "",
        },
        "is_terminal": False,
        "escalation_reason": "",
    }
