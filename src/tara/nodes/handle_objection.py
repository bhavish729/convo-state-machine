from __future__ import annotations

from tara.state.schema import ConversationPhase


def handle_objection(state: dict) -> dict:
    """Process the current objection. Log it, track the excuse, detect loops."""
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    objection_type = extracted.get("objection_type", "unknown")

    updates: dict = {
        "conversation_phase": ConversationPhase.OBJECTION_HANDLING,
        "current_objection": objection_type,
        "objections_raised": [objection_type],  # appended via operator.add reducer
    }

    # Track the borrower's excuse in tactical memory
    excuse = extracted.get("borrower_excuse", objection_type)
    tactical: dict = {}
    if excuse and excuse != "unknown":
        tactical["borrower_excuses"] = [excuse]

    # Track callback attempts
    if objection_type in ("call_later", "requests_callback"):
        tactical["callback_attempts"] = (
            state.get("tactical_memory", {}).get("callback_attempts", 0) + 1
        )

    if tactical:
        updates["tactical_memory"] = tactical

    # --- Objection loop detection (deterministic) ---
    progress = state.get("call_progress", {})
    last_objection = progress.get("last_objection", "")

    if objection_type == last_objection and objection_type != "unknown":
        loop_count = progress.get("objection_loop_count", 0) + 1
    else:
        loop_count = 1

    updates["call_progress"] = {
        "last_objection": objection_type,
        "objection_loop_count": loop_count,
    }

    return updates
