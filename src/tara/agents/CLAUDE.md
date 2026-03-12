# Agents — Per-Delinquency-Stage Graph Definitions

## Architecture

Three independent agent graphs share common infrastructure (state schema, voice pipeline, LLM provider, shared nodes) but each owns its graph topology, prompt, and any unique nodes.

```
agents/
├── __init__.py        # build_graph(), resolve_agent_type(), VALID_AGENT_TYPES
├── pre_due/           # 0-30 DPD
│   ├── graph.py       # build_pre_due_graph() — max 20 turns
│   ├── nodes.py       # confirm_payment_date (full EMI lock)
│   └── prompts.py     # Warm tone, no settlement, 4 consequences
├── bucket_x/          # 31-90 DPD
│   ├── graph.py       # build_bucket_x_graph() — no settlement nodes
│   ├── nodes.py       # confirm_full_payment (full amount, 99% tolerance)
│   └── prompts.py     # Firm tone, all consequences + livelihood
└── npa/               # 91+ DPD
    ├── graph.py        # build_npa_graph() — full node set
    └── prompts.py      # Settlement negotiation, 20-50% floors, installments
```

## __init__.py — Graph Factory

- `VALID_AGENT_TYPES = {"pre_due", "bucket_x", "npa"}`
- `resolve_agent_type(days_past_due)` → auto-detect from DPD
- `build_graph(agent_type)` → compiled StateGraph with MemorySaver

## Agent Selection Flow

```
POST /api/session?borrower_id=X&agent_type=npa
  → session_manager.create_session(borrower_id, agent_type)
  → if agent_type is None: resolve from borrower's DPD
  → build_graph(agent_type)
  → graph.ainvoke(initial_state)
```

## CI Factory Pattern

Each agent wires its prompt to the shared Central Intelligence implementation:

```python
from tara.nodes.central_intelligence import make_central_intelligence
from tara.agents.npa.prompts import build_npa_prompt

npa_central_intelligence = make_central_intelligence(build_npa_prompt)
```

This avoids duplicating the complex CI logic (JSON parsing, retry, sentiment tracking, tactical memory) across 3 agents.

## Per-Agent Details

### Pre-Due (0-30 DPD)
- **Goal**: Get firm payment date for full EMI
- **Tone**: Warm, helpful, rapport-building
- **Aggression**: Starts L1, caps at L3 (no FINAL WARNING)
- **Consequences**: Only 4 — CIBIL, late fees, future loan impact, bounce charges
- **Unique node**: `confirm_payment_date` — locks date + payment mode for full EMI. Rejects partial payments.
- **Graph**: No `present_options` or `validate_commitment`. If LLM tries those routes, they redirect to `confirm_payment_date`.

### Bucket X (31-90 DPD)
- **Goal**: Recover full outstanding amount
- **Tone**: Professional, firm, no-nonsense
- **Aggression**: Starts L2, goes up to L4
- **Consequences**: All available including livelihood personalization
- **Unique node**: `confirm_full_payment` — only accepts amounts ≥99% of debt. Rejects partial amounts.
- **Graph**: Uses `confirm_full_payment` instead of `validate_commitment`. No `present_options`.

### NPA (91+ DPD)
- **Goal**: Maximize settlement recovery percentage
- **Tone**: Assertive, urgent, time-pressure
- **Aggression**: Starts L2, reaches L4
- **Consequences**: Full arsenal (CIBIL, legal, field visit, interest, future loans)
- **Settlement**: Yes — floors by risk tier (low: 50%, medium: 30%, high: 20%)
- **Installments**: 6/12/18 month plans via `present_options`
- **Graph**: Full node set including `present_options` and `validate_commitment`

## Adding a New Agent

1. Create `agents/my_agent/` with `graph.py`, `prompts.py`, optional `nodes.py`
2. Write `build_my_agent_prompt(state) → str` in `prompts.py`
3. Write `build_my_agent_graph()` in `graph.py` using `make_central_intelligence(build_my_agent_prompt)`
4. Register in `agents/__init__.py`: add to `AGENT_BUILDERS` dict
5. Add aggression function `_get_aggression_level()` to `prompts.py`
