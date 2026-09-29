"""A context we cannot read must not fail the call it belongs to.

FastMCP exposes `request_context` and `session` as properties that raise when
there is no active request. `getattr(obj, name, None)` does not cover that - its
default only catches AttributeError - so reading identity off such a context
used to take the whole tool call down with it, before any payment was made.
"""

import pytest

from paymcp.utils.context import (
    capture_client_from_ctx,
    get_stable_session_id,
    read,
)


class Angry:
    """Shaped like a Context with no request behind it."""

    @property
    def request_context(self):
        raise ValueError("Context is not available outside of a request")

    @property
    def session(self):
        raise ValueError("Context is not available outside of a request")

    @property
    def client_id(self):
        raise ValueError("Context is not available outside of a request")


def test_read_gives_up_instead_of_raising():
    assert read(Angry(), "session") is None
    assert read(None, "session") is None
    assert read(object(), "missing") is None


def test_a_session_id_is_simply_unknown():
    assert get_stable_session_id(Angry()) is None


def test_the_client_is_described_as_unknown():
    described = capture_client_from_ctx(Angry())
    assert described["name"] == "unknown"
    assert described["sessionId"] is None
