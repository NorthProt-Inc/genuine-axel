"""Cross-channel session router.

Maps (user_id, channel_id) to sessions with channel-switch metadata.
"""

import time
import uuid
from dataclasses import dataclass, field

from backend.core.logging import get_logger
from backend.core.session.state_machine import SessionState

_log = get_logger("core.session.router")


@dataclass
class RoutedSession:
    """A resolved session with cross-channel metadata."""

    session_id: str
    user_id: str
    channel_id: str
    state: SessionState = SessionState.ACTIVE
    previous_channel: str | None = None
    last_activity: float = field(default_factory=time.time)


class SessionRouter:
    """Routes (user_id, channel_id) pairs to sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, RoutedSession] = {}
        self._user_channels: dict[str, dict[str, str]] = {}

    def resolve(self, user_id: str, channel_id: str) -> RoutedSession:
        """Resolve or create a session for user+channel pair."""
        key = f"{user_id}:{channel_id}"

        if key in self._user_channels.get(user_id, {}):
            sid = self._user_channels[user_id][key]
            if sid in self._sessions:
                return self._sessions[sid]

        previous = self._find_previous_channel(user_id, channel_id)

        session = RoutedSession(
            session_id=uuid.uuid4().hex[:16],
            user_id=user_id,
            channel_id=channel_id,
            previous_channel=previous,
        )

        self._sessions[session.session_id] = session
        self._user_channels.setdefault(user_id, {})[key] = session.session_id

        _log.debug(
            "session_resolved",
            session=session.session_id[:8],
            user=user_id[:8],
            channel=channel_id,
            prev_channel=previous,
        )
        return session

    def end_session(self, session_id: str) -> None:
        """End a session and remove from routing."""
        session = self._sessions.pop(session_id, None)
        if session:
            key = f"{session.user_id}:{session.channel_id}"
            user_map = self._user_channels.get(session.user_id, {})
            user_map.pop(key, None)

    def update_activity(self, session_id: str) -> None:
        """Update last-activity timestamp."""
        if session_id in self._sessions:
            self._sessions[session_id].last_activity = time.time()

    def get_user_sessions(self, user_id: str) -> list[RoutedSession]:
        """Get all active sessions for a user."""
        return [
            s for s in self._sessions.values()
            if s.user_id == user_id
        ]

    def _find_previous_channel(self, user_id: str, current_channel: str) -> str | None:
        """Find the most recent channel used by this user."""
        user_sessions = self.get_user_sessions(user_id)
        if not user_sessions:
            return None
        other = [s for s in user_sessions if s.channel_id != current_channel]
        if not other:
            return None
        return max(other, key=lambda s: s.last_activity).channel_id
