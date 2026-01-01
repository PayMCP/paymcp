from types import SimpleNamespace

from paymcp.utils.context import capture_client_from_ctx, get_ctx_from_server


def test_get_ctx_from_server_returns_none_on_error():
    class Server:
        def get_context(self):
            raise RuntimeError("boom")

    assert get_ctx_from_server(Server()) is None


def test_capture_client_from_ctx_from_headers():
    class Headers(dict):
        def get(self, key, default=None):
            return super().get(key, default)

    ctx = SimpleNamespace(
        session=SimpleNamespace(_client_params=SimpleNamespace(clientInfo=SimpleNamespace(name="c"), capabilities=None)),
        request_context=SimpleNamespace(request=SimpleNamespace(headers=Headers({"mcp-session-id": "sess"}))),
    )
    info = capture_client_from_ctx(ctx)
    assert info["sessionId"] == "sess"
