# Tara — Multi-Agent Collections State Machine

## What is this?

Tara is a voice-first debt collections agent built on LangGraph. It uses 3 independent agent graphs — one per delinquency stage — that share common infrastructure (state schema, voice pipeline, LLM provider, nodes). Each agent uses the **Central Intelligence** pattern: one LLM node evaluates full conversation context each turn and dynamically routes to deterministic action nodes.

## Multi-Agent Architecture

```
POST /api/session?borrower_id=X&agent_type=npa
  → resolve_agent_type() from DPD (or manual override)
  → build_graph(agent_type) → compiled StateGraph
  → graph.ainvoke(initial_state) → opening message
  → WebSocket streams voice turns through the selected graph
```

### Three Agents

| | Pre-Due (0-30 DPD) | Bucket X (31-90 DPD) | NPA (91+ DPD) |
|---|---|---|---|
| **Goal** | Get firm payment date | Recover full amount | Maximize settlement % |
| **Tone** | Warm/helpful | Professional/firm | Assertive/urgent |
| **Settlement?** | No (full EMI only) | No (full amount) | Yes (20-50% floor) |
| **Installments?** | No | No | Yes (6/12/18 mo) |
| **Unique node** | `confirm_payment_date` | `confirm_full_payment` | `validate_commitment` |
| **Max turns** | 20 | 30 | 30 |

### Graph Topology (shared pattern)

```
START → load_context → central_intelligence ──(conditional)──→ action_node → END
                                              │                      ↑
                                              ↓               Next user message
                                           end_call → END     re-enters via
                                                               MemorySaver
```

- `central_intelligence` is the ONLY node that calls the LLM. Each agent wires it to its own prompt via `make_central_intelligence(prompt_builder)`.
- Action nodes are **deterministic state-update functions** — they read `routing_decision.extracted_info` and update state fields.
- Terminal routes (`end_agreement/end_refusal/end_callback`) go through `end_call` node to record call outcomes.

## Tech Stack

- **LangGraph** — state machine with checkpointed state
- **FastAPI + WebSocket** — real-time voice streaming
- **ElevenLabs** — STT (Scribe v2 realtime) + TTS (WebSocket streaming, `eleven_multilingual_v2`)
- **LLM** — configurable via `TARA_LLM_PROVIDER` env var (openai/anthropic/gemini). Currently using Gemini Flash Lite.
- **LangSmith** — automatic tracing via env vars (no code changes needed)

## Quick Start

```bash
cp .env.example .env   # Fill in API keys
uv venv && uv pip install -e ".[dev]"
uv run tara            # Server on http://localhost:8000
```

## Project Structure

```
src/tara/
├── config.py              # Pydantic Settings (TARA_ env prefix)
├── main.py                # uvicorn launcher
├── agents/                # ★ Multi-agent package (graph factory + 3 agents)
│   ├── __init__.py        # build_graph(), resolve_agent_type(), VALID_AGENT_TYPES
│   ├── pre_due/           # 0-30 DPD: warm reminder, full EMI only
│   │   ├── graph.py       # build_pre_due_graph() — simpler graph, max 20 turns
│   │   ├── nodes.py       # confirm_payment_date (full EMI lock)
│   │   └── prompts.py     # Warm tone, no settlement, 4 consequences
│   ├── bucket_x/          # 31-90 DPD: firm recovery, full amount
│   │   ├── graph.py       # build_bucket_x_graph() — no settlement nodes
│   │   ├── nodes.py       # confirm_full_payment (full amount, 99% tolerance)
│   │   └── prompts.py     # Firm tone, all consequences + livelihood
│   └── npa/               # 91+ DPD: settlement negotiation
│       ├── graph.py       # build_npa_graph() — full node set
│       └── prompts.py     # NPA strategy, settlement floors, all tactics
├── llm/                   # LLM provider factory (get_llm)
├── state/                 # TaraState TypedDict + enums (shared by all agents)
├── graph/                 # Legacy graph builder (backward compat)
├── nodes/                 # Shared action nodes (no LLM calls)
├── voice/                 # ElevenLabs STT + TTS with Hindi preprocessing
├── data/                  # Borrower profiles (JSON) + payment option generator
└── web/                   # FastAPI app + WebSocket handler + UI
```

## Key Conventions

- **Language**: All prompts and Tara responses are in Hinglish (Devanagari script with English technical terms in Roman)
- **Agent selection**: Auto from DPD (≤30→pre_due, 31-90→bucket_x, 91+→npa) or manual override via `?agent_type=` query param
- **CI factory**: `make_central_intelligence(prompt_builder)` in `nodes/central_intelligence.py` creates CI nodes wired to agent-specific prompts without duplicating the complex JSON parsing/retry/sentiment logic
- **State updates**: Nodes return dicts that LangGraph merges into `TaraState`. Fields with `operator.add` reducers accumulate; others overwrite.
- **Custom reducers**: `tactical_memory` uses `_merge_tactical_memory` (appends lists, overwrites scalars). `call_progress` uses `_merge_call_progress` (all scalars, overwrite).
- **Routing**: CI sets `routing_decision` (JSON with `next_node`, `reasoning`, `response_to_borrower`, `extracted_info`). Each agent's `route_from_ci()` reads `next_node` and maps to its available nodes.
- **Terminal routing**: `end_agreement/end_refusal/end_callback` route through `end_call` node (not directly to END) to record call outcomes.
- **TTS preprocessing**: `voice/tts.py` has `_preprocess_for_tts()` that converts acronyms to Devanagari phonetics and currency amounts to Hindi number words.
- **No tests yet**: `tests/` exists but is empty. Use `uv run python -c "from tara.agents import build_graph; [build_graph(t) for t in ['pre_due','bucket_x','npa']]; print('OK')"` to verify.

## Environment Variables

All config uses `TARA_` prefix (see `.env.example`):
- `TARA_LLM_PROVIDER` — openai | anthropic | gemini
- `TARA_ELEVENLABS_API_KEY` + `TARA_ELEVENLABS_VOICE_ID` — voice synthesis
- `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` — enables LangSmith tracing

## Common Tasks

- **Change LLM model**: Edit `TARA_GOOGLE_MODEL` (or equivalent) in `.env`
- **Add a new agent**: Create `agents/my_agent/` with `graph.py`, `prompts.py`, `nodes.py`. Register in `agents/__init__.py`.
- **Add a node to an agent**: Create in `nodes/` (shared) or `agents/my_agent/nodes.py` (agent-specific). Register in agent's `graph.py`.
- **Modify collections strategy**: Edit the agent's `prompts.py` — the system prompt drives all behavior
- **Add TTS pronunciation fix**: Add to `_TTS_REPLACEMENTS` dict or `_convert_currency_to_hindi()` in `voice/tts.py`
- **Add a mock borrower**: Add to `data/borrowers.json` (loaded by `mock_borrowers.py`)

## API Endpoints

- `POST /api/session?borrower_id=BRW-001&agent_type=npa` — Create session (agent auto-detected from DPD if `agent_type` omitted)
- `POST /api/session/next-call` (JSON body: `{borrower_id, agent_type, previous_calls}`) — Multi-call: creates new session with negotiation history from prior calls
- `GET /api/graph?agent_type=npa` — Render agent's LangGraph as PNG
- `WebSocket /ws/{session_id}` — Real-time voice streaming
