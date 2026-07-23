"""Bounded in-memory session storage for the RUNE web adapter."""

from copy import deepcopy
from dataclasses import dataclass, field
import json
import secrets
import threading
import time


class SessionNotFoundError(LookupError):
    """The supplied opaque token does not name a live session."""


class SessionCapacityError(RuntimeError):
    """No additional session can be created within the configured bound."""


class SessionStateLimitError(ValueError):
    """A valid runtime state exceeds a configured memory bound."""


class InvalidSessionStateError(ValueError):
    """An evaluator returned a structurally invalid runtime state."""


@dataclass
class Session:
    _state: dict
    expires_at: float
    execution_lock: threading.Lock = field(default_factory=threading.Lock)


class SessionStore:
    """Thread-safe opaque-token store with sliding expiration and hard bounds.

    Each session has a separate execution lock. Serializing evaluations for a
    single session prevents two requests from reading the same starting state
    and silently losing one update. The global index lock is never held while
    RUNE code runs.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 30 * 60,
        max_sessions: int = 1_000,
        max_variables: int = 256,
        max_state_bytes: int = 16 * 1024,
        clock=time.monotonic,
        token_factory=lambda: secrets.token_urlsafe(32),
    ):
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if max_sessions < 1:
            raise ValueError("max_sessions must be at least 1")
        if max_variables < 1:
            raise ValueError("max_variables must be at least 1")
        if max_state_bytes < 1:
            raise ValueError("max_state_bytes must be at least 1")
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.max_variables = max_variables
        self.max_state_bytes = max_state_bytes
        self._clock = clock
        self._token_factory = token_factory
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    @staticmethod
    def initial_state() -> dict:
        return {"chaos_threshold": 1}

    def _cleanup_locked(self, now: float) -> None:
        expired = [
            token
            for token, session in self._sessions.items()
            if session.expires_at <= now and not session.execution_lock.locked()
        ]
        for token in expired:
            del self._sessions[token]

    def cleanup(self) -> int:
        """Remove expired idle sessions and return the number removed."""
        with self._lock:
            before = len(self._sessions)
            self._cleanup_locked(self._clock())
            return before - len(self._sessions)

    def create(self) -> tuple[str, Session]:
        now = self._clock()
        with self._lock:
            self._cleanup_locked(now)
            if len(self._sessions) >= self.max_sessions:
                raise SessionCapacityError("session capacity reached")
            token = self._token_factory()
            while token in self._sessions:
                token = self._token_factory()
            session = Session(self.initial_state(), now + self.ttl_seconds)
            self._sessions[token] = session
            return token, session

    def resolve(self, token: str) -> Session:
        now = self._clock()
        with self._lock:
            session = self._sessions.get(token)
            if session is None or session.expires_at <= now:
                if session is not None and not session.execution_lock.locked():
                    del self._sessions[token]
                raise SessionNotFoundError(token)
            session.expires_at = now + self.ttl_seconds
            return session

    def snapshot(self, session: Session) -> dict:
        """Return state detached from the store's committed copy."""
        return deepcopy(session._state)

    def _validate_state(self, state: dict) -> None:
        if not isinstance(state, dict):
            raise InvalidSessionStateError("invalid evaluator state")
        if set(state) - {"chaos_threshold", "variables"}:
            raise InvalidSessionStateError("invalid evaluator state")
        threshold = state.get("chaos_threshold")
        variables = state.get("variables", {})
        if type(threshold) is not int or threshold < 0:
            raise InvalidSessionStateError("invalid evaluator state")
        if not isinstance(variables, dict) or any(
            not isinstance(name, str)
            or not name
            or type(value) is not int
            for name, value in variables.items()
        ):
            raise InvalidSessionStateError("invalid evaluator state")
        if len(variables) > self.max_variables:
            raise SessionStateLimitError("Session variable limit exceeded")
        try:
            encoded = json.dumps(state, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError, OverflowError) as exc:
            raise SessionStateLimitError("Session state is too large") from exc
        if len(encoded) > self.max_state_bytes:
            raise SessionStateLimitError("Session state is too large")

    def commit(self, token: str, session: Session, state: dict) -> bool:
        """Commit if Reset has not removed/replaced this exact session."""
        self._validate_state(state)
        committed = deepcopy(state)
        now = self._clock()
        with self._lock:
            if self._sessions.get(token) is not session:
                return False
            session._state = committed
            session.expires_at = now + self.ttl_seconds
            return True

    def reset(self, token: str) -> None:
        with self._lock:
            if self._sessions.pop(token, None) is None:
                raise SessionNotFoundError(token)

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)
