# Web — FastAPI + WebSocket + Voice Chat UI

## app.py — FastAPI Factory

`create_app()` returns a FastAPI app with CORS and routes mounted. Loads `.env` via `load_dotenv()` for LangSmith tracing.

## routes.py — API Endpoints

### `POST /api/session?borrower_id=BRW-001&agent_type=npa`
Creates a new session with the specified agent type. If `agent_type` is omitted, auto-detects from borrower's DPD (≤30→pre_due, 31-90→bucket_x, 91+→npa). Runs initial graph invocation (load_context → central_intelligence), returns Tara's opening message + full state snapshot.

### `POST /api/session/next-call` (JSON body)
Multi-call endpoint for follow-up calls. Accepts `{borrower_id, agent_type, previous_calls}` via `NextCallRequest` Pydantic model. Creates a new session with `negotiation_history` populated from prior call outcomes. Allows agent type escalation between calls.

### `GET /api/graph?agent_type=npa`
Renders the specified agent's LangGraph as a PNG image (or Mermaid text fallback).

### `WebSocket /ws/{session_id}`
Real-time voice communication. Full lifecycle:

1. **Connect**: Accept WebSocket, connect persistent TTS WebSocket
2. **Opening TTS**: Stream Tara's opening message as audio
3. **Recording loop**:
   - `start_recording` → Open ElevenLabs STT session
   - Binary frames → Forward PCM audio to STT
   - `stop_recording` → Commit STT, get final transcript
   - Feed transcript into `graph.ainvoke()` with `HumanMessage`
   - Send AI transcript + state update + TTS audio back to client
4. **Terminal**: Send `{type: "terminal"}` but do NOT close WebSocket (let client finish playing audio)

### WebSocket Message Protocol

**Client → Server (JSON text frames):**
- `{type: "start_recording", sample_rate: 16000}` — begin voice input
- `{type: "stop_recording"}` — end voice input, trigger processing
- `{message: "text input"}` — text fallback

**Client → Server (binary frames):**
- PCM audio chunks during recording

**Server → Client (JSON text frames):**
- `{type: "status", status: "listening|thinking|speaking|no_speech"}`
- `{type: "partial_transcript", text: "..."}` — live STT partials
- `{type: "transcript", speaker: "user|tara", text: "...", latency: {...}}`
- `{type: "state_update", state: {...}}` — full state snapshot for debug panel
- `{type: "audio_end", latency: {...}}` — marks end of TTS audio stream
- `{type: "terminal", phase: "..."}` — conversation ended
- `{type: "error", error: "..."}` — error message

**Server → Client (binary frames):**
- MP3 audio chunks (TTS output)

### Key helpers
- `_serialize_state(result, agent_type)` — extracts serializable state for UI. Uses agent-specific aggression function via `_get_aggression_fn()`.
- `NextCallRequest` — Pydantic model for `/api/session/next-call` request body.

## session.py — In-Memory Session Manager

`SessionManager` stores `ConversationSession` objects keyed by session_id. Each session holds:
- `graph` — compiled LangGraph StateGraph
- `thread_id` — MemorySaver checkpoint ID
- `agent_type` — which agent is running ("pre_due", "bucket_x", "npa")
- `tts` — persistent `ElevenLabsTTS` WebSocket connection
- `opening_message` — cached for streaming on WS connect

Sessions have a 1-hour TTL. `_cleanup_stale()` runs on each `create_session()` call. Agent type is auto-resolved from borrower DPD if not explicitly provided.

## static/index.html — Voice Chat UI

Single-file HTML/CSS/JS (no framework). Three-column layout:

### Layout
```
┌──────────────────────────────────────────────────────────────┐
│ Header: Tara [phase] [Call N] │ 02:34 │ [End Call]           │
├─────────────┬──────────────────────┬─────────────────────────┤
│ LEFT 320px  │   CENTER (flex)      │ RIGHT 340px             │
│ CONV STATE  │   Chat + Voice UI    │ AGENT CONFIG            │
│ ──────────  │   Transcript         │ ──────────              │
│ Routing     │   Bottom bar:        │ Agent profile badge     │
│ Session     │    Latency, status,  │ Goal, aggression, etc.  │
│ Identity    │    text input        │ Borrower summary        │
│ Sentiment   │                      │ Call history            │
│ Negotiation │                      │ [Next Call] [Reset All] │
│ Call Prog.  │                      │                         │
│ Borrower    │                      │                         │
└─────────────┴──────────────────────┴─────────────────────────┘
```

### Key Features
- **Three agents**: Color-coded badges (pre_due=green, bucket_x=amber, npa=red)
- **Start screen**: Borrower preset dropdown + field display + agent auto-detection from DPD with override
- **Multi-call simulation**: Call counter in header, call history in right panel, "Next Call" button creates follow-up session with previous call outcomes carried over
- **Between-calls state**: Agent type override enabled, Next Call + Reset All buttons visible
- **VAD + Barge-in**: Auto-detects speech end (1.2s silence), can interrupt Tara mid-speech (RMS > 0.025)
- **Call timer**: MM:SS display in header
- **State debug panel**: Left sidebar showing real-time state (phase, sentiment, aggression, routing, agent type)
- **Error toasts**: Top-right slide-in notifications
- **Latency display**: Shows STT, LLM, TTS timings per turn
