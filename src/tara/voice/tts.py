from __future__ import annotations

import asyncio
import base64
import json
import logging
from collections.abc import AsyncIterator

import websockets

from tara.config import settings
from tara.voice import get_elevenlabs_base_url

logger = logging.getLogger(__name__)

# ── TTS text preprocessing ──
# Replace words that ElevenLabs mispronounces with phonetic Devanagari equivalents.
# The multilingual_v2 model handles Devanagari phonemes much better than Roman acronyms
# when the surrounding text is in Devanagari/Hinglish.
_TTS_REPLACEMENTS = {
    "CIBIL": "सिबिल",
    "cibil": "सिबिल",
    "Cibil": "सिबिल",
    "EMI": "ई एम आई",
    "emi": "ई एम आई",
    "UPI": "यू पी आई",
    "upi": "यू पी आई",
    "NEFT": "नेफ्ट",
    "neft": "नेफ्ट",
    "NACH": "नाच",
    "nach": "नाच",
    "NPA": "एन पी ए",
    "DPD": "डी पी डी",
    "PAN": "पैन",
    "OTP": "ओ टी पी",
    # Currency — LLM sometimes slips in English "rupees" or symbols
    "rupees": "रुपये",
    "Rupees": "रुपये",
    "Rs.": "रुपये",
    "Rs ": "रुपये ",
    "₹": "रुपये",
}

# Regex patterns for currency amounts that slip through (e.g., "Rs.85,000")
import re
_CURRENCY_PATTERN = re.compile(r'(?:Rs\.?|₹)\s*(\d[\d,]*(?:\.\d{2})?)')
_DIGIT_PATTERN = re.compile(r'(\d[\d,]+)')

# Hindi number words for natural speech
_HINDI_NUMBERS = {
    1: "एक", 2: "दो", 3: "तीन", 4: "चार", 5: "पाँच",
    6: "छह", 7: "सात", 8: "आठ", 9: "नौ", 10: "दस",
    11: "ग्यारह", 12: "बारह", 13: "तेरह", 14: "चौदह", 15: "पंद्रह",
    16: "सोलह", 17: "सत्रह", 18: "अट्ठारह", 19: "उन्नीस", 20: "बीस",
    21: "इक्कीस", 22: "बाईस", 23: "तेईस", 24: "चौबीस", 25: "पच्चीस",
    26: "छब्बीस", 27: "सत्ताईस", 28: "अट्ठाईस", 29: "उनतीस", 30: "तीस",
    31: "इकतीस", 32: "बत्तीस", 33: "तैंतीस", 34: "चौंतीस", 35: "पैंतीस",
    36: "छत्तीस", 37: "सैंतीस", 38: "अड़तीस", 39: "उनतालीस", 40: "चालीस",
    41: "इकतालीस", 42: "बयालीस", 43: "तैंतालीस", 44: "चवालीस", 45: "पैंतालीस",
    46: "छियालीस", 47: "सैंतालीस", 48: "अड़तालीस", 49: "उनचास", 50: "पचास",
    51: "इक्यावन", 52: "बावन", 53: "तिरपन", 54: "चौवन", 55: "पचपन",
    56: "छप्पन", 57: "सत्तावन", 58: "अट्ठावन", 59: "उनसठ", 60: "साठ",
    61: "इकसठ", 62: "बासठ", 63: "तिरसठ", 64: "चौंसठ", 65: "पैंसठ",
    66: "छियासठ", 67: "सड़सठ", 68: "अड़सठ", 69: "उनहत्तर", 70: "सत्तर",
    71: "इकहत्तर", 72: "बहत्तर", 73: "तिहत्तर", 74: "चौहत्तर", 75: "पचहत्तर",
    76: "छिहत्तर", 77: "सतहत्तर", 78: "अठहत्तर", 79: "उनासी", 80: "अस्सी",
    81: "इक्यासी", 82: "बयासी", 83: "तिरासी", 84: "चौरासी", 85: "पचासी",
    86: "छियासी", 87: "सतासी", 88: "अट्ठासी", 89: "नवासी", 90: "नब्बे",
    91: "इक्यानवे", 92: "बानवे", 93: "तिरानवे", 94: "चौरानवे", 95: "पचानवे",
    96: "छियानवे", 97: "सत्तानवे", 98: "अट्ठानवे", 99: "निन्यानवे",
}


def _number_to_hindi(n: int) -> str:
    """Convert an integer to spoken Hindi words (Indian number system)."""
    if n == 0:
        return "शून्य"
    if n < 0:
        return "माइनस " + _number_to_hindi(-n)

    parts = []

    if n >= 1_00_00_000:  # crore (1,00,00,000)
        crores = n // 1_00_00_000
        parts.append(_number_to_hindi(crores) + " करोड़")
        n %= 1_00_00_000

    if n >= 1_00_000:  # lakh
        lakhs = n // 1_00_000
        parts.append(_number_to_hindi(lakhs) + " लाख")
        n %= 1_00_000

    if n >= 1_000:  # hazaar
        thousands = n // 1_000
        parts.append(_number_to_hindi(thousands) + " हज़ार")
        n %= 1_000

    if n >= 100:
        hundreds = n // 100
        parts.append(_number_to_hindi(hundreds) + " सौ")
        n %= 100

    if n > 0:
        if n in _HINDI_NUMBERS:
            parts.append(_HINDI_NUMBERS[n])
        else:
            parts.append(str(n))

    return " ".join(parts)


def _convert_currency_to_hindi(text: str) -> str:
    """Convert Rs.85,000 or ₹85000 patterns to spoken Hindi like 'पचासी हज़ार रुपये'."""
    def replace_currency(match):
        num_str = match.group(1).replace(",", "").split(".")[0]
        try:
            num = int(num_str)
            return _number_to_hindi(num) + " रुपये"
        except ValueError:
            return match.group(0)

    return _CURRENCY_PATTERN.sub(replace_currency, text)


def _preprocess_for_tts(text: str) -> str:
    """Replace acronyms/words that TTS mispronounces with phonetic equivalents."""
    # First convert currency patterns like Rs.85,000 → पचासी हज़ार रुपये
    text = _convert_currency_to_hindi(text)
    # Then do simple word replacements
    for word, replacement in _TTS_REPLACEMENTS.items():
        text = text.replace(word, replacement)
    return text


class RealtimeTTS:
    """
    WebSocket-based streaming TTS using ElevenLabs input streaming API.

    Each call to synthesize() opens a fresh connection, sends BOS + text + EOS,
    reads audio chunks until isFinal/connection close, then cleans up.

    This avoids the 20s inactivity timeout issue and guarantees clean state
    per utterance, while still being faster than HTTP TTS because the
    WebSocket handshake (~150ms) is much cheaper than HTTP streaming setup (~500ms+).
    """

    def __init__(self):
        self.ws = None

    async def _open_stream(self) -> None:
        """Open a WebSocket connection and send BOS."""
        base = get_elevenlabs_base_url()
        ws_base = base.replace("https://", "wss://")
        voice_id = settings.elevenlabs_voice_id

        url = (
            f"{ws_base}/v1/text-to-speech/{voice_id}/stream-input"
            f"?model_id=eleven_multilingual_v2"
            f"&output_format=mp3_44100_128"
        )

        self.ws = await websockets.connect(url)

        # BOS (Beginning of Stream): voice config + API key
        bos = {
            "text": " ",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.8,
                "use_speaker_boost": False,
            },
            "generation_config": {
                "chunk_length_schedule": [50],
            },
            "xi_api_key": settings.elevenlabs_api_key,
        }
        await self.ws.send(json.dumps(bos))

    async def synthesize(self, text: str) -> AsyncIterator[bytes]:
        """
        Open stream → send text + EOS → yield audio → connection closes.

        ElevenLabs sends isFinal:true only after EOS is sent, so we send:
          1. BOS (init)
          2. Text + flush
          3. EOS {"text": ""} — triggers isFinal:true

        Audio chunks arrive between steps 2 and 3's response.
        """
        await self._open_stream()

        try:
            # Preprocess text for better pronunciation
            processed = _preprocess_for_tts(text)

            # Send text with flush to force immediate generation
            await self.ws.send(json.dumps({
                "text": processed + " ",
                "flush": True,
            }))

            # EOS — tells ElevenLabs we're done, which triggers isFinal:true
            await self.ws.send(json.dumps({"text": ""}))

            # Read audio chunks until isFinal or connection close
            async for raw in self.ws:
                msg = json.loads(raw)

                audio_b64 = msg.get("audio")
                if audio_b64:
                    chunk = base64.b64decode(audio_b64)
                    if chunk:
                        yield chunk

                if msg.get("isFinal"):
                    break

        except websockets.exceptions.ConnectionClosed:
            logger.debug("TTS WebSocket closed (expected after EOS)")
        finally:
            if self.ws:
                try:
                    await self.ws.close()
                except Exception:
                    pass
                self.ws = None

    async def connect(self):
        """No-op for compatibility. Connection is opened per-synthesize."""
        pass

    async def close(self):
        """Clean up any open WebSocket."""
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None


# Standalone function for one-off TTS
async def stream_tts(text: str) -> AsyncIterator[bytes]:
    """One-shot TTS via WebSocket."""
    tts = RealtimeTTS()
    try:
        async for chunk in tts.synthesize(text):
            yield chunk
    finally:
        await tts.close()
