from __future__ import annotations

import operator
from enum import Enum
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


# ── Enums ──


class ConversationPhase(str, Enum):
    INIT = "init"
    IDENTIFICATION = "identification"
    PURPOSE_STATEMENT = "purpose_statement"
    NEGOTIATION = "negotiation"
    OBJECTION_HANDLING = "objection_handling"
    COMMITMENT = "commitment"
    ESCALATION = "escalation"
    COMPLETED_AGREEMENT = "completed_agreement"
    COMPLETED_REFUSAL = "completed_refusal"
    COMPLETED_CALLBACK = "completed_callback"


class SentimentLevel(str, Enum):
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"
    COOPERATIVE = "cooperative"


class ObjectionType(str, Enum):
    DISPUTES_DEBT = "disputes_debt"
    CANNOT_AFFORD = "cannot_afford"
    WRONG_PERSON = "wrong_person"
    ALREADY_PAID = "already_paid"
    REQUESTS_CALLBACK = "requests_callback"
    ABUSIVE = "abusive"
    NONE = "none"


# ── Sub-structures ──


class BorrowerProfile(TypedDict, total=False):
    borrower_id: str
    full_name: str
    date_of_birth: str
    last_four_ssn: str
    phone: str
    email: str
    address: str
    debt_amount: float
    debt_type: str  # credit_card, personal_loan, medical
    original_creditor: str
    account_number: str
    days_past_due: int
    last_payment_date: str | None
    last_payment_amount: float | None
    risk_tier: str  # low, medium, high


class PaymentOption(TypedDict):
    option_id: str
    description: str
    type: str  # full_payment, full_settlement, installment, hardship
    total_amount: float
    discount_percentage: float
    monthly_payment: float | None
    num_installments: int | None
    due_date: str


class NegotiationState(TypedDict, total=False):
    offers_presented: list[PaymentOption]
    borrower_counter_offers: list[str]
    agreed_option: PaymentOption | None
    rejection_reasons: list[str]
    concessions_made: int


class RoutingDecision(TypedDict):
    next_node: str
    reasoning: str
    response_to_borrower: str
    extracted_info: dict[str, Any]


# ── Root Graph State ──


class TaraState(TypedDict, total=False):
    # Conversation messages — append-reducer via add_messages
    messages: Annotated[list[AnyMessage], add_messages]

    # Borrower context
    borrower_profile: BorrowerProfile

    # Session metadata
    session_id: str
    conversation_phase: ConversationPhase
    turn_count: int

    # Identity verification
    identity_verified: bool
    verification_attempts: int

    # Negotiation tracking
    negotiation: NegotiationState

    # Sentiment
    current_sentiment: SentimentLevel
    sentiment_history: Annotated[list[str], operator.add]

    # Objections
    current_objection: ObjectionType
    objections_raised: Annotated[list[str], operator.add]

    # Routing — set by central_intelligence, read by conditional edge
    routing_decision: RoutingDecision

    # Terminal flag
    is_terminal: bool

    # Escalation
    escalation_reason: str
