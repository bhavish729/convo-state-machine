"""Bucket X agent nodes — full amount recovery.

Bucket X has ONE unique node: confirm_full_payment.
No settlement, no installments. Full amount in one shot.
"""

from __future__ import annotations

from tara.state.schema import ConversationPhase


def confirm_full_payment(state: dict) -> dict:
    """Lock full payment commitment.

    Bucket X only accepts FULL outstanding amount. No partial, no settlement.
    If borrower offers partial → reject and push for full.
    """
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    profile = state.get("borrower_profile", {})
    debt = profile.get("debt_amount", 0)

    payment_mode = extracted.get("payment_mode", "")
    partial = extracted.get("partial_amount")

    # Check if they're offering full amount
    if partial:
        try:
            amount = float(partial)
        except (ValueError, TypeError):
            return {"conversation_phase": ConversationPhase.COMMITMENT}

        # Accept ONLY if it's the full amount (within 1% tolerance for rounding)
        if amount >= debt * 0.99:
            if payment_mode:
                return {
                    "conversation_phase": ConversationPhase.COMPLETED_AGREEMENT,
                    "is_terminal": True,
                    "call_progress": {
                        "payment_locked": True,
                        "partial_amount_committed": debt,
                        "remaining_amount": 0,
                        "payment_mode_confirmed": payment_mode,
                        "call_outcome": "payment_committed",
                    },
                }
            # Amount OK but no mode yet
            return {
                "conversation_phase": ConversationPhase.COMMITMENT,
                "call_progress": {
                    "partial_amount_committed": amount,
                    "remaining_amount": max(0, debt - amount),
                },
            }

        # Partial amount offered → reject (Bucket X = full only)
        return {
            "conversation_phase": ConversationPhase.NEGOTIATION,
            "call_progress": {
                "partial_amount_committed": amount,
                "remaining_amount": max(0, debt - amount),
            },
            "tactical_memory": {"partial_amount_offered": amount},
        }

    # Check for chosen option (if somehow options were presented)
    chosen_option_id = extracted.get("chosen_option_id")
    if chosen_option_id and chosen_option_id == "OPT-FULL":
        negotiation = dict(state.get("negotiation", {}))
        for opt in negotiation.get("offers_presented", []):
            if opt["option_id"] == "OPT-FULL":
                negotiation["agreed_option"] = opt
                return {
                    "negotiation": negotiation,
                    "conversation_phase": ConversationPhase.COMPLETED_AGREEMENT,
                    "is_terminal": True,
                    "call_progress": {
                        "payment_locked": True,
                        "partial_amount_committed": debt,
                        "remaining_amount": 0,
                        "call_outcome": "payment_committed",
                    },
                }

    # No commitment yet
    return {
        "conversation_phase": ConversationPhase.COMMITMENT,
    }
