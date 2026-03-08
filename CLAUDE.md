# Tara — Collections Agent State Machine

## What is this?

Tara is a voice-first NPA debt collections agent built on LangGraph. It uses a **Central Intelligence** pattern: one LLM node evaluates full conversation context each turn and dynamically routes to deterministic action nodes.

## Architecture

```
START → load_context → central_intelligence ──(conditional)──→ action_node → END
                                                                     ↑
                            Next user message re-enters via          │
                            MemorySaver checkpoint ─────────────────┘
```

- `central_intelligence` is the ONLY node that calls the LLM
- Action nodes (`identify_borrower`, `state_purpose`, `handle_objection`, `present_options`, `validate_commitment`, `escalate`) are **deterministic state-update functions** — they read `routing_decision.extracted_info` and update state fields
- The graph compiles with `MemorySaver` checkpointing — each WebSocket turn re-enters the graph at `load_context` with accumulated state

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
├── llm/                   # LLM provider factory + system prompts
├── state/                 # TaraState TypedDict + enums
├── graph/                 # StateGraph assembly + routing function
├── nodes/                 # Deterministic action nodes (no LLM calls)
├── tools/                 # Tool functions (currently bound but unused)
├── voice/                 # ElevenLabs STT + TTS with Hindi preprocessing
├── data/                  # Mock borrower profiles + payment options
└── web/                   # FastAPI app + WebSocket handler + UI
```

## Key Conventions

- **Language**: All prompts and Tara responses are in Hinglish (Devanagari script with English technical terms in Roman)
- **State updates**: Nodes return dicts that LangGraph merges into `TaraState`. Fields with `operator.add` reducers (`sentiment_history`, `objections_raised`) accumulate; others overwrite.
- **Routing**: `central_intelligence` sets `routing_decision` (JSON with `next_node`, `reasoning`, `response_to_borrower`, `extracted_info`). The `route_from_ci()` function reads `next_node` and returns the edge target.
- **TTS preprocessing**: `voice/tts.py` has `_preprocess_for_tts()` that converts acronyms to Devanagari phonetics and currency amounts to Hindi number words before sending to ElevenLabs.
- **No tests yet**: `tests/` exists but is empty.

## Environment Variables

All config uses `TARA_` prefix (see `.env.example`):
- `TARA_LLM_PROVIDER` — openai | anthropic | gemini
- `TARA_ELEVENLABS_API_KEY` + `TARA_ELEVENLABS_VOICE_ID` — voice synthesis
- `LANGCHAIN_TRACING_V2=true` + `LANGCHAIN_API_KEY` — enables LangSmith tracing

## Common Tasks

- **Change LLM model**: Edit `TARA_GOOGLE_MODEL` (or equivalent) in `.env`
- **Add a new action node**: Create in `nodes/`, register in `graph/builder.py` (add to `ACTION_NODES` set + `add_node` + path map)
- **Modify collections strategy**: Edit `llm/prompts.py` — the system prompt drives all behavior
- **Add TTS pronunciation fix**: Add to `_TTS_REPLACEMENTS` dict or `_convert_currency_to_hindi()` in `voice/tts.py`
- **Add a mock borrower**: Add to `BORROWER_DB` in `data/mock_borrowers.py`
