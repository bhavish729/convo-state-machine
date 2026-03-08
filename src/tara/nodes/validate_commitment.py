from __future__ import annotations

from tara.state.schema import ConversationPhase


def validate_commitment(state: dict) -> dict:
    """Validate and record the borrower's commitment to a payment plan.

    Two paths:
    1. Borrower chose a pre-built option (option_id match) → lock as agreed_option
    2. Borrower committed a partial amount (no option match) → lock partial, end call
    """
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    chosen_option_id = extracted.get("chosen_option_id")

    negotiation = dict(state.get("negotiation", {}))
    offers = negotiation.get("offers_presented", [])

    # Path 1: Match against pre-built payment options
    agreed = None
    if chosen_option_id:
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
            "call_progress": {
                "payment_locked": True,
                "partial_amount_committed": agreed["total_amount"],
                "remaining_amount": 0,
                "call_outcome": "payment_committed",
            },
        }

    # Path 2: Partial amount committed (not from pre-built options)
    partial = extracted.get("partial_amount")
    if partial:
        try:
            amount = float(partial)
            debt = state.get("borrower_profile", {}).get("debt_amount", 0)
            payment_mode = extracted.get("payment_mode", "")

            return {
                "conversation_phase": ConversationPhase.COMPLETED_AGREEMENT,
                "is_terminal": True,
                "call_progress": {
                    "payment_locked": True,
                    "partial_amount_committed": amount,
                    "remaining_amount": max(0, debt - amount),
                    "payment_mode_confirmed": payment_mode,
                    "call_outcome": "payment_committed",
                },
                "tactical_memory": {"partial_amount_offered": amount},
            }
        except (ValueError, TypeError):
            pass

    # No commitment yet — stay in commitment phase
    return {
        "conversation_phase": ConversationPhase.COMMITMENT,
    }
