from __future__ import annotations

from tara.data.mock_payments import generate_payment_options
from tara.state.schema import ConversationPhase


def present_options(state: dict) -> dict:
    """Generate and present payment options to the borrower."""
    profile = state.get("borrower_profile", {})
    options = generate_payment_options(
        profile.get("debt_amount", 0),
        profile.get("risk_tier", "medium"),
        profile.get("days_past_due", 90),
    )

    negotiation = dict(state.get("negotiation", {}))
    negotiation["offers_presented"] = options

    return {
        "conversation_phase": ConversationPhase.NEGOTIATION,
        "negotiation": negotiation,
    }
