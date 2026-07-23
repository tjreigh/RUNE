import pytest

from sessions import (
    InvalidSessionStateError,
    SessionCapacityError,
    SessionNotFoundError,
    SessionStateLimitError,
    SessionStore,
)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _tokens(*values):
    iterator = iter(values)
    return lambda: next(iterator)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ttl_seconds": 0},
        {"max_sessions": 0},
        {"max_variables": 0},
        {"max_state_bytes": 0},
    ],
)
def test_session_store_rejects_non_positive_bounds(kwargs):
    with pytest.raises(ValueError):
        SessionStore(**kwargs)


def test_create_uses_unique_opaque_tokens_and_initial_state():
    store = SessionStore(token_factory=_tokens("a" * 43, "a" * 43, "b" * 43))
    first_token, first = store.create()
    second_token, second = store.create()

    assert first_token == "a" * 43
    assert second_token == "b" * 43
    assert store.snapshot(first) == {"chaos_threshold": 1}
    assert store.snapshot(second) == {"chaos_threshold": 1}


def test_resolve_refreshes_sliding_expiration():
    clock = Clock()
    store = SessionStore(
        ttl_seconds=10,
        clock=clock,
        token_factory=_tokens("a" * 43),
    )
    token, session = store.create()
    clock.now = 6
    assert store.resolve(token) is session
    clock.now = 11
    assert store.resolve(token) is session


def test_expired_session_is_removed_and_cannot_be_resolved():
    clock = Clock()
    store = SessionStore(
        ttl_seconds=10,
        clock=clock,
        token_factory=_tokens("a" * 43),
    )
    token, _ = store.create()
    clock.now = 10

    with pytest.raises(SessionNotFoundError):
        store.resolve(token)
    assert store.session_count == 0


def test_expiration_cleanup_releases_capacity():
    clock = Clock()
    store = SessionStore(
        ttl_seconds=10,
        max_sessions=1,
        clock=clock,
        token_factory=_tokens("a" * 43, "b" * 43),
    )
    store.create()
    with pytest.raises(SessionCapacityError):
        store.create()

    clock.now = 10
    token, _ = store.create()
    assert token == "b" * 43


def test_snapshot_and_commit_are_detached_from_caller_mappings():
    store = SessionStore(token_factory=_tokens("a" * 43))
    token, session = store.create()
    new_state = {"chaos_threshold": 1, "variables": {"answer": 42}}
    assert store.commit(token, session, new_state)

    new_state["variables"]["answer"] = 0
    snapshot = store.snapshot(session)
    snapshot["variables"]["answer"] = -1
    assert store.snapshot(session)["variables"] == {"answer": 42}


def test_reset_prevents_an_in_flight_session_reference_from_committing():
    store = SessionStore(token_factory=_tokens("a" * 43))
    token, session = store.create()
    store.reset(token)

    assert not store.commit(
        token,
        session,
        {"chaos_threshold": 1, "variables": {"answer": 42}},
    )
    with pytest.raises(SessionNotFoundError):
        store.resolve(token)


def test_variable_count_and_serialized_size_are_bounded():
    store = SessionStore(
        max_variables=1,
        max_state_bytes=100,
        token_factory=_tokens("a" * 43),
    )
    token, session = store.create()

    with pytest.raises(SessionStateLimitError, match="variable limit"):
        store.commit(
            token,
            session,
            {"chaos_threshold": 1, "variables": {"a": 1, "b": 2}},
        )
    with pytest.raises(SessionStateLimitError, match="too large"):
        store.commit(
            token,
            session,
            {"chaos_threshold": 1, "variables": {"huge": 10 ** 200}},
        )
    assert store.snapshot(session) == {"chaos_threshold": 1}


@pytest.mark.parametrize(
    "state",
    [
        None,
        {},
        {"chaos_threshold": "1"},
        {"chaos_threshold": 1, "variables": []},
        {"chaos_threshold": 1, "variables": {"answer": "42"}},
        {"chaos_threshold": 1, "unexpected": True},
    ],
)
def test_structurally_invalid_evaluator_state_is_rejected(state):
    store = SessionStore(token_factory=_tokens("a" * 43))
    token, session = store.create()

    with pytest.raises(InvalidSessionStateError):
        store.commit(token, session, state)
