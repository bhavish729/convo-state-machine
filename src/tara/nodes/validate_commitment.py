from __future__ import annotations

from tara.state.schema import ConversationPhase

# Minimum acceptable settlement percentages by risk tier.
# Below this floor, the amount is rejected and negotiation continues.
_MIN_SETTLEMENT_PCT: dict[str, float] = {
    "low": 0.50,     # Low risk: push for at least 50% recovery
    "medium": 0.30,  # Medium risk: at least 30%
    "high": 0.20,    # High risk (NPA 180+ DPD): at least 20%
}

_DEFAULT_MIN_PCT = 0.25  # Fallback: 25% of debt


def validate_commitment(state: dict) -> dict:
    """Validate and record the borrower's commitment to a payment plan.

    Three paths:
    1. Borrower chose a pre-built option (option_id match) → always accept (options are pre-approved)
    2. Borrower committed an amount above the settlement floor → lock it, end call
    3. Borrower offered too little (below floor) → reject, stay in negotiation for counter-offer
    """
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    chosen_option_id = extracted.get("chosen_option_id")

    profile = state.get("borrower_profile", {})
    debt = profile.get("debt_amount", 0)
    risk_tier = profile.get("risk_tier", "medium")

    negotiation = dict(state.get("negotiation", {}))
    offers = negotiation.get("offers_presented", [])

    # Path 1: Match against pre-built payment options (always accepted — they're pre-approved)
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

    # Path 2 & 3: Partial/settlement amount offered
    partial = extracted.get("partial_amount")
    if partial:
        try:
            amount = float(partial)
        except (ValueError, TypeError):
            return {"conversation_phase": ConversationPhase.COMMITMENT}

        min_pct = _MIN_SETTLEMENT_PCT.get(risk_tier, _DEFAULT_MIN_PCT)
        min_amount = debt * min_pct

        if amount >= min_amount:
            # Path 2: Above floor → accept and lock
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

        # Path 3: Below floor → reject, track the low offer, stay in negotiation
        return {
            "conversation_phase": ConversationPhase.NEGOTIATION,
            "call_progress": {
                "partial_amount_committed": amount,
                "remaining_amount": max(0, debt - amount),
            },
            "tactical_memory": {"partial_amount_offered": amount},
        }

    # No commitment yet — stay in commitment phase
    return {
        "conversation_phase": ConversationPhase.COMMITMENT,
    }
