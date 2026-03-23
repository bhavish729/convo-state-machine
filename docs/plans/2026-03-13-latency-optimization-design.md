# Latency Optimization Design — Full Pipeline

**Date:** 2026-03-13
**Goal:** Reduce perceived latency from ~2-5s to ~0.8-1.5s (user stops speaking → first audio heard)

## Current Latency Profile

```
VAD(800ms) + STT(0ms) + LLM(500-2000ms) + TTS_pre(0ms) + TTS_gen(100-400ms) + TTS_stream(300-1500ms) + Blob(50-100ms) + Pause(150ms)
= ~1900ms to ~4950ms
```

## Phase A: Quick Wins (~400ms saved)

### A1. VAD Silence Timeout: 800ms → 500ms
- File: `index.html` — `SILENCE_TIMEOUT`
- Safe minimum for Hinglish speech patterns

### A2. Inter-Turn Pause: 150ms → 0ms
- File: `index.html` — `autoStartListening()` setTimeout
- AudioContext already initialized, delay unnecessary

### A3. Async LLM: `invoke` → `ainvoke`
- File: `central_intelligence.py`
- Make CI node async, use `await llm.ainvoke()` instead of sync `llm.invoke()`
- Eliminates executor thread overhead (~20-50ms)

## Phase B: Streaming Audio Playback (~300-1500ms saved)

### B1. Web Audio API Chunked Decode
- File: `index.html`
- Replace Blob accumulation with per-chunk `decodeAudioData()` + `AudioBufferSourceNode` scheduling
- First chunk plays immediately; subsequent chunks scheduled on audio timeline
- Buffer first ~2 chunks before starting (MP3 frame boundary safety)
- Blob fallback if Web Audio decode fails

### B2. TTS Start Signal
- File: `routes.py`
- Send `tts_start` message before streaming so frontend prepares AudioContext

## Phase C: LLM Streaming → TTS Pipe (~200-800ms saved)

### C1. Stream LLM + Incremental JSON Parse
- File: `central_intelligence.py`
- Use `llm.astream()`, accumulate tokens
- Extract `response_to_borrower` as soon as its value is complete
- Continue accumulating for routing fields (`next_node`, `extracted_info`)
- Two-phase state update: early (response text) + late (routing)

### C2. Streaming Process Flow
- File: `routes.py`
- New `_process_user_input_streaming()` that starts TTS as soon as response text is available
- LLM continues generating routing fields concurrently with TTS

### C3. TTS Streaming Text Input
- File: `tts.py`
- New `synthesize_stream(text_chunks)` that sends text chunks incrementally to ElevenLabs
- Uses ElevenLabs input-streaming protocol (multiple `{text: chunk}` before EOS)

## Target Latency

```
VAD(500ms) + LLM_to_first_text(200-800ms) + TTS_first_byte(100-200ms) + decode(30ms)
= ~830ms to ~1530ms
```

~50-70% reduction in perceived latency.
