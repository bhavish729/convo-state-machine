from __future__ import annotations

import uuid

from tara.data.mock_borrowers import BORROWER_DB
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
        "is_terminal": False,
        "escalation_reason": "",
    }
