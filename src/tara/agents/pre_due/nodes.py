"""Pre-due agent nodes — full EMI payment date confirmation.

Pre-due has ONE unique node: confirm_payment_date.
No settlement, no installments. Full EMI only.
"""

from __future__ import annotations

from tara.state.schema import ConversationPhase


def confirm_payment_date(state: dict) -> dict:
    """Lock exact date + mode for full EMI payment.

    Pre-due only accepts FULL EMI amount. No partial payments.
    The borrower must commit to a specific date and payment mode.
    """
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    profile = state.get("borrower_profile", {})
    debt = profile.get("debt_amount", 0)

    payment_date = extracted.get("callback_date", extracted.get("payment_date", ""))
    payment_mode = extracted.get("payment_mode", "")

    # If borrower confirms full EMI payment with date + mode → lock it
    if payment_date and payment_mode:
        return {
            "conversation_phase": ConversationPhase.COMPLETED_AGREEMENT,
            "is_terminal": True,
            "call_progress": {
                "payment_locked": True,
                "partial_amount_committed": debt,  # Full EMI
                "remaining_amount": 0,
                "payment_mode_confirmed": payment_mode,
                "call_outcome": "payment_committed",
            },
        }

    # If borrower commits to a date but no mode yet → stay in commitment
    if payment_date:
        return {
            "conversation_phase": ConversationPhase.COMMITMENT,
            "call_progress": {
                "partial_amount_committed": debt,
                "remaining_amount": 0,
            },
        }

    # If they offer a partial amount → reject (pre-due = full EMI only)
    partial = extracted.get("partial_amount")
    if partial:
        try:
            amount = float(partial)
            if amount < debt:
                return {
                    "conversation_phase": ConversationPhase.NEGOTIATION,
                    "call_progress": {
                        "partial_amount_committed": amount,
                        "remaining_amount": max(0, debt - amount),
                    },
                    "tactical_memory": {"partial_amount_offered": amount},
                }
        except (ValueError, TypeError):
            pass

    # No commitment yet — stay in commitment phase
    return {
        "conversation_phase": ConversationPhase.COMMITMENT,
    }
