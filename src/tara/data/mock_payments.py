def generate_payment_options(
    debt_amount: float,
    risk_tier: str,
    days_past_due: int,
) -> list[dict]:
    """Generate payment/settlement options based on borrower parameters."""
    discount_map = {
        "low": {"settlement": 0.10, "hardship": 0.20},
        "medium": {"settlement": 0.20, "hardship": 0.30},
        "high": {"settlement": 0.35, "hardship": 0.45},
    }
    discounts = discount_map.get(risk_tier, discount_map["medium"])

    options = [
        {
            "option_id": "OPT-FULL",
            "description": "Full payment",
            "type": "full_payment",
            "total_amount": debt_amount,
            "discount_percentage": 0,
            "monthly_payment": None,
            "num_installments": None,
            "due_date": "2026-04-15",
        },
        {
            "option_id": "OPT-SETTLE",
            "description": f"One-time settlement ({int(discounts['settlement'] * 100)}% discount)",
            "type": "full_settlement",
            "total_amount": round(debt_amount * (1 - discounts["settlement"]), 2),
            "discount_percentage": discounts["settlement"] * 100,
            "monthly_payment": None,
            "num_installments": None,
            "due_date": "2026-04-15",
        },
        {
            "option_id": "OPT-EMI-6",
            "description": "6-month installment plan",
            "type": "installment",
            "total_amount": debt_amount,
            "discount_percentage": 0,
            "monthly_payment": round(debt_amount / 6, 2),
            "num_installments": 6,
            "due_date": "2026-04-01",
        },
        {
            "option_id": "OPT-EMI-12",
            "description": "12-month installment plan",
            "type": "installment",
            "total_amount": debt_amount,
            "discount_percentage": 0,
            "monthly_payment": round(debt_amount / 12, 2),
            "num_installments": 12,
            "due_date": "2026-04-01",
        },
    ]

    # Hardship option for high-risk or long-overdue
    if risk_tier == "high" or days_past_due > 180:
        options.append(
            {
                "option_id": "OPT-HARDSHIP",
                "description": (
                    f"Hardship program ({int(discounts['hardship'] * 100)}% discount, 18 months)"
                ),
                "type": "hardship",
                "total_amount": round(debt_amount * (1 - discounts["hardship"]), 2),
                "discount_percentage": discounts["hardship"] * 100,
                "monthly_payment": round(
                    debt_amount * (1 - discounts["hardship"]) / 18, 2
                ),
                "num_installments": 18,
                "due_date": "2026-04-01",
            }
        )

    return options
