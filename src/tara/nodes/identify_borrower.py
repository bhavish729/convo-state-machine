from __future__ import annotations

from tara.state.schema import ConversationPhase


def identify_borrower(state: dict) -> dict:
    """
    Process identity verification. Handles two scenarios:

    1. First-time verification: Borrower confirms their name → identity_verified = True
    2. Identity reversal: Previously verified borrower claims they're not the person →
       always comply (RBI compliance), revoke verification, switch to third-party protocol.
    """
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    profile = state.get("borrower_profile", {})
    attempts = state.get("verification_attempts", 0) + 1

    # --- Mid-call identity reversal ---
    if state.get("identity_verified") and extracted.get("identity_challenge"):
        # RBI compliance: always accept identity challenge, revoke verification
        claimed = extracted.get("claimed_identity", "unknown")
        return {
            "identity_verified": False,
            "verification_attempts": attempts,
            "conversation_phase": ConversationPhase.IDENTIFICATION,
            "call_progress": {
                "identity_challenged": True,
                "identity_challenge_turn": state.get("turn_count", 0),
                "claimed_identity": claimed,
            },
        }

    # --- First-time verification ---
    verified = False

    # Primary check: LLM explicitly confirmed identity via prompt instruction
    if extracted.get("identity_confirmed") is True:
        verified = True
    # Legacy fallback checks
    elif extracted.get("last_four_ssn") and extracted["last_four_ssn"] == profile.get("last_four_ssn"):
        verified = True
    elif extracted.get("date_of_birth") and extracted["date_of_birth"] == profile.get("date_of_birth"):
        verified = True
    elif (
        extracted.get("full_name")
        and extracted["full_name"].lower() == profile.get("full_name", "").lower()
    ):
        verified = True

    new_phase = (
        ConversationPhase.PURPOSE_STATEMENT
        if verified
        else ConversationPhase.IDENTIFICATION
    )

    return {
        "identity_verified": verified,
        "verification_attempts": attempts,
        "conversation_phase": new_phase,
    }
