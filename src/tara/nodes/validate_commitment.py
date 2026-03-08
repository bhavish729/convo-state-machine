from __future__ import annotations

from tara.state.schema import ConversationPhase


def validate_commitment(state: dict) -> dict:
    """Validate and record the borrower's commitment to a payment plan."""
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    chosen_option_id = extracted.get("chosen_option_id")

    negotiation = dict(state.get("negotiation", {}))
    offers = negotiation.get("offers_presented", [])

    agreed = None
    for opt in offers:
        if opt["option_id"] == chosen_option_id:
            agreed = opt
            break

    if agreed:
        negotiation["agreed_option"] = agreed
        return {
            "negotiation": negotiation,
            "conversation_phase": ConversationPhase.COMPLETED_AGREEMENT,
            "is_terminal": True,
        }

    return {
        "conversation_phase": ConversationPhase.COMMITMENT,
    }
