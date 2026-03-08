# Web — FastAPI + WebSocket + Voice Chat UI

## app.py — FastAPI Factory

`create_app()` returns a FastAPI app with CORS and routes mounted. Loads `.env` via `load_dotenv()` for LangSmith tracing.

## routes.py — API Endpoints

### `POST /api/session?borrower_id=BRW-001`
Creates a new session, runs initial graph invocation (load_context → central_intelligence), returns Tara's opening message.

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

### `_serialize_state(result)`
Extracts serializable state for the UI debug panel. Includes call_progress, tactical_memory, aggression level. Strips messages (too large).

## session.py — In-Memory Session Manager

`SessionManager` stores `ConversationSession` objects keyed by session_id. Each session holds:
- `graph` — compiled LangGraph StateGraph
- `thread_id` — MemorySaver checkpoint ID
- `tts` — persistent `ElevenLabsTTS` WebSocket connection
- `opening_message` — cached for streaming on WS connect

Sessions have a 1-hour TTL. `_cleanup_stale()` runs on each `create_session()` call.

## static/index.html — Voice Chat UI

Single-file HTML/CSS/JS. No framework. Key features:
- **Push-to-talk**: Hold spacebar or click mic button
- **Barge-in**: Can interrupt Tara mid-speech (monitors mic RMS > 0.025 threshold during playback)
- **Call timer**: MM:SS display in header
- **State debug panel**: Left sidebar showing real-time state (phase, sentiment, aggression, routing decision)
- **Error toasts**: Top-right slide-in notifications
- **Borrower selector**: Dropdown to pick mock borrower profile
- **Latency display**: Shows STT, LLM, TTS timings per turn
