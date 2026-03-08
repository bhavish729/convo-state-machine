from langchain_core.tools import tool

from tara.data.mock_payments import generate_payment_options


@tool
def calculate_payment_options(
    debt_amount: float,
    risk_tier: str,
    days_past_due: int,
) -> list[dict]:
    """Generate available payment/settlement options based on debt amount,
    borrower risk tier, and days past due. Returns a list of options
    including full settlement, installment plans, and hardship programs."""
    return generate_payment_options(debt_amount, risk_tier, days_past_due)
