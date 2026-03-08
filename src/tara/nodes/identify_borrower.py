from __future__ import annotations

from tara.state.schema import ConversationPhase


def identify_borrower(state: dict) -> dict:
    """
    Process identity verification. The prompt instructs the LLM to set
    extracted_info.identity_confirmed = true when the borrower confirms
    their name. We also accept legacy checks (full_name, DOB, SSN match)
    for backward compatibility.
    """
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    profile = state.get("borrower_profile", {})
    attempts = state.get("verification_attempts", 0) + 1

    verified = False

    # Primary check: LLM explicitly confirmed identity via prompt instruction
    if extracted.get("identity_confirmed") is True:
        verified = True
    # Legacy fallback checks — only match if the field actually exists in both
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
