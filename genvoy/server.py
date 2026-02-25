from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Literal, cast

from fastmcp import Context, FastMCP
from fastmcp.server.transforms import ResourcesAsTools
from pydantic import ValidationError

from genvoy import __version__, config
from genvoy.errors import GenvoyToolError, ensure
from genvoy.fal_client import FalClient
from genvoy.filesystem import copy_to_repo, detect_type_and_ext, download_to_file, resolve_output_path
from genvoy.models import (
    BatchInput,
    BatchResult,
    CompareInput,
    CompareResult,
    EstimateCostInput,
    GenerateInput,
    GenerateResult,
    JobLookupInput,
    SearchModelsInput,
)

logger = logging.getLogger(__name__)
mcp = FastMCP(name="genvoy", version=__version__)
mcp.add_transform(ResourcesAsTools(mcp))
SEMAPHORE = asyncio.Semaphore(config.MAX_CONCURRENT_JOBS)


def _raise_validation_error(exc: ValidationError) -> None:
    errors = exc.errors()
    message = str(errors[0].get("msg", "Validation failed")) if errors else "Validation failed"
    if "INVALID_MODEL_ID" in message:
        raise GenvoyToolError("INVALID_MODEL_ID", "Invalid model ID format.")
    if "PROMPT_TOO_LONG" in message:
        raise GenvoyToolError(
            "PROMPT_TOO_LONG",
            f"Prompt exceeds MAX_PROMPT_LENGTH ({config.MAX_PROMPT_LENGTH}).",
        )
    if "AMBIGUOUS_PAGINATION_CURSOR" in message:
        raise GenvoyToolError(
            "AMBIGUOUS_PAGINATION_CURSOR",
            "Provide only one of cursor or page, or set both to the same value.",
        )
    raise GenvoyToolError("VALIDATION_ERROR", message)


async def _get_client() -> FalClient:
    settings = config.get_settings(require_key=True)
    return FalClient(settings.fal_key)


def _slugify_model_id(model_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", model_id).strip("-").lower()


def _extract_first_media_url(payload: Any) -> str | None:
    urls: list[str] = []

    if isinstance(payload, str):
        if payload.startswith("http://") or payload.startswith("https://"):
            urls.append(payload)
    elif isinstance(payload, dict):
        # Prefer common media-bearing keys first.
        for preferred in ("images", "videos", "audio", "url", "image", "video", "result", "output"):
            if preferred in payload:
                found = _extract_first_media_url(payload[preferred])
                if found:
                    urls.append(found)
        for value in payload.values():
            found = _extract_first_media_url(value)
            if found:
                urls.append(found)
    elif isinstance(payload, list):
        for item in payload:
            found = _extract_first_media_url(item)
            if found:
                urls.append(found)

    if not urls:
        return None

    # Prefer URLs with recognized media extension; otherwise return the first URL.
    for candidate in urls:
        media_type, _ = detect_type_and_ext(candidate)
        if media_type in {"image", "video", "audio"}:
            return candidate
    return urls[0]


def _status_from_payload(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("data"), dict):
        nested = payload["data"]
        return str(
            nested.get("status")
            or nested.get("state")
            or payload.get("status")
            or payload.get("state")
            or ""
        ).upper()
    return str(payload.get("status") or payload.get("state") or "").upper()


def _progress_from_payload(payload: dict[str, Any]) -> float:
    source: dict[str, Any] = payload
    if isinstance(payload.get("data"), dict):
        source = payload["data"]

    raw = source.get("progress")
    if raw is None:
        raw = source.get("progress_percent")
    if raw is None:
        raw = source.get("percentage")
    if raw is None and isinstance(source.get("metrics"), dict):
        raw = source["metrics"].get("progress")

    try:
        value = float(raw if raw is not None else 0.0)
    except (TypeError, ValueError):
        return 0.0
    if 0.0 <= value <= 1.0:
        value *= 100.0
    return max(0.0, min(100.0, value))


def _get_nested(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return None
        cursor = cursor[key]
    return cursor


def _extract_cost_usd(payload: dict[str, Any]) -> float | None:
    candidate_paths = [
        ("cost_usd",),
        ("cost",),
        ("usage", "cost_usd"),
        ("usage", "cost"),
        ("usage", "total_cost"),
        ("metrics", "cost"),
    ]
    sources = [payload]
    if isinstance(payload.get("data"), dict):
        sources.append(payload["data"])
    for source in sources:
        for path in candidate_paths:
            raw = _get_nested(source, path)
            if raw is None:
                continue
            if isinstance(raw, (int, float)):
                return float(raw)
            if isinstance(raw, str):
                match = re.search(r"-?\d+(?:\.\d+)?", raw)
                if match:
                    return float(match.group(0))
    return None


def _extract_duration_ms(payload: dict[str, Any]) -> int | None:
    candidate_paths = [
        ("duration_ms",),
        ("latency_ms",),
        ("timings", "duration_ms"),
        ("timings", "total_ms"),
        ("metrics", "duration_ms"),
    ]
    sources = [payload]
    if isinstance(payload.get("data"), dict):
        sources.append(payload["data"])
    for source in sources:
        for path in candidate_paths:
            raw = _get_nested(source, path)
            if raw is None:
                continue
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                continue
    return None


async def _wait_for_completion_with_progress(
    client: FalClient,
    *,
    model_id: str,
    request_id: str,
    timeout_seconds: float,
    poll_interval_seconds: float,
    ctx: Context | None,
) -> dict[str, Any]:
    async def _on_status(status: dict[str, Any]) -> None:
        state = _status_from_payload(status)
        progress = _progress_from_payload(status)
        if state == "COMPLETED":
            progress = 100.0
        if ctx:
            await ctx.report_progress(progress, 100.0, f"{model_id} status={state or 'UNKNOWN'}")

    return await client.wait_for_completion(
        model_id=model_id,
        request_id=request_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        on_status=_on_status,
    )


async def _generate_once(
    *,
    model_id: str,
    prompt: str,
    params: dict[str, Any],
    output_path: str | Path,
    repo_path: str | Path | None,
    timeout_seconds: float,
    ctx: Context | None,
) -> GenerateResult:
    async with SEMAPHORE:
        client = await _get_client()
        try:
            payload = {"prompt": prompt, **(params or {})}
            submit_data = await client.submit_job(model_id, payload)
            request_id_raw = submit_data.get("request_id") or submit_data.get("requestId")
            ensure(bool(request_id_raw), "INVALID_RESPONSE", "fal.ai queue response missing request_id.")
            request_id = str(request_id_raw)

            terminal_status = await _wait_for_completion_with_progress(
                client,
                model_id=model_id,
                request_id=request_id,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=2.0,
                ctx=ctx,
            )
            result_payload = await client.get_job_result(model_id, request_id)
        finally:
            await client.aclose()

    result_url_raw = _extract_first_media_url(result_payload)
    ensure(bool(result_url_raw), "INVALID_RESPONSE", "No media URL found in fal.ai result payload.")
    result_url = str(result_url_raw)

    _, ext = detect_type_and_ext(result_url)
    resolved_output = resolve_output_path(output_path, preferred_ext=ext)
    settings = config.get_settings(require_key=True)
    download = await download_to_file(
        result_url,
        resolved_output,
        headers={"Authorization": settings.fal_key},
    )

    copied_to_repo: Path | None = None
    if repo_path:
        repo_target = Path(repo_path)
        if not repo_target.suffix and download.path.suffix:
            repo_target = repo_target.with_suffix(download.path.suffix)
        copied_to_repo = await copy_to_repo(download.path, repo_target)

    duration_ms = _extract_duration_ms(result_payload) or _extract_duration_ms(terminal_status)
    cost_usd = _extract_cost_usd(result_payload) or _extract_cost_usd(terminal_status)

    media_type: Literal["image", "video", "audio", "unknown"] = (
        cast(Literal["image", "video", "audio"], download.media_type)
        if download.media_type in {"image", "video", "audio"}
        else "unknown"
    )

    return GenerateResult(
        request_id=str(request_id),
        output_path=str(download.path),
        repo_path=str(copied_to_repo) if copied_to_repo else None,
        media_type=media_type,
        file_size_kb=round(download.file_size_bytes / 1024, 3),
        model_id=model_id,
        cost_usd=cost_usd,
        duration_ms=duration_ms,
        result_url=result_url,
    )


@mcp.tool(
    name="search_models",
    timeout=15,
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def search_models(
    ctx: Context,
    query: str,
    category: str | None = None,
    cursor: str | None = None,
    page: str | None = None,
) -> dict[str, Any]:
    """Search fal.ai models by keyword with optional category and pagination cursor."""
    try:
        data = SearchModelsInput(query=query, category=category, cursor=cursor, page=page)
    except ValidationError as exc:
        _raise_validation_error(exc)
    client = await _get_client()
    try:
        return await client.search_models(data.query, data.category, data.cursor)
    finally:
        await client.aclose()


@mcp.tool(
    name="get_schema",
    timeout=15,
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def get_schema(ctx: Context, model_id: str) -> dict[str, Any]:
    """Fetch the model input schema so callers can validate generation parameters before use."""
    try:
        data = EstimateCostInput(model_id=model_id, count=1)
    except ValidationError as exc:
        _raise_validation_error(exc)
    client = await _get_client()
    try:
        return await client.get_schema(data.model_id)
    finally:
        await client.aclose()


@mcp.tool(
    name="estimate_cost",
    timeout=15,
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def estimate_cost(ctx: Context, model_id: str, count: int = 1) -> dict[str, Any]:
    """Estimate generation cost for a model and quantity using fal.ai pricing endpoints."""
    try:
        data = EstimateCostInput(model_id=model_id, count=count)
    except ValidationError as exc:
        _raise_validation_error(exc)
    client = await _get_client()
    try:
        return await client.estimate_cost(data.model_id, data.count)
    finally:
        await client.aclose()


@mcp.tool(
    name="generate",
    timeout=360,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def generate(
    ctx: Context,
    model_id: str,
    prompt: str,
    output_path: str,
    repo_path: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate one asset, download it locally, and optionally copy it into a repository path."""
    try:
        data = GenerateInput(
            model_id=model_id,
            prompt=prompt,
            output_path=output_path,
            repo_path=repo_path,
            params=params or {},
        )
    except ValidationError as exc:
        _raise_validation_error(exc)

    result = await _generate_once(
        model_id=data.model_id,
        prompt=data.prompt,
        params=data.params,
        output_path=data.output_path,
        repo_path=data.repo_path,
        timeout_seconds=360.0,
        ctx=ctx,
    )
    return result.model_dump()


@mcp.tool(
    name="generate_batch",
    timeout=600,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def generate_batch(
    ctx: Context,
    model_id: str,
    prompt: str,
    count: int,
    output_dir: str,
    repo_dir: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run multiple generation jobs for one model/prompt and return partial successes/failures."""
    try:
        data = BatchInput(
            model_id=model_id,
            prompt=prompt,
            count=count,
            output_dir=output_dir,
            repo_dir=repo_dir,
            params=params or {},
        )
    except ValidationError as exc:
        _raise_validation_error(exc)

    output_base = Path(data.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)
    slug = _slugify_model_id(data.model_id)

    tasks = [
        _generate_once(
            model_id=data.model_id,
            prompt=data.prompt,
            params=data.params,
            output_path=output_base / f"{slug}_{idx + 1}",
            repo_path=(Path(data.repo_dir) / f"{slug}_{idx + 1}") if data.repo_dir else None,
            timeout_seconds=600.0,
            ctx=ctx,
        )
        for idx in range(data.count)
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    files: list[GenerateResult] = []
    failed: list[dict[str, Any]] = []
    for idx, item in enumerate(results):
        if isinstance(item, BaseException):
            failed.append({"index": idx + 1, "error": str(item)})
        else:
            files.append(cast(GenerateResult, item))

    return BatchResult(files=files, failed=failed).model_dump()


@mcp.tool(
    name="generate_compare",
    timeout=600,
    annotations={
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def generate_compare(
    ctx: Context,
    model_ids: list[str],
    prompt: str,
    output_dir: str,
    repo_dir: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the same prompt across multiple models for side-by-side output comparison."""
    try:
        data = CompareInput(
            model_ids=model_ids,
            prompt=prompt,
            output_dir=output_dir,
            repo_dir=repo_dir,
            params=params or {},
        )
    except ValidationError as exc:
        _raise_validation_error(exc)

    output_base = Path(data.output_dir)
    output_base.mkdir(parents=True, exist_ok=True)

    tasks = []
    for model_id in data.model_ids:
        slug = _slugify_model_id(model_id)
        tasks.append(
            _generate_once(
                model_id=model_id,
                prompt=data.prompt,
                params=data.params,
                output_path=output_base / slug,
                repo_path=(Path(data.repo_dir) / slug) if data.repo_dir else None,
                timeout_seconds=600.0,
                ctx=ctx,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)
    files: list[GenerateResult] = []
    failed: list[dict[str, Any]] = []
    for model_id, item in zip(data.model_ids, results):
        if isinstance(item, BaseException):
            failed.append({"model_id": model_id, "error": str(item)})
        else:
            files.append(cast(GenerateResult, item))

    return CompareResult(files=files, failed=failed).model_dump()


@mcp.tool(
    name="get_job_status",
    timeout=15,
    annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True},
)
async def get_job_status(ctx: Context, request_id: str, model_id: str) -> dict[str, Any]:
    """Get the current status of a queued fal.ai request by model and request ID."""
    try:
        data = JobLookupInput(request_id=request_id, model_id=model_id)
    except ValidationError as exc:
        _raise_validation_error(exc)
    client = await _get_client()
    try:
        return await client.get_job_status(data.model_id, data.request_id)
    finally:
        await client.aclose()


@mcp.tool(
    name="cancel_job",
    timeout=15,
    annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True},
)
async def cancel_job(ctx: Context, request_id: str, model_id: str) -> dict[str, Any]:
    """Request cancellation for a queued fal.ai job and return the provider response payload."""
    try:
        data = JobLookupInput(request_id=request_id, model_id=model_id)
    except ValidationError as exc:
        _raise_validation_error(exc)
    client = await _get_client()
    try:
        return await client.cancel_job(data.model_id, data.request_id)
    finally:
        await client.aclose()


@mcp.resource("genvoy://models")
async def models_resource() -> str:
    """Return a JSON snapshot of available fal.ai models for resource-aware MCP clients."""
    client = await _get_client()
    try:
        payload = await client.list_models()
    finally:
        await client.aclose()
    return json.dumps(payload, indent=2)


@mcp.resource("genvoy://recent")
async def recent_resource() -> str:
    """Return recent usage history from fal.ai (requires Admin API key scope)."""
    client = await _get_client()
    try:
        payload = await client.list_recent()
    finally:
        await client.aclose()
    return json.dumps(payload, indent=2)


def main() -> None:
    # Fail fast on startup if key is missing.
    config.get_settings(require_key=True)
    logger.info("Starting Genvoy MCP server.")
    mcp.run()


if __name__ == "__main__":
    main()
