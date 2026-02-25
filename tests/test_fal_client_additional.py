from __future__ import annotations

import httpx
import pytest
import respx

from genvoy.errors import GenvoyToolError
from genvoy.fal_client import BASE_API, FalClient, QUEUE_API


# Expected behavior: constructor should fail immediately when FAL_KEY is missing.
def test_fal_client_requires_key() -> None:
    with pytest.raises(GenvoyToolError) as exc:
        FalClient("")
    assert exc.value.code == "MISSING_FAL_KEY"


# Expected behavior: HTTP 404 should map to MODEL_NOT_FOUND for actionable fallback guidance.
@pytest.mark.asyncio
async def test_request_maps_model_not_found() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{BASE_API}/models").mock(return_value=httpx.Response(404, content=b"missing"))
            with pytest.raises(GenvoyToolError) as exc:
                await client.list_models()
        assert exc.value.code == "MODEL_NOT_FOUND"
    finally:
        await client.aclose()


# Expected behavior: non-special HTTP status failures should map to FAL_API_ERROR.
@pytest.mark.asyncio
async def test_request_maps_generic_http_failure() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{BASE_API}/models").mock(return_value=httpx.Response(500, content=b"boom"))
            with pytest.raises(GenvoyToolError) as exc:
                await client.list_models()
        assert exc.value.code == "FAL_API_ERROR"
    finally:
        await client.aclose()


# Expected behavior: get_schema should return inlined OpenAPI object from first model entry.
@pytest.mark.asyncio
async def test_get_schema_prefers_first_model_openapi() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{BASE_API}/models").mock(
                return_value=httpx.Response(
                    200,
                    json={"models": [{"openapi": {"title": "SchemaA"}}, {"openapi": {"title": "SchemaB"}}]},
                )
            )
            payload = await client.get_schema("fal-ai/flux/dev")
        assert payload["title"] == "SchemaA"
    finally:
        await client.aclose()


# Expected behavior: estimate_cost should combine pricing and estimate endpoint payloads.
@pytest.mark.asyncio
async def test_estimate_cost_calls_pricing_and_estimate_endpoints() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{BASE_API}/models/pricing").mock(return_value=httpx.Response(200, json={"unit_price": 0.02}))
            mock.post(f"{BASE_API}/models/pricing/estimate").mock(
                return_value=httpx.Response(200, json={"total_cost": 0.06})
            )
            payload = await client.estimate_cost("fal-ai/flux/dev", 3)
        assert payload["pricing"]["unit_price"] == 0.02
        assert payload["estimate"]["total_cost"] == 0.06
    finally:
        await client.aclose()


# Expected behavior: stream status should map unsupported stream endpoint responses to SSE_UNAVAILABLE.
@pytest.mark.asyncio
async def test_stream_job_status_maps_unavailable_status() -> None:
    client = FalClient("Key test")
    try:
        with respx.mock(assert_all_called=True) as mock:
            mock.get(f"{QUEUE_API}/fal-ai/flux/dev/requests/req-1/status/stream").mock(
                return_value=httpx.Response(404, content=b"not found")
            )
            with pytest.raises(GenvoyToolError) as exc:
                await client.stream_job_status("fal-ai/flux/dev", "req-1")
        assert exc.value.code == "SSE_UNAVAILABLE"
    finally:
        await client.aclose()

