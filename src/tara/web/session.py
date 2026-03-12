from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field

from langgraph.graph.state import CompiledStateGraph

from tara.agents import build_graph, resolve_agent_type
from tara.data.mock_borrowers import BORROWER_DB
from tara.voice.tts import RealtimeTTS

logger = logging.getLogger(__name__)


@dataclass
class ConversationSession:
    session_id: str
    borrower_id: str
    agent_type: str  # "pre_due", "bucket_x", "npa"
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

    def create_session(
        self,
        borrower_id: str = "BRW-001",
        agent_type: str | None = None,
    ) -> ConversationSession:
        """Create a new session with the appropriate agent graph.

        If agent_type is not specified, auto-resolves from borrower's DPD.
        """
        self._cleanup_stale()

        # Auto-resolve agent type from DPD if not specified
        if not agent_type:
            profile = BORROWER_DB.get(borrower_id, BORROWER_DB.get("BRW-001", {}))
            dpd = profile.get("days_past_due", 90)
            agent_type = resolve_agent_type(dpd)

        session_id = str(uuid.uuid4())
        graph = build_graph(agent_type)
        session = ConversationSession(
            session_id=session_id,
            borrower_id=borrower_id,
            agent_type=agent_type,
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
