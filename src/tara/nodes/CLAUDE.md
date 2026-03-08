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
| `central_intelligence` | Calls LLM with full state context. Parses JSON routing decision. | `messages` (AI response), `routing_decision`, `turn_count` |
| `identify_borrower` | Checks `extracted_info.identity_confirmed`. Legacy fallback checks SSN/DOB/name. | `identity_verified`, `verification_attempts`, `conversation_phase` |
| `state_purpose` | Currently a stub — just sets phase. | `conversation_phase=PURPOSE_STATEMENT` |
| `handle_objection` | Reads `extracted_info.objection_type`, logs it. | `conversation_phase`, `current_objection`, `objections_raised` (appended) |
| `present_options` | Calls `generate_payment_options()` to create payment plans. | `conversation_phase`, `negotiation.offers_presented` |
| `validate_commitment` | Matches `extracted_info.chosen_option_id` against offers. If found, sets terminal. | `negotiation.agreed_option`, `is_terminal`, `conversation_phase` |
| `escalate` | Marks conversation terminal with escalation reason. | `conversation_phase=ESCALATION`, `escalation_reason`, `is_terminal=True` |

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
