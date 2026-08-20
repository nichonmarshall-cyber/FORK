"""
Where academic sessions live: a dictionary, in this process, until it restarts.

Server-side rather than client-side because the alternative is posting the
whole normalized record back and forth on every request, which makes the
"confirmed" record something the browser can rewrite between confirming it and
using it. Keeping it here means confirmation actually pins a value.

Deliberately not a database. No migrations, no connection pooling, no
deployment story — losing every session on restart is the accepted cost of a
prototype, and it is written down in `QUICKSTART.md` rather than discovered.

Two consequences worth stating, because both would be defects in a real system
and are only acceptable in this one:

  * Multiple workers each get their own store, so a session is only visible to
    the process that created it. Run a single worker.
  * Sessions expire on a timer and on capacity. An audit is an education
    record, and one shouldn't sit in memory for a week because a tab was left
    open.
"""

import secrets
import threading
from datetime import datetime, timedelta, timezone

from .context import SessionAcademicContext

#: How long an idle session survives. Short on purpose: the record contains a
#: full grade history and there is no reason to hold one past the visit.
SESSION_TTL = timedelta(hours=2)

#: Ceiling on concurrent sessions, so a script hitting the upload endpoint
#: can't exhaust memory. The oldest go first when it's reached.
MAX_SESSIONS = 500


class SessionNotFound(KeyError):
    """No live session with that id — unknown, or expired and swept."""


class AcademicSessionStore:
    """Thread-safe in-memory session store.

    FastAPI serves requests from a thread pool, so two requests for the same
    session can genuinely overlap. The lock is not decorative.
    """

    def __init__(self, ttl: timedelta = SESSION_TTL, max_sessions: int = MAX_SESSIONS):
        self._sessions: dict[str, SessionAcademicContext] = {}
        self._lock = threading.Lock()
        self._ttl = ttl
        self._max_sessions = max_sessions

    def create(self) -> SessionAcademicContext:
        with self._lock:
            self._evict_expired()
            self._evict_overflow()
            session_id = secrets.token_urlsafe(16)
            session = SessionAcademicContext(session_id=session_id)
            self._sessions[session_id] = session
            return session

    def get(self, session_id: str) -> SessionAcademicContext:
        with self._lock:
            self._evict_expired()
            session = self._sessions.get(session_id)
            if session is None:
                raise SessionNotFound(session_id)
            return session

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def count(self) -> int:
        with self._lock:
            self._evict_expired()
            return len(self._sessions)

    def clear(self) -> None:
        """Drop everything. Used by tests; harmless in production."""
        with self._lock:
            self._sessions.clear()

    def _evict_expired(self) -> None:
        cutoff = datetime.now(timezone.utc) - self._ttl
        for session_id in [
            sid for sid, s in self._sessions.items() if s.updated_at < cutoff
        ]:
            del self._sessions[session_id]

    def _evict_overflow(self) -> None:
        while len(self._sessions) >= self._max_sessions:
            oldest = min(self._sessions.items(), key=lambda item: item[1].updated_at)
            del self._sessions[oldest[0]]


#: Process-wide store. One per process — see the note on multiple workers.
academic_sessions = AcademicSessionStore()