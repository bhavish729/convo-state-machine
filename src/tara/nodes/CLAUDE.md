# Nodes — Deterministic State Update Functions

## Pattern: Central Intelligence + Action Nodes

This is the most important architectural pattern in Tara:

1. `central_intelligence.py` is the **ONLY** node that calls the LLM
2. It returns `routing_decision` with `{next_node, reasoning, response_to_borrower, extracted_info}`
3. The graph's conditional edge (`route_from_ci` in `graph/builder.py`) reads `next_node` and routes to the appropriate action node
4. Action nodes are **pure state-update functions** — they read `routing_decision.extracted_info` and update state fields
5. After the action node runs, the turn ends (edge to `END`). The next user message re-enters via checkpoint.

## Node Responsibilities

| Node | What it does | Key state updates |
|------|-------------|-------------------|
| `load_context` | First node. Initializes state with borrower profile + defaults. Skips on subsequent turns (guard: `if state.get("conversation_phase") is not None: return {}`) | `borrower_profile`, `conversation_phase=INIT`, all defaults |
| `central_intelligence` | Calls LLM, parses JSON routing, extracts sentiment + tactical memory + call progress. Retries once on JSON parse failure. | `messages`, `routing_decision`, `turn_count`, `current_sentiment`, `tactical_memory`, `call_progress` |
| `identify_borrower` | Two paths: (1) first-time verification via extracted_info, (2) mid-call identity reversal — revokes verification, records challenge in call_progress. | `identity_verified`, `verification_attempts`, `conversation_phase`, `call_progress` |
| `state_purpose` | Sets phase + records consequence used in tactical memory. | `conversation_phase`, `tactical_memory` |
| `handle_objection` | Reads objection_type, tracks excuses in tactical memory, detects objection loops (consecutive same-type counter). | `conversation_phase`, `current_objection`, `objections_raised`, `tactical_memory`, `call_progress` |
| `present_options` | Calls `generate_payment_options()` to create payment plans. Tracks tactic used. | `conversation_phase`, `negotiation.offers_presented`, `tactical_memory` |
| `validate_commitment` | Two paths: (1) pre-built option match, (2) partial amount lock (sets payment_locked, calculates remaining, marks terminal). | `negotiation.agreed_option`, `is_terminal`, `conversation_phase`, `call_progress` |
| `escalate` | Marks conversation terminal with escalation reason. | `conversation_phase=ESCALATION`, `escalation_reason`, `is_terminal=True` |
| `end_call` | Terminal handler — maps next_node (end_agreement/end_refusal/end_callback) to phase + outcome. | `conversation_phase`, `is_terminal=True`, `call_progress.call_outcome` |

## Important: Gemini Workaround in central_intelligence

Gemini requires the last message to be from a human. When the conversation is empty (first turn) or ends with an AI message (after action node loop), `central_intelligence` injects a synthetic `HumanMessage` to satisfy Gemini's constraint.

## Adding a New Action Node

1. Create `src/tara/nodes/my_node.py` with `def my_node(state: dict) -> dict:`
2. Import and register in `graph/builder.py`:
   - Add to `ACTION_NODES` set
   - `builder.add_node("my_node", my_node)`
   - Add to conditional edge path map
   - Add `builder.add_edge("my_node", END)`
3. Add the node name to the routing decision options in `llm/prompts.py`
