from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from langgraph.graph.state import CompiledStateGraph

from tara.graph.builder import build_graph
from tara.voice.tts import RealtimeTTS


@dataclass
class ConversationSession:
    session_id: str
    borrower_id: str
    graph: CompiledStateGraph
    thread_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    opening_message: str = ""  # Stored so WebSocket can stream TTS on connect
    tts: RealtimeTTS = field(default_factory=RealtimeTTS)  # Persistent TTS WebSocket


class SessionManager:
    """In-memory session store. Replace with Redis/DB for production."""

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def create_session(self, borrower_id: str = "BRW-001") -> ConversationSession:
        session_id = str(uuid.uuid4())
        graph = build_graph()
        session = ConversationSession(
            session_id=session_id,
            borrower_id=borrower_id,
            graph=graph,
            thread_id=session_id,
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> ConversationSession | None:
        return self._sessions.get(session_id)

    def remove_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


session_manager = SessionManager()
