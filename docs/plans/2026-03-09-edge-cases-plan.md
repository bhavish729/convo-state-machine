# Edge Cases Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Give Tara awareness of what's happened during the call — partial payment tracking, identity reversal handling, intelligent call termination, and objection loop detection.

**Architecture:** Prompt-driven (Approach A) with one deterministic check (selective B). New `CallProgress` state tracks call events. New `end_call` node handles all terminal routes. Objection loop counter in `handle_objection`. Prompt teaches LLM about termination rules and partial payment awareness.

**Tech Stack:** LangGraph, Python TypedDict, custom reducer

**Design Doc:** `docs/plans/2026-03-09-edge-cases-design.md`

---

### Task 1: Add CallProgress to state schema

**Files:**
- Modify: `src/tara/state/schema.py`

**Step 1: Add CallProgress TypedDict and reducer**

After the `TacticalMemory` class and `_merge_tactical_memory` function (line ~123), add:

```python
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
```

**Step 2: Add call_progress field to TaraState**

In `TaraState`, after the `tactical_memory` field (line ~157), add:

```python
    # Call progress — tracks events within THIS call
    call_progress: Annotated[CallProgress, _merge_call_progress]
```

**Step 3: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "from tara.state.schema import TaraState, CallProgress, _merge_call_progress; print('Schema OK')"`

Expected: `Schema OK`

---

### Task 2: Initialize call_progress in load_context

**Files:**
- Modify: `src/tara/nodes/load_context.py`

**Step 1: Add call_progress initialization**

In the return dict of `load_context()`, after the `"negotiation_history"` line (line ~57), add:

```python
        "call_progress": {
            "partial_amount_committed": 0,
            "payment_mode_confirmed": "",
            "payment_locked": False,
            "remaining_amount": profile.get("debt_amount", 0),
            "identity_challenged": False,
            "identity_challenge_turn": 0,
            "claimed_identity": "",
            "objection_loop_count": 0,
            "last_objection": "",
            "unproductive_turns": 0,
            "call_outcome": "",
        },
```

Note: `remaining_amount` is initialized to the full `debt_amount` from the borrower profile.

**Step 2: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "from tara.nodes.load_context import load_context; r = load_context({'borrower_profile': {'borrower_id': 'BRW-001'}}); print('remaining_amount:', r['call_progress']['remaining_amount']); print('Load OK')"`

Expected: `remaining_amount: 85000.0` (or whatever BRW-001's debt is), `Load OK`

---

### Task 3: Create end_call terminal node

**Files:**
- Create: `src/tara/nodes/end_call.py`

**Step 1: Create the node**

```python
from __future__ import annotations

from tara.state.schema import ConversationPhase


def end_call(state: dict) -> dict:
    """Terminal handler for end_agreement, end_refusal, and end_callback.

    Previously these routes went directly to END with no state tracking.
    Now they set the proper phase, is_terminal, and record the call outcome.
    """
    routing = state.get("routing_decision", {})
    next_node = routing.get("next_node", "end_refusal")

    phase_map = {
        "end_agreement": ConversationPhase.COMPLETED_AGREEMENT,
        "end_refusal": ConversationPhase.COMPLETED_REFUSAL,
        "end_callback": ConversationPhase.COMPLETED_CALLBACK,
    }

    outcome_map = {
        "end_agreement": "payment_committed",
        "end_refusal": "firm_refusal",
        "end_callback": "callback_scheduled",
    }

    return {
        "conversation_phase": phase_map.get(next_node, ConversationPhase.COMPLETED_REFUSAL),
        "is_terminal": True,
        "call_progress": {
            "call_outcome": outcome_map.get(next_node, "unknown"),
        },
    }
```

**Step 2: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "from tara.nodes.end_call import end_call; r = end_call({'routing_decision': {'next_node': 'end_agreement'}}); print(r['conversation_phase'], r['is_terminal'], r['call_progress']['call_outcome'])"`

Expected: `completed_agreement True payment_committed`

---

### Task 4: Wire end_call into the graph

**Files:**
- Modify: `src/tara/graph/builder.py`

**Step 1: Import end_call**

Add to imports (after `from tara.nodes.escalate import escalate`):

```python
from tara.nodes.end_call import end_call
```

**Step 2: Update route_from_ci to return "end_call" instead of END for terminal routes**

Replace the terminal condition block in `route_from_ci`:

```python
    # Terminal conditions — route through end_call node for state tracking
    if next_node in ("end_agreement", "end_refusal", "end_callback"):
        return "end_call"
```

**Step 3: Update the return type annotation**

Add `"end_call"` to the `Literal` return type of `route_from_ci`.

**Step 4: Add end_call node to the graph**

In `build_graph()`:
- Add `builder.add_node("end_call", end_call)` after the other `add_node` calls
- Add `builder.add_edge("end_call", END)` (add to the action nodes edge loop, or separate)
- Update the conditional edges path map: replace `END: END` with `"end_call": "end_call"`

**Step 5: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "from tara.graph.builder import build_graph; g = build_graph(); print('Graph OK:', type(g).__name__)"`

Expected: `Graph OK: CompiledStateGraph`

---

### Task 5: Add identity reversal logic to identify_borrower

**Files:**
- Modify: `src/tara/nodes/identify_borrower.py`

**Step 1: Add identity reversal handling**

Replace the entire `identify_borrower` function body with logic that handles both first-time verification AND mid-call identity challenges:

```python
def identify_borrower(state: dict) -> dict:
    """
    Process identity verification. Handles two scenarios:

    1. First-time verification: Borrower confirms their name → identity_verified = True
    2. Identity reversal: Previously verified borrower claims they're not the person →
       always comply (RBI compliance), revoke verification, switch to third-party protocol.
    """
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    profile = state.get("borrower_profile", {})
    attempts = state.get("verification_attempts", 0) + 1

    # --- Mid-call identity reversal ---
    if state.get("identity_verified") and extracted.get("identity_challenge"):
        # RBI compliance: always accept identity challenge, revoke verification
        claimed = extracted.get("claimed_identity", "unknown")
        return {
            "identity_verified": False,
            "verification_attempts": attempts,
            "conversation_phase": ConversationPhase.IDENTIFICATION,
            "call_progress": {
                "identity_challenged": True,
                "identity_challenge_turn": state.get("turn_count", 0),
                "claimed_identity": claimed,
            },
        }

    # --- First-time verification ---
    verified = False

    # Primary check: LLM explicitly confirmed identity via prompt instruction
    if extracted.get("identity_confirmed") is True:
        verified = True
    # Legacy fallback checks
    elif extracted.get("last_four_ssn") and extracted["last_four_ssn"] == profile.get("last_four_ssn"):
        verified = True
    elif extracted.get("date_of_birth") and extracted["date_of_birth"] == profile.get("date_of_birth"):
        verified = True
    elif (
        extracted.get("full_name")
        and extracted["full_name"].lower() == profile.get("full_name", "").lower()
    ):
        verified = True

    new_phase = (
        ConversationPhase.PURPOSE_STATEMENT
        if verified
        else ConversationPhase.IDENTIFICATION
    )

    return {
        "identity_verified": verified,
        "verification_attempts": attempts,
        "conversation_phase": new_phase,
    }
```

**Step 2: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "
from tara.nodes.identify_borrower import identify_borrower
# Test reversal
r = identify_borrower({
    'identity_verified': True,
    'turn_count': 5,
    'routing_decision': {'extracted_info': {'identity_challenge': True, 'claimed_identity': 'wife'}},
    'borrower_profile': {}
})
print('Reversal:', r['identity_verified'], r['call_progress']['claimed_identity'])
# Test normal
r2 = identify_borrower({
    'routing_decision': {'extracted_info': {'identity_confirmed': True}},
    'borrower_profile': {}
})
print('Normal:', r2['identity_verified'])
"`

Expected: `Reversal: False wife` and `Normal: True`

---

### Task 6: Add objection loop detection to handle_objection

**Files:**
- Modify: `src/tara/nodes/handle_objection.py`

**Step 1: Add loop counter logic**

After the existing tactical memory logic, add objection loop detection that reads from and writes to `call_progress`:

```python
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
```

**Step 2: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "
from tara.nodes.handle_objection import handle_objection
# First objection
r1 = handle_objection({'routing_decision': {'extracted_info': {'objection_type': 'cannot_afford'}}, 'call_progress': {}})
print('First:', r1['call_progress']['objection_loop_count'])
# Same objection again
r2 = handle_objection({'routing_decision': {'extracted_info': {'objection_type': 'cannot_afford'}}, 'call_progress': {'last_objection': 'cannot_afford', 'objection_loop_count': 1}})
print('Loop:', r2['call_progress']['objection_loop_count'])
# Different objection
r3 = handle_objection({'routing_decision': {'extracted_info': {'objection_type': 'call_later'}}, 'call_progress': {'last_objection': 'cannot_afford', 'objection_loop_count': 2}})
print('Reset:', r3['call_progress']['objection_loop_count'])
"`

Expected: `First: 1`, `Loop: 2`, `Reset: 1`

---

### Task 7: Update central_intelligence to track call progress

**Files:**
- Modify: `src/tara/nodes/central_intelligence.py`

**Step 1: Add call_progress extraction**

After the existing tactical memory extraction block (after line ~96, before `return result`), add:

```python
    # --- Call progress: track partial payment + identity challenge ---
    progress_update: dict = {}

    partial_amount = extracted.get("partial_amount")
    if partial_amount:
        try:
            amount = float(partial_amount)
            debt = state.get("borrower_profile", {}).get("debt_amount", 0)
            progress_update["partial_amount_committed"] = amount
            progress_update["remaining_amount"] = max(0, debt - amount)
        except (ValueError, TypeError):
            pass

    payment_mode = extracted.get("payment_mode")
    if payment_mode:
        progress_update["payment_mode_confirmed"] = payment_mode

    identity_challenge = extracted.get("identity_challenge")
    if identity_challenge:
        progress_update["identity_challenged"] = True
        progress_update["identity_challenge_turn"] = state.get("turn_count", 0)
        progress_update["claimed_identity"] = extracted.get("claimed_identity", "unknown")

    if progress_update:
        result["call_progress"] = progress_update
```

**Step 2: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "from tara.nodes.central_intelligence import central_intelligence; print('CI import OK')"`

Expected: `CI import OK`

---

### Task 8: Update validate_commitment for partial payment locking

**Files:**
- Modify: `src/tara/nodes/validate_commitment.py`

**Step 1: Replace the function body**

The current `validate_commitment` handles matching against pre-built options. We add a second path: if there's a `partial_amount` but no matching offer, lock it as a partial payment and mark the call for termination.

```python
def validate_commitment(state: dict) -> dict:
    """Validate and record the borrower's commitment to a payment plan.

    Two paths:
    1. Borrower chose a pre-built option (option_id match) → lock as agreed_option
    2. Borrower committed a partial amount (no option match) → lock partial, end call
    """
    routing = state.get("routing_decision", {})
    extracted = routing.get("extracted_info", {})
    chosen_option_id = extracted.get("chosen_option_id")

    negotiation = dict(state.get("negotiation", {}))
    offers = negotiation.get("offers_presented", [])

    # Path 1: Match against pre-built payment options
    agreed = None
    if chosen_option_id:
        for opt in offers:
            if opt["option_id"] == chosen_option_id:
                agreed = opt
                break

    if agreed:
        negotiation["agreed_option"] = agreed
        return {
            "negotiation": negotiation,
            "conversation_phase": ConversationPhase.COMPLETED_AGREEMENT,
            "is_terminal": True,
            "call_progress": {
                "payment_locked": True,
                "partial_amount_committed": agreed["total_amount"],
                "remaining_amount": 0,
                "call_outcome": "payment_committed",
            },
        }

    # Path 2: Partial amount committed (not from pre-built options)
    partial = extracted.get("partial_amount")
    if partial:
        try:
            amount = float(partial)
            debt = state.get("borrower_profile", {}).get("debt_amount", 0)
            payment_mode = extracted.get("payment_mode", "")

            return {
                "conversation_phase": ConversationPhase.COMPLETED_AGREEMENT,
                "is_terminal": True,
                "call_progress": {
                    "payment_locked": True,
                    "partial_amount_committed": amount,
                    "remaining_amount": max(0, debt - amount),
                    "payment_mode_confirmed": payment_mode,
                    "call_outcome": "payment_committed",
                },
                "tactical_memory": {"partial_amount_offered": amount},
            }
        except (ValueError, TypeError):
            pass

    # No commitment yet — stay in commitment phase
    return {
        "conversation_phase": ConversationPhase.COMMITMENT,
    }
```

**Step 2: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "
from tara.nodes.validate_commitment import validate_commitment
# Test partial payment lock
r = validate_commitment({
    'routing_decision': {'extracted_info': {'partial_amount': '10000', 'payment_mode': 'upi'}},
    'borrower_profile': {'debt_amount': 85000},
    'negotiation': {'offers_presented': []}
})
print('Locked:', r['call_progress']['payment_locked'])
print('Partial:', r['call_progress']['partial_amount_committed'])
print('Remaining:', r['call_progress']['remaining_amount'])
print('Terminal:', r['is_terminal'])
"`

Expected: `Locked: True`, `Partial: 10000.0`, `Remaining: 75000.0`, `Terminal: True`

---

### Task 9: Add call progress + termination rules to the prompt

**Files:**
- Modify: `src/tara/llm/prompts.py`

This is the largest change — the prompt needs three new sections and two modifications.

**Step 1: Extract call_progress data in build_central_intelligence_prompt**

After the tactical memory extraction block (around line 130), add:

```python
    # Call progress — what's happened THIS call
    progress = state.get("call_progress", {})
    partial_committed = progress.get("partial_amount_committed", 0)
    payment_mode = progress.get("payment_mode_confirmed", "")
    payment_locked = progress.get("payment_locked", False)
    remaining = progress.get("remaining_amount", profile.get("debt_amount", 0))
    identity_challenged = progress.get("identity_challenged", False)
    challenge_turn = progress.get("identity_challenge_turn", 0)
    claimed_identity = progress.get("claimed_identity", "")
    objection_loop = progress.get("objection_loop_count", 0)
    last_objection = progress.get("last_objection", "")
```

**Step 2: Add == THIS CALL'S PROGRESS == section to the prompt string**

Insert after the `== TACTICAL MEMORY ==` section (before `== CALL FLOW ==`):

```
== THIS CALL'S PROGRESS ==
Partial amount committed: {f'Rs.{partial_committed:,.0f} via {payment_mode} ✓ LOCKED' if payment_locked else f'Rs.{partial_committed:,.0f}' if partial_committed > 0 else 'None yet'}
Remaining to discuss: Rs.{remaining:,.0f}
Identity challenged: {'YES at turn ' + str(challenge_turn) + ' (claimed: ' + claimed_identity + ')' if identity_challenged else 'No'}
Objection loop: {f'"{last_objection}" repeated {objection_loop}x' if objection_loop > 1 else 'None'}

{'⚠️ PAYMENT LOCKED — You already secured Rs.' + f'{partial_committed:,.0f}' + '. Do NOT ask for more. End the call with end_agreement NOW.' if payment_locked else ''}
{'⚠️ IDENTITY CHALLENGED — Borrower claims to be ' + claimed_identity + '. Switch to THIRD PARTY protocol. Do NOT reveal any loan details.' if identity_challenged else ''}
{'⚠️ OBJECTION LOOP DETECTED — Same excuse "' + last_objection + '" repeated ' + str(objection_loop) + 'x. Give FINAL WARNING and end with end_refusal.' if objection_loop >= 3 else ''}
```

**Step 3: Add == IDENTITY REVERSAL HANDLING == section**

Insert after the existing `== THIRD PARTY HANDLING ==` section:

```
== IDENTITY REVERSAL (mid-call denial) ==
If borrower ALREADY confirmed their name but NOW claims they're someone else:
• Set extracted_info: {{"identity_challenge": true, "claimed_identity": "<who they claim to be>"}}
• Route to "identify_borrower" — the node will revoke verification
• Then follow THIRD PARTY HANDLING rules above — never reveal loan details
• This is a common escapist tactic but we MUST comply for RBI compliance
```

**Step 4: Add == CALL TERMINATION RULES == section**

Insert after the `== AGGRESSION SCALE ==` section (before `== YOUR DECISION FRAMEWORK ==`):

```
== CALL TERMINATION RULES ==
End the call when ANY of these conditions are met:
1. Payment committed (partial or full) → "end_agreement" — lock amount + mode first
2. Firm refusal after 3+ attempts with different tactics → "end_refusal" with consequences warning
3. Callback agreed with EXACT time within 24 hours → "end_callback"
4. Same objection repeated 3+ times (loop detected) → "end_refusal" with final warning
5. Turn count > 30 with no progress → "end_refusal" with final warning
6. Borrower abusive for 3+ consecutive turns → "escalate"
7. After locking a partial payment → END the call immediately (end_agreement). Do NOT continue negotiating the remaining amount on this call.
8. Identity challenged → follow third-party protocol, then "end_callback" to call back for actual borrower

CRITICAL: After borrower commits ANY amount (even partial), confirm payment mode and END.
Do NOT keep pushing for more money on the same call.
```

**Step 5: Add identity_challenge to extracted_info schema**

In the `extracted_info` documentation section, add:

```
  • "identity_challenge" — true if borrower claims they are NOT the borrower (mid-call reversal)
  • "claimed_identity" — who they claim to be: "wife", "husband", "parent", "friend", "wrong_person"
```

**Step 6: Update the turn limit guard**

In the prompt, change any reference to turn count limits to use 30 instead of whatever is currently there. The existing prompt says "NEVER accept callback more than 24 hours away" which is fine. The new CALL TERMINATION RULES section handles the 30-turn limit.

**Step 7: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "
from tara.llm.prompts import build_central_intelligence_prompt
state = {
    'borrower_profile': {'full_name': 'Test', 'debt_amount': 85000, 'days_past_due': 30},
    'conversation_phase': 'negotiation',
    'turn_count': 5,
    'identity_verified': True,
    'current_sentiment': 'neutral',
    'objections_raised': [],
    'negotiation': {'offers_presented': []},
    'tactical_memory': {},
    'negotiation_history': [],
    'call_progress': {
        'partial_amount_committed': 10000,
        'payment_mode_confirmed': 'upi',
        'payment_locked': True,
        'remaining_amount': 75000,
        'identity_challenged': False,
        'objection_loop_count': 0,
        'last_objection': '',
    },
}
prompt = build_central_intelligence_prompt(state)
assert 'THIS CALL' in prompt, 'Missing call progress section'
assert 'PAYMENT LOCKED' in prompt, 'Missing payment locked warning'
assert 'TERMINATION RULES' in prompt, 'Missing termination rules'
assert 'IDENTITY REVERSAL' in prompt, 'Missing identity reversal section'
print('Prompt OK — all new sections present')
"`

Expected: `Prompt OK — all new sections present`

---

### Task 10: Add call_progress to UI state serializer

**Files:**
- Modify: `src/tara/web/routes.py`

**Step 1: Add call_progress to _serialize_state**

In `_serialize_state()`, after the `"tactical_memory"` line (line ~69), add:

```python
        "call_progress": result.get("call_progress", {}),
```

**Step 2: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "from tara.web.routes import _serialize_state; r = _serialize_state({'call_progress': {'payment_locked': True}}); print('call_progress in state:', 'call_progress' in r)"`

Expected: `call_progress in state: True`

---

### Task 11: Update graph turn limit to 30

**Files:**
- Modify: `src/tara/graph/builder.py`

**Step 1: Change the hard turn limit**

In `route_from_ci()`, change:

```python
    if state.get("turn_count", 0) > 50:
```

to:

```python
    if state.get("turn_count", 0) > 30:
```

**Step 2: Verify**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "from tara.graph.builder import build_graph; g = build_graph(); print('Graph with 30-turn limit OK')"`

Expected: `Graph with 30-turn limit OK`

---

### Task 12: Full integration verification

**Step 1: Verify all imports chain correctly**

Run: `cd "/Users/bhavish/Documents/BR<>DPDzero/Convo_State_Machine" && uv run python -c "
from tara.state.schema import TaraState, CallProgress, _merge_call_progress
from tara.nodes.load_context import load_context
from tara.nodes.central_intelligence import central_intelligence
from tara.nodes.identify_borrower import identify_borrower
from tara.nodes.handle_objection import handle_objection
from tara.nodes.validate_commitment import validate_commitment
from tara.nodes.end_call import end_call
from tara.graph.builder import build_graph
from tara.llm.prompts import build_central_intelligence_prompt

# Verify call_progress reducer
existing = {'partial_amount_committed': 0, 'payment_locked': False}
update = {'partial_amount_committed': 10000, 'payment_locked': True}
merged = _merge_call_progress(existing, update)
assert merged['partial_amount_committed'] == 10000
assert merged['payment_locked'] is True
print('Reducer OK')

# Verify graph compiles with end_call node
graph = build_graph()
print(f'Graph OK: {type(graph).__name__}')

# Verify load_context initializes call_progress
state = load_context({'borrower_profile': {'borrower_id': 'BRW-001'}})
assert 'call_progress' in state
assert state['call_progress']['remaining_amount'] > 0
print(f'Load context OK, remaining: {state[\"call_progress\"][\"remaining_amount\"]}')

print('\\nAll integration checks passed!')
"
`

Expected: All checks pass, `All integration checks passed!`

---

## Implementation Order

| # | Task | Impact | Risk |
|---|------|--------|------|
| 1 | CallProgress schema | Foundation | Low — additive |
| 2 | load_context init | Foundation | Low — additive |
| 3 | end_call node | Medium | Low — new file |
| 4 | Wire end_call into graph | High | Medium — graph routing change |
| 5 | Identity reversal in identify_borrower | High | Low — additive logic |
| 6 | Objection loop in handle_objection | Medium | Low — additive logic |
| 7 | Call progress in central_intelligence | High | Low — additive extraction |
| 8 | Partial payment in validate_commitment | High | Medium — replaces existing logic |
| 9 | Prompt changes (call progress + termination + identity) | Critical | Medium — large prompt edit |
| 10 | UI state serializer | Low | Low — one line |
| 11 | Turn limit 30 | Low | Low — one number |
| 12 | Integration verification | Validation | None |
