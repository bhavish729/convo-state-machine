from __future__ import annotations

import asyncio
import base64
import json
import logging

import websockets

from tara.config import settings
from tara.voice import get_elevenlabs_base_url

logger = logging.getLogger(__name__)


class RealtimeTranscriber:
    """
    WebSocket-based realtime STT using ElevenLabs Scribe v2.

    Key design: partials are streamed continuously while audio is being sent.
    When the user stops talking, we use the last partial immediately — no need
    to wait for a committed transcript in a real-time voice call.
    """

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.ws = None
        self.transcript = ""
        self._last_partial = ""
        self._committed_event = asyncio.Event()
        self._receiver_task: asyncio.Task | None = None
        self._partial_callback = None

    async def connect(self, on_partial=None):
        """Open WebSocket connection to ElevenLabs realtime STT."""
        self._partial_callback = on_partial
        base = get_elevenlabs_base_url()
        ws_base = base.replace("https://", "wss://")

        audio_fmt = f"pcm_{self.sample_rate}"

        params = (
            f"model_id=scribe_v2_realtime"
            f"&language_code=hi"
            f"&include_language_detection=true"
            f"&audio_format={audio_fmt}"
        )
        url = f"{ws_base}/v1/speech-to-text/realtime?{params}"

        self.ws = await websockets.connect(
            url,
            additional_headers={"xi-api-key": settings.elevenlabs_api_key},
        )

        # ElevenLabs sends session_started as the first message
        raw = await self.ws.recv()
        msg = json.loads(raw)
        logger.info(f"STT session: {msg}")
        if msg.get("message_type") != "session_started":
            logger.warning(f"Unexpected initial STT message: {msg}")

        # Start background receiver
        self._receiver_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self):
        """Background task: read transcript events from ElevenLabs."""
        try:
            async for msg_str in self.ws:
                msg = json.loads(msg_str)
                msg_type = msg.get("message_type")

                if msg_type == "partial_transcript":
                    text = msg.get("text", "")
                    if text:
                        self._last_partial = text
                    if self._partial_callback and text:
                        await self._partial_callback(text)

                elif msg_type in ("committed_transcript", "committed_transcript_with_timestamps"):
                    text = msg.get("text", "")
                    if text:
                        self.transcript += text
                    self._committed_event.set()
                    logger.debug(f"STT committed: {text!r}")

                elif msg_type == "commit_throttled":
                    # ElevenLabs throttles commits if sent too quickly
                    logger.debug("STT commit throttled — using partial")
                    self._committed_event.set()

                elif msg_type in ("error", "auth_error", "quota_exceeded", "rate_limited"):
                    logger.error(f"STT error: {msg}")
                    self._committed_event.set()
                    break

                else:
                    logger.debug(f"STT msg: {msg_type}")

        except websockets.exceptions.ConnectionClosed:
            logger.debug("STT WebSocket closed")
            self._committed_event.set()
        except Exception as e:
            logger.error(f"STT receiver error: {e}")
            self._committed_event.set()

    async def send_audio(self, pcm_bytes: bytes):
        """Forward a PCM audio chunk to ElevenLabs."""
        if not self.ws:
            return
        msg = json.dumps({
            "message_type": "input_audio_chunk",
            "audio_base_64": base64.b64encode(pcm_bytes).decode(),
        })
        await self.ws.send(msg)

    def get_best_transcript(self) -> str:
        """Return the best transcript available right now (no waiting)."""
        return self.transcript.strip() or self._last_partial.strip()

    async def commit(self):
        """
        Signal end of audio via commit flag.

        ElevenLabs Scribe v2 uses commit=true on an input_audio_chunk,
        NOT a separate 'flush' message type.
        """
        if self.ws:
            try:
                await self.ws.send(json.dumps({
                    "message_type": "input_audio_chunk",
                    "audio_base_64": "",
                    "commit": True,
                }))
            except Exception as e:
                logger.debug(f"STT commit send error: {e}")

    # Alias
    async def flush(self):
        await self.commit()

    async def wait_for_final(self, timeout: float = 3) -> str:
        """Wait briefly for committed transcript, fall back to partial."""
        try:
            await asyncio.wait_for(self._committed_event.wait(), timeout)
        except asyncio.TimeoutError:
            logger.warning("STT wait_for_final timed out after %.1fs", timeout)

        if not self.transcript.strip() and self._last_partial.strip():
            logger.info(f"Using partial transcript fallback: {self._last_partial}")
            self.transcript = self._last_partial

        return self.transcript

    async def close(self):
        """Clean up WebSocket and receiver task."""
        if self._receiver_task:
            self._receiver_task.cancel()
            try:
                await self._receiver_task
            except asyncio.CancelledError:
                pass
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                pass
            self.ws = None
