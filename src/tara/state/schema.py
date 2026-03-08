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


class TacticalMemory(TypedDict, total=False):
    """Tracks which consequences/tactics have been used across turns.
    Prevents Tara from repeating the same arguments."""
    consequences_used: list[str]   # ["cibil", "legal", "field_visit", ...]
    tactics_used: list[str]        # ["probe_occupation", "personalize_consequence", ...]
    borrower_occupation: str       # "shop_owner", "salaried", "farmer", etc.
    borrower_excuses: list[str]    # ["salary_nahi_aayi", "kal_karunga", ...]
    partial_amount_offered: float  # Last partial amount borrower mentioned
    callback_attempts: int         # How many times they asked for callback
    promises_broken: int           # How many times they promised but didn't pay


def _merge_tactical_memory(
    existing: TacticalMemory | None,
    update: TacticalMemory | None,
) -> TacticalMemory:
    """Custom reducer for TacticalMemory.

    LangGraph reducers only work at the top level of state, not on nested
    TypedDict fields.  This function knows which fields are lists (append)
    vs scalars (overwrite), so nodes can return partial dicts and they
    accumulate correctly across turns.
    """
    _LIST_FIELDS = frozenset({"consequences_used", "tactics_used", "borrower_excuses"})

    merged: dict = dict(existing) if existing else {}
    for key, value in (update or {}).items():
        if key in _LIST_FIELDS:
            merged[key] = merged.get(key, []) + value  # append lists
        else:
            merged[key] = value  # overwrite scalars
    return merged  # type: ignore[return-value]


class CallProgress(TypedDict, total=False):
    """Tracks what has happened during THIS call.
    Gives the LLM awareness of partial payments, identity challenges, and loops."""
    # Payment tracking
    partial_amount_committed: float    # Amount borrower committed to pay
    payment_mode_confirmed: str        # "upi", "neft", "nach", "cash"
    payment_locked: bool               # True once borrower confirmed payment details
    remaining_amount: float            # debt_amount - partial_amount_committed

    # Identity tracking
    identity_challenged: bool          # True if borrower reverses identity mid-call
    identity_challenge_turn: int       # Which turn they challenged
    claimed_identity: str              # "wife", "husband", "wrong_person", etc.

    # Termination intelligence
    objection_loop_count: int          # How many times same objection repeated consecutively
    last_objection: str                # Last objection type for loop detection
    unproductive_turns: int            # Consecutive turns with no forward progress
    call_outcome: str                  # "payment_committed", "firm_refusal", "callback_scheduled"


def _merge_call_progress(
    existing: CallProgress | None,
    update: CallProgress | None,
) -> CallProgress:
    """Custom reducer for CallProgress. All fields are scalars — just overwrite."""
    merged: dict = dict(existing) if existing else {}
    merged.update(update or {})
    return merged  # type: ignore[return-value]


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

    # Tactical memory — tracks consequences/tactics used across turns
    tactical_memory: Annotated[TacticalMemory, _merge_tactical_memory]

    # Call progress — tracks events within THIS call
    call_progress: Annotated[CallProgress, _merge_call_progress]

    # Previous call history (loaded from JSON, injected into prompt)
    negotiation_history: list[dict]

    # Routing — set by central_intelligence, read by conditional edge
    routing_decision: RoutingDecision

    # Terminal flag
    is_terminal: bool

    # Escalation
    escalation_reason: str
