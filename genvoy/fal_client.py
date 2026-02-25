from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from genvoy.errors import GenvoyToolError

BASE_API = "https://api.fal.ai/v1"
QUEUE_API = "https://queue.fal.run"


class FalClient:
    def __init__(self, fal_key: str, timeout: float = 30.0):
        if not fal_key:
            raise GenvoyToolError("MISSING_FAL_KEY", "FAL_KEY is not configured.")
        self.fal_key = fal_key
        self.client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": fal_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self.client.aclose()

    async def __aenter__(self) -> "FalClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self.client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise GenvoyToolError("NETWORK_ERROR", f"fal.ai request failed: {exc}") from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise GenvoyToolError(
                "RATE_LIMITED",
                f"Rate limited by fal.ai. Retry-After={retry_after}.",
            )

        if response.status_code == 404:
            raise GenvoyToolError("MODEL_NOT_FOUND", "Model or request ID not found.")

        if response.status_code == 403 and "/models/usage" in url:
            raise GenvoyToolError(
                "ADMIN_KEY_REQUIRED",
                "fal.ai usage history requires an Admin API key.",
            )

        if response.status_code == 504 and response.headers.get("X-Fal-Request-Timeout-Type") == "user":
            raise GenvoyToolError(
                "QUEUE_START_TIMEOUT",
                "Queue job did not start within the requested timeout window.",
            )

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text[:500]
            raise GenvoyToolError(
                "FAL_API_ERROR",
                f"{response.status_code} response from fal.ai: {body}",
            ) from exc

        if not response.content:
            return {}

        try:
            return response.json()
        except ValueError as exc:
            raise GenvoyToolError("INVALID_RESPONSE", "fal.ai returned non-JSON payload.") from exc

    @staticmethod
    def _status_value(payload: dict[str, Any]) -> str:
        if isinstance(payload.get("data"), dict):
            nested = payload["data"]
            return str(nested.get("status") or nested.get("state") or payload.get("status") or payload.get("state") or "").upper()
        return str(payload.get("status") or payload.get("state") or "").upper()

    async def stream_job_status(
        self,
        model_id: str,
        request_id: str,
        *,
        timeout_seconds: float = 360.0,
        on_status: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        url = f"{QUEUE_API}/{model_id}/requests/{request_id}/status/stream"
        last_payload: dict[str, Any] | None = None
        try:
            async with self.client.stream("GET", url, timeout=timeout_seconds) as response:
                if response.status_code in {404, 405, 501}:
                    raise GenvoyToolError(
                        "SSE_UNAVAILABLE",
                        f"SSE stream unavailable for {model_id}/{request_id}.",
                    )
                response.raise_for_status()

                data_lines: list[str] = []
                async for line in response.aiter_lines():
                    if line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
                        continue
                    if line.strip():
                        continue
                    if not data_lines:
                        continue

                    raw = "\n".join(data_lines).strip()
                    data_lines = []
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        last_payload = payload
                        if on_status:
                            maybe_awaitable = on_status(payload)
                            if maybe_awaitable is not None:
                                await maybe_awaitable
                        state = self._status_value(payload)
                        if state in {"COMPLETED", "FAILED"}:
                            return payload
        except GenvoyToolError:
            raise
        except httpx.HTTPStatusError as exc:
            raise GenvoyToolError("SSE_UNAVAILABLE", f"SSE stream request failed: {exc}") from exc
        except httpx.HTTPError as exc:
            raise GenvoyToolError("SSE_UNAVAILABLE", f"SSE stream unavailable: {exc}") from exc

        if last_payload:
            state = self._status_value(last_payload)
            if state in {"COMPLETED", "FAILED"}:
                return last_payload
        raise GenvoyToolError("SSE_UNAVAILABLE", "SSE stream ended without usable status events.")

    async def search_models(
        self,
        query: str,
        category: str | None = None,
        cursor: str | None = None,
        page: str | None = None,
    ) -> dict[str, Any]:
        if cursor and page and cursor != page:
            raise GenvoyToolError(
                "AMBIGUOUS_PAGINATION_CURSOR",
                "Provide only one of cursor or page, or set both to the same value.",
            )
        effective_cursor = cursor or page
        params: dict[str, Any] = {"q": query}
        if category:
            params["category"] = category
        if effective_cursor:
            params["cursor"] = effective_cursor
        return await self._request("GET", f"{BASE_API}/models", params=params)

    async def list_models(
        self,
        category: str | None = None,
        cursor: str | None = None,
        page: str | None = None,
    ) -> dict[str, Any]:
        if cursor and page and cursor != page:
            raise GenvoyToolError(
                "AMBIGUOUS_PAGINATION_CURSOR",
                "Provide only one of cursor or page, or set both to the same value.",
            )
        effective_cursor = cursor or page
        params: dict[str, Any] = {}
        if category:
            params["category"] = category
        if effective_cursor:
            params["cursor"] = effective_cursor
        return await self._request("GET", f"{BASE_API}/models", params=params)

    async def get_schema(self, model_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"{BASE_API}/models",
            params={"endpoint_id": model_id, "expand": "openapi-3.0"},
        )
        if isinstance(payload.get("models"), list) and payload["models"]:
            model_entry = payload["models"][0]
            return model_entry.get("openapi", model_entry)
        return payload.get("openapi", payload)

    async def estimate_cost(self, model_id: str, count: int) -> dict[str, Any]:
        pricing = await self._request(
            "GET",
            f"{BASE_API}/models/pricing",
            params={"endpoint_id": model_id},
        )
        estimate = await self._request(
            "POST",
            f"{BASE_API}/models/pricing/estimate",
            json={
                "estimate_type": "historical_api_price",
                "endpoints": {model_id: {"call_quantity": count}},
            },
        )
        return {"pricing": pricing, "estimate": estimate}

    async def list_recent(self, model_id: str | None = None, limit: int = 20) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if model_id:
            params["endpoint_id"] = model_id
        return await self._request("GET", f"{BASE_API}/models/usage", params=params)

    async def submit_job(
        self,
        model_id: str,
        payload: dict[str, Any],
        *,
        start_timeout_seconds: int = 60,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"{QUEUE_API}/{model_id}",
            json=payload,
            headers={"X-Fal-Request-Timeout": str(start_timeout_seconds)},
        )

    async def get_job_status(self, model_id: str, request_id: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"{QUEUE_API}/{model_id}/requests/{request_id}/status",
        )

    async def get_job_result(self, model_id: str, request_id: str) -> dict[str, Any]:
        return await self._request("GET", f"{QUEUE_API}/{model_id}/requests/{request_id}")

    async def cancel_job(self, model_id: str, request_id: str) -> dict[str, Any]:
        return await self._request(
            "PUT",
            f"{QUEUE_API}/{model_id}/requests/{request_id}/cancel",
        )

    async def wait_for_completion(
        self,
        model_id: str,
        request_id: str,
        *,
        timeout_seconds: float = 360.0,
        poll_interval_seconds: float = 2.0,
        on_status: Callable[[dict[str, Any]], Awaitable[None] | None] | None = None,
    ) -> dict[str, Any]:
        # Preferred path: SSE status stream.
        try:
            terminal = await self.stream_job_status(
                model_id,
                request_id,
                timeout_seconds=timeout_seconds,
                on_status=on_status,
            )
            state = self._status_value(terminal)
            if state == "COMPLETED":
                return terminal
            if state == "FAILED":
                raise GenvoyToolError("JOB_FAILED", f"fal.ai job failed: {terminal}")
        except GenvoyToolError as exc:
            # Fall back to polling when stream is unavailable.
            if getattr(exc, "code", None) != "SSE_UNAVAILABLE":
                raise

        # Fallback path: polling.
        elapsed = 0.0
        while elapsed < timeout_seconds:
            status = await self.get_job_status(model_id, request_id)
            if on_status:
                maybe_awaitable = on_status(status)
                if maybe_awaitable is not None:
                    await maybe_awaitable
            state = self._status_value(status)
            if state == "COMPLETED":
                return status
            if state == "FAILED":
                raise GenvoyToolError("JOB_FAILED", f"fal.ai job failed: {status}")
            await asyncio.sleep(poll_interval_seconds)
            elapsed += poll_interval_seconds
        raise GenvoyToolError("JOB_TIMEOUT", f"Job {request_id} timed out after {timeout_seconds}s.")
