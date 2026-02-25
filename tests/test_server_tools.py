from __future__ import annotations

from typing import Any

import pytest

import genvoy.server as server
from genvoy.errors import GenvoyToolError


class _ToolClient:
    def __init__(self) -> None:
        self.closed = False
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    async def search_models(self, query: str, category: str | None, cursor: str | None) -> dict[str, Any]:
        self.calls.append(("search_models", (query, category, cursor)))
        return {"models": [{"endpoint_id": "fal-ai/flux/dev"}]}

    async def get_schema(self, model_id: str) -> dict[str, Any]:
        self.calls.append(("get_schema", (model_id,)))
        return {"openapi": {"type": "object"}}

    async def estimate_cost(self, model_id: str, count: int) -> dict[str, Any]:
        self.calls.append(("estimate_cost", (model_id, count)))
        return {"estimate": {"total": 0.1}}

    async def get_job_status(self, model_id: str, request_id: str) -> dict[str, Any]:
        self.calls.append(("get_job_status", (model_id, request_id)))
        return {"status": "IN_PROGRESS"}

    async def cancel_job(self, model_id: str, request_id: str) -> dict[str, Any]:
        self.calls.append(("cancel_job", (model_id, request_id)))
        return {"cancelled": True}

    async def aclose(self) -> None:
        self.closed = True


# Expected behavior: read-only/search tools should call underlying client methods and return their payload.
@pytest.mark.asyncio
async def test_search_schema_and_estimate_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _ToolClient()

    async def _fake_get_client():
        return client

    monkeypatch.setattr(server, "_get_client", _fake_get_client)

    search_payload = await server.search_models(None, "flux", category=None, cursor="next-1")
    legacy_search_payload = await server.search_models(None, "flux", category=None, page="legacy-2")
    schema_payload = await server.get_schema(None, "fal-ai/flux/dev")
    estimate_payload = await server.estimate_cost(None, "fal-ai/flux/dev", count=3)

    assert search_payload["models"][0]["endpoint_id"] == "fal-ai/flux/dev"
    assert legacy_search_payload["models"][0]["endpoint_id"] == "fal-ai/flux/dev"
    assert schema_payload["openapi"]["type"] == "object"
    assert estimate_payload["estimate"]["total"] == 0.1
    assert ("search_models", ("flux", None, "next-1")) in client.calls
    assert ("search_models", ("flux", None, "legacy-2")) in client.calls
    assert ("get_schema", ("fal-ai/flux/dev",)) in client.calls
    assert ("estimate_cost", ("fal-ai/flux/dev", 3)) in client.calls
    assert client.closed is True


# Expected behavior: queue management tools should validate IDs and proxy to client when valid.
@pytest.mark.asyncio
async def test_get_job_status_and_cancel_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _ToolClient()

    async def _fake_get_client():
        return client

    monkeypatch.setattr(server, "_get_client", _fake_get_client)

    status_payload = await server.get_job_status(None, request_id="req-1", model_id="fal-ai/flux/dev")
    cancel_payload = await server.cancel_job(None, request_id="req-1", model_id="fal-ai/flux/dev")

    assert status_payload["status"] == "IN_PROGRESS"
    assert cancel_payload["cancelled"] is True
    assert ("get_job_status", ("fal-ai/flux/dev", "req-1")) in client.calls
    assert ("cancel_job", ("fal-ai/flux/dev", "req-1")) in client.calls


# Expected behavior: invalid model IDs should surface INVALID_MODEL_ID from validation boundary.
@pytest.mark.asyncio
async def test_tool_validation_surfaces_invalid_model_id() -> None:
    with pytest.raises(GenvoyToolError) as exc:
        await server.get_schema(None, "invalid model id")
    assert exc.value.code == "INVALID_MODEL_ID"


# Expected behavior: conflicting cursor/page values should be rejected to avoid ambiguous pagination.
@pytest.mark.asyncio
async def test_search_models_rejects_conflicting_cursor_and_page() -> None:
    with pytest.raises(GenvoyToolError) as exc:
        await server.search_models(None, "flux", cursor="cursor-A", page="cursor-B")
    assert exc.value.code == "AMBIGUOUS_PAGINATION_CURSOR"
