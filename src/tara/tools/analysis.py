from langchain_core.tools import tool


@tool
def detect_objection_type(borrower_message: str) -> dict:
    """Classify the borrower's objection into a category. Returns the
    objection type and confidence score."""
    message_lower = borrower_message.lower()

    if any(w in message_lower for w in ["not mine", "don't owe", "dispute", "wrong"]):
        return {"type": "disputes_debt", "confidence": 0.8}
    if any(w in message_lower for w in ["can't afford", "no money", "broke", "unemployed"]):
        return {"type": "cannot_afford", "confidence": 0.8}
    if any(w in message_lower for w in ["already paid", "paid off"]):
        return {"type": "already_paid", "confidence": 0.85}
    if any(w in message_lower for w in ["call back", "later", "not a good time"]):
        return {"type": "requests_callback", "confidence": 0.7}

    return {"type": "none", "confidence": 0.5}


@tool
def assess_sentiment(borrower_message: str) -> dict:
    """Analyze the sentiment of a borrower's message. Returns a sentiment
    label and a numeric score from -1.0 to 1.0."""
    message_lower = borrower_message.lower()

    if any(w in message_lower for w in ["scam", "sue", "lawyer", "harass", "fraud"]):
        return {"sentiment": "very_negative", "score": -0.9}
    if any(w in message_lower for w in ["unfair", "ridiculous", "refuse", "never", "stop"]):
        return {"sentiment": "negative", "score": -0.5}
    if any(w in message_lower for w in ["ok", "fine", "understand", "sure", "agree", "yes"]):
        return {"sentiment": "cooperative", "score": 0.7}
    if any(w in message_lower for w in ["thank", "appreciate", "help"]):
        return {"sentiment": "positive", "score": 0.5}

    return {"sentiment": "neutral", "score": 0.0}
