# State — TaraState Schema + Enums

## schema.py — Root Graph State

`TaraState` is a `TypedDict` with `total=False` (all fields optional, populated incrementally by nodes).

### Reducer Fields (accumulate across turns)

These fields use LangGraph reducers — returning them from a node **appends** rather than overwrites:

| Field | Reducer | Purpose |
|-------|---------|---------|
| `messages` | `add_messages` | Conversation history (LangGraph's message dedup reducer) |
| `sentiment_history` | `operator.add` | List of sentiment strings per turn (**currently never written to**) |
| `objections_raised` | `operator.add` | List of objection types raised by borrower |

### Overwrite Fields (last write wins)

All other fields overwrite on each update:
- `borrower_profile` — BorrowerProfile dict (set once by `load_context`)
- `conversation_phase` — ConversationPhase enum (updated by every action node)
- `turn_count` — incremented by `central_intelligence`
- `identity_verified` — set by `identify_borrower`
- `routing_decision` — overwritten every turn by `central_intelligence`
- `current_sentiment` — SentimentLevel enum (**initialized to NEUTRAL, never updated — known bug**)
- `is_terminal` — set to True by `escalate` or `validate_commitment` (agreement)

### Enums

- `ConversationPhase`: INIT → IDENTIFICATION → PURPOSE_STATEMENT → NEGOTIATION → OBJECTION_HANDLING → COMMITMENT → ESCALATION → COMPLETED_*
- `SentimentLevel`: VERY_NEGATIVE, NEGATIVE, NEUTRAL, POSITIVE, COOPERATIVE
- `ObjectionType`: DISPUTES_DEBT, CANNOT_AFFORD, WRONG_PERSON, ALREADY_PAID, REQUESTS_CALLBACK, ABUSIVE, NONE

### Sub-structures

- `BorrowerProfile` — borrower details (name, debt_amount, DPD, risk_tier, etc.)
- `PaymentOption` — payment plan (type, total_amount, monthly_payment, num_installments)
- `NegotiationState` — offers_presented, agreed_option, counter_offers, rejection_reasons
- `RoutingDecision` — next_node, reasoning, response_to_borrower, extracted_info

## Important Convention: How Nodes Return State Updates

Nodes return a dict with ONLY the fields they want to update. LangGraph merges this into the accumulated state:

```python
def my_node(state: dict) -> dict:
    return {
        "conversation_phase": ConversationPhase.NEGOTIATION,  # overwrites
        "objections_raised": ["cannot_afford"],  # APPENDED via operator.add
    }
```

For reducer fields (`messages`, `sentiment_history`, `objections_raised`), returning a list **appends** to the existing list, not replaces it.
