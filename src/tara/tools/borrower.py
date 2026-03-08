from langchain_core.tools import tool

from tara.data.mock_borrowers import BORROWER_DB
from tara.data.mock_history import NEGOTIATION_HISTORY_DB


@tool
def get_borrower_profile(borrower_id: str) -> dict:
    """Retrieve the full borrower profile by ID. Returns name, debt amount,
    account details, payment history, and risk tier."""
    profile = BORROWER_DB.get(borrower_id)
    if not profile:
        return {"error": f"No borrower found with ID {borrower_id}"}
    return profile


@tool
def get_negotiation_history(borrower_id: str) -> dict:
    """Retrieve past negotiation attempts for a borrower. Returns dates,
    outcomes, offers made, and reasons for failure."""
    history = NEGOTIATION_HISTORY_DB.get(borrower_id, [])
    return {"borrower_id": borrower_id, "attempts": history}
