NEGOTIATION_HISTORY_DB: dict[str, list[dict]] = {
    "BRW-001": [
        {
            "date": "2025-12-10",
            "outcome": "no_answer",
            "notes": "Call went unanswered. Left voicemail.",
        },
        {
            "date": "2026-01-05",
            "outcome": "callback_requested",
            "notes": "Borrower picked up, said it was not a good time. Requested callback.",
        },
    ],
    "BRW-002": [
        {
            "date": "2025-10-15",
            "outcome": "refused",
            "notes": "Borrower disputed the debt. Claimed already paid to original creditor.",
            "offers_made": ["OPT-SETTLE", "OPT-EMI-6"],
        },
        {
            "date": "2025-11-20",
            "outcome": "partial_agreement",
            "notes": "Borrower showed interest in installment plan but did not commit.",
            "offers_made": ["OPT-EMI-12", "OPT-HARDSHIP"],
        },
        {
            "date": "2026-01-10",
            "outcome": "no_answer",
            "notes": "Call went unanswered.",
        },
    ],
    "BRW-003": [],
}
