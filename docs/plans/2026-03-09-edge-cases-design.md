# Edge Cases Design: Call Awareness, Identity Reversal & Smart Termination

**Date:** 2026-03-09
**Status:** Approved
**Approach:** A + selective B (Prompt-driven with deterministic loop detection)

## Problem Statement

Tara has critical blindspots that prevent effective collections:

1. **Partial payment amnesia** — After a borrower commits to ₹10k partial, Tara asks for the full ₹85k again next turn
2. **Identity reversal unchecked** — Borrower confirms identity, then later claims "it's my wife" — no mechanism to handle this
3. **No call termination intelligence** — `end_agreement/end_refusal/end_callback` hit `END` with no state tracking; LLM has no guidance on when to end
4. **Objection loops undetected** — Same excuse repeated 5x with no circuit breaker
5. **Escapist behavior unrecognized** — LLM can't distinguish genuine inability from evasion tactics

## Root Causes

- `call_progress` doesn't exist — LLM has no visibility into what's been accomplished this call
- `identity_verified` is a one-way boolean — set once, never revoked
- Terminal routes (`end_*`) bypass all nodes — no state recorded on call outcome
- No objection loop counter — `handle_objection` doesn't track repetitions

## Design

### 1. New State: `CallProgress`

```python
class CallProgress(TypedDict, total=False):
    # Payment tracking
    partial_amount_committed: float    # e.g., 10000.0
    payment_mode_confirmed: str        # "upi", "neft", etc.
    payment_locked: bool               # True once borrower confirmed payment
    remaining_amount: float            # debt_amount - partial_amount_committed

    # Identity tracking
    identity_challenged: bool          # True if borrower reverses identity mid-call
    identity_challenge_turn: int       # Which turn they challenged
    claimed_identity: str              # "wife", "husband", "wrong_person", etc.

    # Termination intelligence
    objection_loop_count: int          # How many times same objection repeated
    last_objection: str                # Last objection type for loop detection
    unproductive_turns: int            # Consecutive turns with no progress
    call_outcome: str                  # "payment_committed", "firm_refusal", "callback_scheduled"
```

Custom reducer (scalars overwrite only — no list fields):
```python
def _merge_call_progress(existing, update):
    merged = dict(existing) if existing else {}
    merged.update(update or {})
    return merged
```

Initialized in `load_context` with zeros/defaults.

### 2. Identity Reversal Protocol

**Rule:** Any identity challenge → always comply (RBI compliance). Revoke `identity_verified`, switch to third-party protocol.

In `identify_borrower` node, add reversal logic:
- If `identity_verified = True` AND `extracted_info.identity_challenge = True`:
  - Set `identity_verified = False`
  - Set `conversation_phase = IDENTIFICATION`
  - Update `call_progress` with challenge details
  - LLM sees this in prompt and switches to third-party mode

In prompt, add `== IDENTITY REVERSAL HANDLING ==`:
- If identity was already verified but borrower now challenges → revoke and follow third-party protocol
- Never reveal loan details after identity is challenged

### 3. Call Termination

#### 3a. New `end_call` Node

Replaces the current direct-to-END routing. Handles all three terminal types:
- `end_agreement` → phase=COMPLETED_AGREEMENT, outcome="payment_committed"
- `end_refusal` → phase=COMPLETED_REFUSAL, outcome="firm_refusal"
- `end_callback` → phase=COMPLETED_CALLBACK, outcome="callback_scheduled"

Sets `is_terminal = True` and records outcome in `call_progress`.

Graph change: `end_*` routes → `end_call` node → END (instead of direct END).

#### 3b. Objection Loop Detector (Deterministic)

In `handle_objection`, after existing logic:
- Compare current objection_type to `call_progress.last_objection`
- If same → increment `objection_loop_count`
- If different → reset to 1

Prompt reads loop_count and at 3+: "This borrower is going in circles. Give FINAL WARNING and end."

#### 3c. Prompt-Based Termination Rules

```
== CALL TERMINATION RULES ==
1. Payment committed → end_agreement
2. Firm refusal after 3+ attempts → end_refusal
3. Callback agreed with EXACT time within 24h → end_callback
4. Same objection repeated 3+ times → end_refusal (unproductive loop)
5. Turn count > 30 with no progress → end_refusal
6. Borrower abusive 3+ turns → escalate
7. After locking partial payment → end_agreement (do NOT continue for rest)
```

### 4. Partial Payment Awareness

#### In `central_intelligence`:
Extract `partial_amount` and `payment_mode` from `extracted_info` → write to `call_progress`.

#### In `validate_commitment`:
If no matching `offer_id` but `partial_amount` exists → set `payment_locked = True`, calculate `remaining_amount`.

#### In prompt:
New `== THIS CALL'S PROGRESS ==` section shows:
- Amount committed, payment mode, locked status
- Remaining amount
- Identity challenge status
- Objection loop count

With critical instruction: "You already locked ₹X. Do NOT ask for full amount again. End the call."

## Files Affected

| File | Change |
|------|--------|
| `state/schema.py` | Add `CallProgress` TypedDict + reducer + field in `TaraState` |
| `nodes/load_context.py` | Initialize `call_progress` |
| `nodes/central_intelligence.py` | Extract partial_amount, payment_mode, identity_challenge → write to `call_progress` |
| `nodes/identify_borrower.py` | Add identity reversal logic |
| `nodes/handle_objection.py` | Add objection loop counter |
| `nodes/validate_commitment.py` | Update `call_progress.payment_locked` for partial payments |
| `nodes/end_call.py` | NEW — terminal handler node |
| `graph/builder.py` | Add `end_call` node, route terminal types through it |
| `llm/prompts.py` | Add call progress section, identity reversal rules, termination rules |
| `web/routes.py` | Add `call_progress` to `_serialize_state()` |

## Decision Log

- **Partial payment → end call**: User chose "lock partial, end call" over continuing negotiation
- **Identity reversal → always comply**: User chose RBI-safe approach over skeptical pushback
- **Turn limit: 30**: User specified this threshold
- **Architecture: A + selective B**: Prompt-driven with deterministic objection loop detection
