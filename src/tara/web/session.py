from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from langgraph.graph.state import CompiledStateGraph

from tara.graph.builder import build_graph
from tara.voice.tts import RealtimeTTS

logger = logging.getLogger(__name__)


@dataclass
class ConversationSession:
    session_id: str
    borrower_id: str
    graph: CompiledStateGraph
    thread_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    opening_message: str = ""  # Stored so WebSocket can stream TTS on connect
    tts: RealtimeTTS = field(default_factory=RealtimeTTS)  # Persistent TTS WebSocket
    created_at: float = field(default_factory=time.time)


class SessionManager:
    """In-memory session store. Replace with Redis/DB for production."""

    SESSION_TTL = 3600  # 1 hour

    def __init__(self) -> None:
        self._sessions: dict[str, ConversationSession] = {}

    def create_session(self, borrower_id: str = "BRW-001") -> ConversationSession:
        # Cleanup stale sessions on each new session creation
        self._cleanup_stale()

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

    def _cleanup_stale(self) -> None:
        """Remove sessions older than SESSION_TTL seconds."""
        now = time.time()
        stale = [
            sid
            for sid, s in self._sessions.items()
            if now - s.created_at > self.SESSION_TTL
        ]
        for sid in stale:
            logger.info(f"Cleaning up stale session {sid}")
            del self._sessions[sid]


session_manager = SessionManager()
