from __future__ import annotations

import httpx
import pytest
import respx

from genvoy.errors import GenvoyToolError
from genvoy.fal_client import BASE_API, FalClient


# Expected behavior: model search should call platform endpoint and return parsed JSON payload.
@pytest.mark.asyncio
async def test_search_models_happy_path() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.get(f"{BASE_API}/models").mock(
                return_value=httpx.Response(200, json={"models": [{"endpoint_id": "fal-ai/flux/dev"}]})
            )
            payload = await client.search_models("flux")
        assert route.called
        assert payload["models"][0]["endpoint_id"] == "fal-ai/flux/dev"
    finally:
        await client.aclose()


# Expected behavior: cursor-based pagination should be forwarded as `cursor` query param.
@pytest.mark.asyncio
async def test_search_models_uses_cursor_param() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.get(f"{BASE_API}/models").mock(return_value=httpx.Response(200, json={"models": []}))
            await client.search_models("flux", cursor="abc123")
        assert route.called
        assert route.calls.last.request.url.params.get("cursor") == "abc123"
    finally:
        await client.aclose()


# Expected behavior: legacy `page` input should continue to work by mapping to `cursor`.
@pytest.mark.asyncio
async def test_search_models_page_alias_maps_to_cursor() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            route = mock.get(f"{BASE_API}/models").mock(return_value=httpx.Response(200, json={"models": []}))
            await client.search_models("flux", page="legacy-page")
        assert route.called
        assert route.calls.last.request.url.params.get("cursor") == "legacy-page"
        assert route.calls.last.request.url.params.get("page") is None
    finally:
        await client.aclose()


# Expected behavior: HTTP 429 should map to RATE_LIMITED with retry metadata preserved in message.
@pytest.mark.asyncio
async def test_request_maps_rate_limit_error() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{BASE_API}/models").mock(
                return_value=httpx.Response(429, headers={"Retry-After": "7"}, content=b"too many")
            )
            with pytest.raises(GenvoyToolError) as exc:
                await client.list_models()
        assert exc.value.code == "RATE_LIMITED"
        assert "Retry-After=7" in str(exc.value)
    finally:
        await client.aclose()


# Expected behavior: queue start timeout should map to QUEUE_START_TIMEOUT for actionable retries.
@pytest.mark.asyncio
async def test_submit_job_maps_queue_start_timeout() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.post("https://queue.fal.run/fal-ai/flux/dev").mock(
                return_value=httpx.Response(
                    504,
                    headers={"X-Fal-Request-Timeout-Type": "user"},
                    content=b"timeout",
                )
            )
            with pytest.raises(GenvoyToolError) as exc:
                await client.submit_job("fal-ai/flux/dev", {"prompt": "x"})
        assert exc.value.code == "QUEUE_START_TIMEOUT"
    finally:
        await client.aclose()


# Expected behavior: malformed non-JSON success payloads should raise INVALID_RESPONSE.
@pytest.mark.asyncio
async def test_request_rejects_non_json_success_payload() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{BASE_API}/models").mock(
                return_value=httpx.Response(200, content=b"not-json", headers={"Content-Type": "text/plain"})
            )
            with pytest.raises(GenvoyToolError) as exc:
                await client.list_models()
        assert exc.value.code == "INVALID_RESPONSE"
    finally:
        await client.aclose()


# Expected behavior: usage-history endpoint should return a clear admin-key-required error on 403 scope failures.
@pytest.mark.asyncio
async def test_list_recent_maps_admin_key_required_on_403() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{BASE_API}/models/usage").mock(return_value=httpx.Response(403, content=b"forbidden"))
            with pytest.raises(GenvoyToolError) as exc:
                await client.list_recent()
        assert exc.value.code == "ADMIN_KEY_REQUIRED"
        assert "Admin API key" in str(exc.value)
    finally:
        await client.aclose()


# Expected behavior: SSE parser should emit live status updates and stop at terminal COMPLETED.
@pytest.mark.asyncio
async def test_stream_job_status_parses_sse_events(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FalClient("Key test")

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            yield 'data: {"status":"IN_PROGRESS","progress":15}'
            yield ""
            yield 'data: {"status":"COMPLETED","progress":100}'
            yield ""

    class _FakeStreamCtx:
        async def __aenter__(self):
            return _FakeResponse()

        async def __aexit__(self, exc_type, exc, tb):
            return None

    def _fake_stream(method: str, url: str, timeout: float | None = None):
        return _FakeStreamCtx()

    updates: list[str] = []

    async def _on_status(payload: dict):
        updates.append(payload["status"])

    try:
        monkeypatch.setattr(client.client, "stream", _fake_stream)
        terminal = await client.stream_job_status("fal-ai/flux/dev", "req-1", on_status=_on_status)
    finally:
        await client.aclose()

    assert terminal["status"] == "COMPLETED"
    assert updates == ["IN_PROGRESS", "COMPLETED"]


# Expected behavior: when SSE is unavailable, wait_for_completion should fall back to polling.
@pytest.mark.asyncio
async def test_wait_for_completion_falls_back_to_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FalClient("Key test")
    statuses = [{"status": "IN_PROGRESS", "progress": 25}, {"status": "COMPLETED", "progress": 100}]
    poll_calls = 0
    observed: list[str] = []

    async def _stream_unavailable(*args, **kwargs):
        raise GenvoyToolError("SSE_UNAVAILABLE", "stream down")

    async def _fake_get_job_status(model_id: str, request_id: str):
        nonlocal poll_calls
        current = statuses[min(poll_calls, len(statuses) - 1)]
        poll_calls += 1
        return current

    async def _on_status(payload: dict):
        observed.append(payload["status"])

    async def _no_sleep(delay: float):
        return None

    try:
        monkeypatch.setattr(client, "stream_job_status", _stream_unavailable)
        monkeypatch.setattr(client, "get_job_status", _fake_get_job_status)
        monkeypatch.setattr("genvoy.fal_client.asyncio.sleep", _no_sleep)
        terminal = await client.wait_for_completion(
            "fal-ai/flux/dev",
            "req-2",
            timeout_seconds=30,
            poll_interval_seconds=2,
            on_status=_on_status,
        )
    finally:
        await client.aclose()

    assert terminal["status"] == "COMPLETED"
    assert poll_calls >= 2
    assert observed == ["IN_PROGRESS", "COMPLETED"]
