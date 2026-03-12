from __future__ import annotations

import logging

from tara.state.schema import ConversationPhase

logger = logging.getLogger(__name__)

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
    1. Borrower chose a pre-built option (option_id match) → accept, move to payment confirmation
    2. Borrower committed an amount above the settlement floor → accept, move to payment confirmation
    3. Borrower offered too little (below floor) → reject, stay in negotiation for counter-offer

    NOTE: This node does NOT set is_terminal. After acceptance, the call moves to
    PAYMENT_CONFIRMATION phase where CI confirms the amount with the borrower and
    guides them through the payment process. Only end_call sets is_terminal.
    """
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    progress = state.get("call_progress", {})
    phase = state.get("conversation_phase", "")

    # Path 0: Payment confirmation — borrower explicitly confirmed amount + mode
    # This happens when CI routes back here during PAYMENT_CONFIRMATION phase
    if (
        str(phase) == ConversationPhase.PAYMENT_CONFIRMATION
        and progress.get("payment_committed")
        and extracted.get("payment_confirmed")
    ):
        amount = progress.get("partial_amount_committed", 0)
        payment_mode = extracted.get("payment_mode") or progress.get("payment_mode_confirmed", "")
        logger.warning(
            f"[VALIDATE_COMMITMENT] LOCKED: amount={amount}, mode={payment_mode} "
            f"— borrower explicitly confirmed. Call will end via end_call."
        )
        return {
            "conversation_phase": ConversationPhase.COMPLETED_AGREEMENT,
            "is_terminal": True,
            "call_progress": {
                "payment_locked": True,
                "payment_mode_confirmed": payment_mode,
                "call_outcome": "payment_committed",
            },
        }

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
        logger.info(
            f"[VALIDATE_COMMITMENT] Accepted option '{agreed.get('option_id')}' "
            f"amount={agreed.get('total_amount')} → PAYMENT_CONFIRMATION phase"
        )
        return {
            "negotiation": negotiation,
            "conversation_phase": ConversationPhase.PAYMENT_CONFIRMATION,
            "call_progress": {
                "payment_committed": True,
                "partial_amount_committed": agreed["total_amount"],
                "remaining_amount": 0,
                "call_outcome": "pending_confirmation",
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
            # Path 2: Above floor → accept, move to payment confirmation
            payment_mode = extracted.get("payment_mode", "")
            logger.info(
                f"[VALIDATE_COMMITMENT] Accepted amount={amount} >= floor={min_amount} "
                f"(debt={debt}, risk={risk_tier}, pct={min_pct}) → PAYMENT_CONFIRMATION phase"
            )
            return {
                "conversation_phase": ConversationPhase.PAYMENT_CONFIRMATION,
                "call_progress": {
                    "payment_committed": True,
                    "partial_amount_committed": amount,
                    "remaining_amount": max(0, debt - amount),
                    "payment_mode_confirmed": payment_mode,
                    "call_outcome": "pending_confirmation",
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
