# Voice — ElevenLabs STT + TTS Pipeline

## Overview

Voice pipeline: Browser mic → PCM audio → WebSocket → ElevenLabs STT → text → LangGraph → response text → ElevenLabs TTS → audio chunks → WebSocket → browser playback.

## stt.py — Speech-to-Text (ElevenLabs Scribe v2)

`RealtimeTranscriber` manages a WebSocket connection to ElevenLabs realtime STT:
- **Protocol**: WebSocket at `wss://api.elevenlabs.io/v1/speech-to-text/...`
- **Language**: Hindi (`language_code="hi"`)
- **Partial transcripts**: Streamed in real-time via `on_partial` callback
- **Final transcript**: Obtained by calling `commit()` (sends empty audio chunk) then `wait_for_final(timeout=3)`
- **Fallback**: If commit fails, `get_best_transcript()` returns the last partial

## tts.py — Text-to-Speech (ElevenLabs WebSocket Streaming)

`ElevenLabsTTS` manages a **persistent WebSocket connection** for low-latency TTS:
- **Protocol**: WebSocket at `wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input`
- **Model**: `eleven_multilingual_v2`
- **Flow per utterance**: BOS (begin-of-stream) → text chunk with `flush=true` → EOS (end-of-stream, `text=""`)
- **Output**: Yields MP3 audio chunks as they arrive, stopping at `isFinal: true`

### TTS Preprocessing (Critical)

`_preprocess_for_tts(text)` runs BEFORE sending text to ElevenLabs. Two-layer fix:

1. **Currency conversion**: `_convert_currency_to_hindi(text)` — regex catches `Rs.85,000` patterns and converts to Hindi number words using Indian number system (लाख/करोड़)
2. **Word replacement**: `_TTS_REPLACEMENTS` dict maps acronyms to Devanagari phonetics:
   - `CIBIL` → `सिबिल`, `EMI` → `ई एम आई`, `UPI` → `यू पी आई`
   - `rupees` → `रुपये`, `Rs.` → `रुपये`, `₹` → `रुपये`

### Hindi Number System (`_number_to_hindi`)

Full implementation of Indian number system with unique Hindi words for 1-99:
- Uses लाख (1,00,000) and करोड़ (1,00,00,000) — NOT million/billion
- `_HINDI_NUMBERS` dict maps 1-99 to Devanagari words
- Composes numbers: `85,000` → `पचासी हज़ार`

## normalize.py — Audio Normalization

PCM audio normalization utilities. Used to normalize mic input levels before STT.

## Adding a New Pronunciation Fix

Add to `_TTS_REPLACEMENTS` dict in `tts.py`:
```python
"NEW_WORD": "देवनागरी_pronunciation",
```
For currency patterns, modify the `_CURRENCY_PATTERN` regex in `_convert_currency_to_hindi()`.
