from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from langchain_core.messages import HumanMessage
from pathlib import Path
from pydantic import BaseModel

from tara.agents import VALID_AGENT_TYPES
from tara.voice.stt import RealtimeTranscriber
from tara.web.session import session_manager

logger = logging.getLogger(__name__)

router = APIRouter()


# Agent-type → aggression level function mapping
_AGGRESSION_FN_CACHE: dict = {}


def _get_aggression_fn(agent_type: str):
    """Lazy-load the correct aggression level function for the agent type."""
    if agent_type not in _AGGRESSION_FN_CACHE:
        if agent_type == "pre_due":
            from tara.agents.pre_due.prompts import _get_aggression_level
        elif agent_type == "bucket_x":
            from tara.agents.bucket_x.prompts import _get_aggression_level
        else:
            from tara.agents.npa.prompts import _get_aggression_level
        _AGGRESSION_FN_CACHE[agent_type] = _get_aggression_level
    return _AGGRESSION_FN_CACHE[agent_type]


def _serialize_state(result: dict, agent_type: str = "npa") -> dict:
    """
    Extract serializable state from a graph invocation result for the UI.
    Strips messages (large) and non-JSON-safe objects.
    """
    routing = result.get("routing_decision", {})
    profile = result.get("borrower_profile", {})
    negotiation = result.get("negotiation", {})

    # Calculate aggression level using the correct agent's function
    aggression_fn = _get_aggression_fn(agent_type)
    sentiment = str(result.get("current_sentiment", "neutral"))
    turn_count = result.get("turn_count", 0)
    dpd = profile.get("days_past_due", 0)
    aggression = aggression_fn(sentiment, turn_count, dpd)

    return {
        "agent_type": agent_type,
        "conversation_phase": str(result.get("conversation_phase", "init")),
        "turn_count": result.get("turn_count", 0),
        "identity_verified": result.get("identity_verified", False),
        "verification_attempts": result.get("verification_attempts", 0),
        "current_sentiment": str(result.get("current_sentiment", "neutral")),
        "aggression_level": aggression["level"],
        "aggression_desc": aggression["description"],
        "current_objection": str(result.get("current_objection", "none")),
        "objections_raised": result.get("objections_raised", []),
        "is_terminal": result.get("is_terminal", False),
        "escalation_reason": result.get("escalation_reason", ""),
        "routing_decision": {
            "next_node": routing.get("next_node", ""),
            "reasoning": routing.get("reasoning", ""),
            "response_to_borrower": routing.get("response_to_borrower", ""),
        },
        "borrower_profile": {
            "full_name": profile.get("full_name", "Unknown"),
            "borrower_id": profile.get("borrower_id", ""),
            "debt_amount": profile.get("debt_amount", 0),
            "debt_type": profile.get("debt_type", ""),
            "days_past_due": profile.get("days_past_due", 0),
            "risk_tier": profile.get("risk_tier", ""),
            "original_creditor": profile.get("original_creditor", ""),
            "account_number": profile.get("account_number", ""),
        },
        "negotiation": {
            "offers_presented": len(negotiation.get("offers_presented", [])),
            "concessions_made": negotiation.get("concessions_made", 0),
            "agreed_option": negotiation.get("agreed_option"),
        },
        "tactical_memory": result.get("tactical_memory", {}),
        "call_progress": result.get("call_progress", {}),
        "message_count": len(result.get("messages", [])),
    }


@router.get("/")
async def index():
    html_path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(content=html_path.read_text())


@router.get("/api/graph")
async def get_graph(agent_type: str = "npa"):
    """Render a LangGraph as a PNG image for visualization."""
    from tara.agents import build_graph

    graph = build_graph(agent_type)
    try:
        png_bytes = graph.get_graph().draw_mermaid_png()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        mermaid = graph.get_graph().draw_mermaid()
        return HTMLResponse(
            content=f"""<html><body style="background:#0a0a0a;color:#e0e0e0;font-family:monospace;padding:24px">
            <h2>Tara LangGraph — {agent_type}</h2>
            <pre>{mermaid}</pre>
            <p style="color:#888">Install pygraphviz or use <a href="https://mermaid.live" style="color:#7c8cf5">mermaid.live</a> to render</p>
            </body></html>""",
            status_code=200,
        )


@router.post("/api/session")
async def create_session(
    borrower_id: str = "BRW-001",
    agent_type: str | None = None,
):
    """Create a new conversation session.

    agent_type: "pre_due" | "bucket_x" | "npa" (auto-detected from DPD if omitted)
    """
    # Validate agent_type if provided
    if agent_type and agent_type not in VALID_AGENT_TYPES:
        return {
            "error": f"Invalid agent_type '{agent_type}'. Valid: {', '.join(VALID_AGENT_TYPES)}"
        }

    session = session_manager.create_session(borrower_id, agent_type=agent_type)

    # Run initial graph invocation (load_context → central_intelligence)
    config = {"configurable": {"thread_id": session.thread_id}}
    initial_state = {
        "messages": [],
        "borrower_profile": {"borrower_id": borrower_id},
        "agent_type": session.agent_type,
    }
    result = await asyncio.wait_for(
        session.graph.ainvoke(initial_state, config=config),
        timeout=30.0,
    )

    # Extract Tara's opening message
    ai_messages = [m for m in result.get("messages", []) if m.type == "ai"]
    opening = ai_messages[-1].content if ai_messages else "Hello, this is Tara."

    # Store opening message so WebSocket can stream TTS on connect
    session.opening_message = opening

    return {
        "session_id": session.session_id,
        "agent_type": session.agent_type,
        "opening_message": opening,
        "phase": result.get("conversation_phase", "init"),
        "state": _serialize_state(result, agent_type=session.agent_type),
    }


class NextCallRequest(BaseModel):
    borrower_id: str = "BRW-001"
    agent_type: str | None = None
    previous_calls: list[dict] = []


@router.post("/api/session/next-call")
async def create_next_call(req: NextCallRequest):
    """Create a new session for a follow-up call (2nd/3rd connect).

    Carries over negotiation_history from previous calls so the agent
    has context about what happened in earlier conversations.
    """
    if req.agent_type and req.agent_type not in VALID_AGENT_TYPES:
        return {
            "error": f"Invalid agent_type '{req.agent_type}'. Valid: {', '.join(VALID_AGENT_TYPES)}"
        }

    session = session_manager.create_session(req.borrower_id, agent_type=req.agent_type)

    # Build initial state with negotiation history from previous calls
    config = {"configurable": {"thread_id": session.thread_id}}

    initial_state = {
        "messages": [],
        "borrower_profile": {"borrower_id": req.borrower_id},
        "agent_type": session.agent_type,
        "negotiation_history": req.previous_calls,
    }

    result = await asyncio.wait_for(
        session.graph.ainvoke(initial_state, config=config),
        timeout=30.0,
    )

    ai_messages = [m for m in result.get("messages", []) if m.type == "ai"]
    opening = ai_messages[-1].content if ai_messages else "Hello, this is Tara."
    session.opening_message = opening

    return {
        "session_id": session.session_id,
        "agent_type": session.agent_type,
        "opening_message": opening,
        "phase": result.get("conversation_phase", "init"),
        "state": _serialize_state(result, agent_type=session.agent_type),
    }


# ═══════════════════════════════════════════════════════
#  TTS background streaming (cancellable)
# ═══════════════════════════════════════════════════════


async def _stream_tts(
    websocket: WebSocket,
    session,
    text: str,
    is_terminal: bool,
    phase: str,
):
    """Background task: stream TTS audio over WebSocket.

    Designed to be run as ``asyncio.create_task()`` so the main message
    loop stays free to handle barge-in (``start_recording``).

    On cancellation (barge-in), sends ``audio_end`` so frontend doesn't hang,
    then closes the TTS connection for a fresh start next turn.
    """
    if not text:
        try:
            await websocket.send_json({"type": "audio_end"})
            if is_terminal:
                await websocket.send_json({"type": "terminal", "phase": phase})
        except Exception:
            pass
        return

    await websocket.send_json({"type": "status", "status": "speaking"})
    t0 = time.monotonic()
    tts_fb = None
    interrupted = False

    try:
        async for chunk in session.tts.synthesize(text):
            if tts_fb is None:
                tts_fb = int((time.monotonic() - t0) * 1000)
            await websocket.send_bytes(chunk)
    except asyncio.CancelledError:
        logger.info("[TTS] Interrupted by barge-in")
        interrupted = True
        # Close TTS connection so next turn gets a fresh one
        await session.tts.close()
    except Exception as e:
        logger.error(f"[TTS] Error: {e}")

    tts_total = int((time.monotonic() - t0) * 1000)
    if not interrupted:
        logger.info(f"[TTS] Done: first_byte={tts_fb}ms total={tts_total}ms")

    # Always send audio_end so frontend doesn't hang
    try:
        await websocket.send_json({
            "type": "audio_end",
            "latency": {
                "tts_first_byte_ms": tts_fb or 0,
                "tts_total_ms": tts_total,
            },
            "interrupted": interrupted,
        })
        if is_terminal and not interrupted:
            await websocket.send_json({"type": "terminal", "phase": phase})
    except Exception:
        pass


# ═══════════════════════════════════════════════════════
#  WebSocket endpoint
# ═══════════════════════════════════════════════════════


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    config = {"configurable": {"thread_id": session.thread_id}}
    transcriber: RealtimeTranscriber | None = None
    tts_task: asyncio.Task | None = None

    async def _cancel_tts():
        """Cancel any ongoing TTS background task."""
        nonlocal tts_task
        if tts_task and not tts_task.done():
            logger.info("[BARGE-IN] Cancelling TTS task")
            tts_task.cancel()
            try:
                await tts_task
            except Exception:
                pass
        tts_task = None

    # Connect persistent TTS WebSocket for this session
    try:
        await session.tts.connect()
    except Exception as e:
        logger.error(f"TTS WebSocket connect failed: {e}")

    # Stream opening TTS as a background task (non-blocking).
    # The main loop starts immediately so barge-in during the
    # opening message is handled correctly.
    if session.opening_message:
        logger.info(f"[OPENING] Streaming opening TTS: '{session.opening_message[:60]}'")
        tts_task = asyncio.create_task(
            _stream_tts(websocket, session, session.opening_message, False, "")
        )
        session.opening_message = ""

    try:
        while True:
            message = await websocket.receive()

            if "text" in message and message["text"]:
                data = json.loads(message["text"])
                msg_type = data.get("type", "")

                if msg_type == "barge_in":
                    # User interrupted Tara — cancel TTS immediately
                    await _cancel_tts()

                elif msg_type == "start_recording":
                    # Cancel any ongoing TTS before opening STT
                    await _cancel_tts()

                    # Open realtime STT session
                    sample_rate = data.get("sample_rate", 16000)
                    transcriber = RealtimeTranscriber(sample_rate=sample_rate)

                    async def on_partial(text):
                        await websocket.send_json({
                            "type": "partial_transcript",
                            "text": text,
                        })

                    try:
                        await transcriber.connect(on_partial=on_partial)
                        await websocket.send_json({"type": "status", "status": "listening"})
                    except Exception as e:
                        logger.error(f"STT connect error: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "error": f"STT connection failed: {e}",
                        })
                        transcriber = None

                elif msg_type == "stop_recording":
                    logger.info("[STT] stop_recording received")
                    if not transcriber:
                        logger.warning("[STT] No transcriber active, sending audio_end")
                        await websocket.send_json({"type": "audio_end"})
                        continue

                    t_stt_start = time.monotonic()

                    # Eager transcript: grab the best partial immediately
                    # instead of blocking up to 3s for a committed transcript.
                    # Scribe v2 partials are highly accurate by the time
                    # the user stops speaking.
                    user_text = transcriber.get_best_transcript()
                    logger.info(f"[STT] Eager transcript: '{user_text}'")

                    # Background cleanup: commit + close STT without blocking
                    # the pipeline. Saves ~50-200ms vs sequential await.
                    _stt_ref = transcriber
                    transcriber = None

                    async def _cleanup_stt(t):
                        try:
                            await t.commit()
                        except Exception:
                            pass
                        try:
                            await t.close()
                        except Exception:
                            pass

                    asyncio.create_task(_cleanup_stt(_stt_ref))

                    stt_ms = int((time.monotonic() - t_stt_start) * 1000)

                    if not user_text.strip():
                        await websocket.send_json({
                            "type": "status",
                            "status": "no_speech",
                            "message": "Kuch sunai nahi diya, please phir se boliye",
                        })
                        await websocket.send_json({"type": "audio_end"})
                        continue

                    await websocket.send_json({
                        "type": "transcript",
                        "speaker": "user",
                        "text": user_text,
                        "latency": {"stt_ms": stt_ms},
                    })

                    try:
                        tts_info = await _process_user_input(
                            websocket, session, config, user_text
                        )
                        if tts_info:
                            text, terminal, phase = tts_info
                            tts_task = asyncio.create_task(
                                _stream_tts(
                                    websocket, session, text, terminal, str(phase)
                                )
                            )
                    except Exception as e:
                        logger.error(f"Process error: {e}", exc_info=True)
                        await websocket.send_json({"type": "error", "error": str(e)})
                        await websocket.send_json({"type": "audio_end"})

                elif "message" in data and data["message"]:
                    user_text = data["message"]
                    # Cancel TTS if user sends text while Tara is speaking
                    await _cancel_tts()
                    try:
                        tts_info = await _process_user_input(
                            websocket, session, config, user_text
                        )
                        if tts_info:
                            text, terminal, phase = tts_info
                            tts_task = asyncio.create_task(
                                _stream_tts(
                                    websocket, session, text, terminal, str(phase)
                                )
                            )
                    except Exception as e:
                        logger.error(f"Process error: {e}", exc_info=True)
                        await websocket.send_json({"type": "error", "error": str(e)})
                        await websocket.send_json({"type": "audio_end"})

            elif "bytes" in message and message["bytes"]:
                if transcriber:
                    try:
                        await transcriber.send_audio(message["bytes"])
                    except Exception as e:
                        logger.error(f"STT send error: {e}")

    except WebSocketDisconnect:
        logger.info(f"Session {session_id} disconnected")
    except Exception as e:
        logger.error(f"WebSocket error in session {session_id}: {e}")
    finally:
        await _cancel_tts()
        if transcriber:
            await transcriber.close()
        await session.tts.close()
        session_manager.remove_session(session_id)


async def _process_user_input(
    websocket: WebSocket, session, config: dict, user_text: str
) -> tuple[str, bool, str] | None:
    """Feed user text into the LangGraph and send transcript + state.

    Returns ``(response_text, is_terminal, phase)`` for TTS streaming,
    or ``None`` if no TTS is needed (timeout / empty response).
    TTS is streamed by the caller as a background task.
    """
    logger.info(f"[PIPELINE] _process_user_input start: '{user_text[:50]}'")
    await websocket.send_json({"type": "status", "status": "thinking"})

    # Pre-warm TTS WebSocket concurrently with LLM processing.
    # The handshake (~100-200ms) runs in parallel with the LLM call,
    # so synthesize() can send text immediately when the LLM returns.
    logger.info("[PIPELINE] Starting TTS pre-connect task")
    tts_preconnect = asyncio.create_task(session.tts.pre_connect())

    t_llm_start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            session.graph.ainvoke(
                {"messages": [HumanMessage(content=user_text)]},
                config=config,
            ),
            timeout=30.0,
        )
    except asyncio.TimeoutError:
        tts_preconnect.cancel()
        await websocket.send_json({
            "type": "error",
            "error": "Response took too long. Please try again.",
        })
        await websocket.send_json({"type": "audio_end"})
        return None
    llm_ms = int((time.monotonic() - t_llm_start) * 1000)
    logger.info(f"[PIPELINE] LLM done in {llm_ms}ms")

    ai_messages = [m for m in result.get("messages", []) if m.type == "ai"]
    response_text = ai_messages[-1].content if ai_messages else ""
    is_terminal = result.get("is_terminal", False)
    phase = result.get("conversation_phase", "unknown")
    logger.info(f"[PIPELINE] Response: '{response_text[:80]}...' terminal={is_terminal} phase={phase}")

    await websocket.send_json({
        "type": "transcript",
        "speaker": "tara",
        "text": response_text,
        "phase": phase,
        "is_terminal": is_terminal,
        "latency": {"llm_ms": llm_ms},
    })

    # Send full state snapshot for the debug panel
    await websocket.send_json({
        "type": "state_update",
        "state": _serialize_state(result, agent_type=session.agent_type),
    })

    if not response_text:
        tts_preconnect.cancel()
        await session.tts.close()
        await websocket.send_json({"type": "audio_end"})
        return None

    # Ensure pre-connect finished (should be done — LLM takes much longer)
    logger.info("[PIPELINE] Awaiting TTS pre-connect")
    try:
        await tts_preconnect
    except Exception as e:
        logger.warning(f"[PIPELINE] TTS pre-connect error (will retry): {e}")
    logger.info(f"[PIPELINE] TTS pre-connect done, ws={session.tts.ws is not None}")

    return (response_text, is_terminal, str(phase))
