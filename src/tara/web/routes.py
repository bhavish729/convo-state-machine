from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from langchain_core.messages import HumanMessage
from pathlib import Path

from tara.voice.stt import RealtimeTranscriber
from tara.web.session import session_manager

logger = logging.getLogger(__name__)

router = APIRouter()


def _serialize_state(result: dict) -> dict:
    """
    Extract serializable state from a graph invocation result for the UI.
    Strips messages (large) and non-JSON-safe objects.
    """
    routing = result.get("routing_decision", {})
    profile = result.get("borrower_profile", {})
    negotiation = result.get("negotiation", {})

    # Calculate aggression level for display
    from tara.llm.prompts import _get_aggression_level
    sentiment = str(result.get("current_sentiment", "neutral"))
    turn_count = result.get("turn_count", 0)
    dpd = result.get("borrower_profile", {}).get("days_past_due", 0)
    aggression = _get_aggression_level(sentiment, turn_count, dpd)

    return {
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
async def get_graph():
    """Render the LangGraph as a PNG image for visualization."""
    from tara.graph.builder import build_graph

    graph = build_graph()
    try:
        png_bytes = graph.get_graph().draw_mermaid_png()
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        # Fallback: return Mermaid text if PNG rendering fails
        mermaid = graph.get_graph().draw_mermaid()
        return HTMLResponse(
            content=f"""<html><body style="background:#0a0a0a;color:#e0e0e0;font-family:monospace;padding:24px">
            <h2>Tara LangGraph</h2>
            <pre>{mermaid}</pre>
            <p style="color:#888">Install pygraphviz or use <a href="https://mermaid.live" style="color:#7c8cf5">mermaid.live</a> to render</p>
            </body></html>""",
            status_code=200,
        )


@router.post("/api/session")
async def create_session(borrower_id: str = "BRW-001"):
    session = session_manager.create_session(borrower_id)

    # Run initial graph invocation (load_context -> central_intelligence)
    config = {"configurable": {"thread_id": session.thread_id}}
    initial_state = {
        "messages": [],
        "borrower_profile": {"borrower_id": borrower_id},
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
        "opening_message": opening,
        "phase": result.get("conversation_phase", "init"),
        "state": _serialize_state(result),
    }


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    session = session_manager.get_session(session_id)
    if not session:
        await websocket.close(code=4004, reason="Session not found")
        return

    await websocket.accept()
    config = {"configurable": {"thread_id": session.thread_id}}
    transcriber: RealtimeTranscriber | None = None

    # Connect persistent TTS WebSocket for this session
    try:
        await session.tts.connect()
    except Exception as e:
        logger.error(f"TTS WebSocket connect failed: {e}")

    # Stream TTS for the opening message using persistent connection
    if session.opening_message:
        try:
            await websocket.send_json({"type": "status", "status": "speaking"})
            t0 = time.monotonic()
            tts_fb = None
            async for audio_chunk in session.tts.synthesize(session.opening_message):
                if tts_fb is None:
                    tts_fb = int((time.monotonic() - t0) * 1000)
                await websocket.send_bytes(audio_chunk)
            tts_total = int((time.monotonic() - t0) * 1000)
            await websocket.send_json({
                "type": "audio_end",
                "latency": {"tts_first_byte_ms": tts_fb or 0, "tts_total_ms": tts_total},
            })
        except Exception as e:
            logger.error(f"Opening TTS error: {e}")
            # ALWAYS send audio_end so frontend doesn't hang
            await websocket.send_json({"type": "audio_end"})
        finally:
            session.opening_message = ""

    try:
        while True:
            message = await websocket.receive()

            if "text" in message and message["text"]:
                data = json.loads(message["text"])
                msg_type = data.get("type", "")

                if msg_type == "start_recording":
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
                    if not transcriber:
                        await websocket.send_json({"type": "audio_end"})
                        continue

                    t_stt_start = time.monotonic()

                    # Fast path: grab the last partial transcript immediately.
                    # Partials are already streaming in real-time during recording,
                    # so by the time the user stops, we have the text.
                    try:
                        # Try commit for a proper committed_transcript (short wait)
                        await transcriber.commit()
                        user_text = await transcriber.wait_for_final(timeout=3)
                    except Exception as e:
                        logger.error(f"STT finalize error: {e}")
                        # Fall back to whatever partial we have
                        user_text = transcriber.get_best_transcript()
                    finally:
                        await transcriber.close()
                        transcriber = None

                    stt_ms = int((time.monotonic() - t_stt_start) * 1000)

                    if not user_text.strip():
                        await websocket.send_json({
                            "type": "status",
                            "status": "no_speech",
                            "message": "Kuch sunai nahi diya, please phir se boliye",
                        })
                        await websocket.send_json({"type": "audio_end"})
                        continue

                    # Send final transcript with STT latency
                    await websocket.send_json({
                        "type": "transcript",
                        "speaker": "user",
                        "text": user_text,
                        "latency": {"stt_ms": stt_ms},
                    })

                    # Process through LangGraph (with safety net)
                    try:
                        await _process_user_input(websocket, session, config, user_text)
                    except Exception as e:
                        logger.error(f"Process error: {e}", exc_info=True)
                        await websocket.send_json({"type": "error", "error": str(e)})
                        await websocket.send_json({"type": "audio_end"})

                elif "message" in data and data["message"]:
                    # Text input fallback
                    user_text = data["message"]
                    try:
                        await _process_user_input(websocket, session, config, user_text)
                    except Exception as e:
                        logger.error(f"Process error: {e}", exc_info=True)
                        await websocket.send_json({"type": "error", "error": str(e)})
                        await websocket.send_json({"type": "audio_end"})

            elif "bytes" in message and message["bytes"]:
                # Binary frame: PCM audio chunk — forward to ElevenLabs STT
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
        if transcriber:
            await transcriber.close()
        # Close persistent TTS WebSocket
        await session.tts.close()
        session_manager.remove_session(session_id)


async def _process_user_input(
    websocket: WebSocket, session, config: dict, user_text: str
):
    """Feed user text into the LangGraph and send response + TTS back."""
    await websocket.send_json({"type": "status", "status": "thinking"})

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
        await websocket.send_json({
            "type": "error",
            "error": "Response took too long. Please try again.",
        })
        await websocket.send_json({"type": "audio_end"})
        return
    llm_ms = int((time.monotonic() - t_llm_start) * 1000)

    # Extract the latest AI response
    ai_messages = [m for m in result.get("messages", []) if m.type == "ai"]
    response_text = ai_messages[-1].content if ai_messages else ""
    is_terminal = result.get("is_terminal", False)
    phase = result.get("conversation_phase", "unknown")

    # Send AI transcript with LLM latency
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
        "state": _serialize_state(result),
    })

    # Stream TTS audio via persistent WebSocket connection
    if response_text:
        await websocket.send_json({"type": "status", "status": "speaking"})
        t_tts_start = time.monotonic()
        tts_first_byte = None
        try:
            async for audio_chunk in session.tts.synthesize(response_text):
                if tts_first_byte is None:
                    tts_first_byte = int((time.monotonic() - t_tts_start) * 1000)
                await websocket.send_bytes(audio_chunk)
            tts_total_ms = int((time.monotonic() - t_tts_start) * 1000)
            await websocket.send_json({
                "type": "audio_end",
                "latency": {
                    "tts_first_byte_ms": tts_first_byte or 0,
                    "tts_total_ms": tts_total_ms,
                },
            })
        except Exception as e:
            logger.error(f"TTS error: {e}")
            await websocket.send_json({
                "type": "error",
                "error": f"TTS failed: {e}",
            })
            await websocket.send_json({"type": "audio_end"})
    else:
        await websocket.send_json({"type": "audio_end"})

    if is_terminal:
        await websocket.send_json({"type": "terminal", "phase": phase})
        # Do NOT close the WebSocket here — let the client finish playing
        # TTS audio first, then close from its side after a grace period.
