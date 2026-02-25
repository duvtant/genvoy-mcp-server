from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

import genvoy.server as server
from genvoy.errors import GenvoyToolError


def _workspace_tmp_dir() -> Path:
    base = Path.cwd() / ".pytest_codex_tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"srv-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


class _Ctx:
    def __init__(self) -> None:
        self.progress_events: list[tuple[float, float | None, str | None]] = []

    async def report_progress(self, progress: float, total: float | None = None, message: str | None = None) -> None:
        self.progress_events.append((progress, total, message))


class _ClientFactory:
    def __init__(self, *, fail_request_ids: set[str] | None = None, fail_models: set[str] | None = None):
        self.counter = 0
        self.fail_request_ids = fail_request_ids or set()
        self.fail_models = fail_models or set()
        self.closed_clients = 0

    def make(self):
        factory = self

        class _FakeClient:
            async def submit_job(self, model_id: str, payload: dict[str, Any]) -> dict[str, Any]:
                factory.counter += 1
                return {"request_id": f"req-{factory.counter}"}

            async def wait_for_completion(
                self,
                model_id: str,
                request_id: str,
                timeout_seconds: float = 360.0,
                poll_interval_seconds: float = 2.0,
                on_status=None,
            ) -> dict[str, Any]:
                if on_status:
                    await on_status({"status": "IN_PROGRESS", "progress": 0.5})
                if request_id in factory.fail_request_ids or model_id in factory.fail_models:
                    raise GenvoyToolError("JOB_FAILED", f"forced failure for {model_id}/{request_id}")
                terminal = {"status": "COMPLETED", "usage": {"cost_usd": 0.42}, "timings": {"duration_ms": 1234}}
                if on_status:
                    await on_status(terminal)
                return terminal

            async def get_job_result(self, model_id: str, request_id: str) -> dict[str, Any]:
                return {
                    "result": {
                        "url": f"https://cdn.fal.ai/{model_id.replace('/', '-')}-{request_id}.png",
                    },
                    "usage": {"cost": "$0.15"},
                }

            async def aclose(self) -> None:
                factory.closed_clients += 1

        return _FakeClient()


# Expected behavior: generate should run queue -> completion -> download -> optional repo copy and return structured metadata.
@pytest.mark.asyncio
async def test_generate_pipeline_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp = _workspace_tmp_dir()
    try:
        monkeypatch.setenv("FAL_KEY", "Key test")
        factory = _ClientFactory()

        async def _fake_get_client():
            return factory.make()

        monkeypatch.setattr(server, "_get_client", _fake_get_client)
        ctx = _Ctx()

        with respx.mock(assert_all_called=True) as mock:
            mock.get(re.compile(r"https://cdn\.fal\.ai/.*")).mock(
                return_value=httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"PNG")
            )
            result = await server.generate(
                ctx=ctx,
                model_id="fal-ai/flux/dev",
                prompt="a floating island",
                output_path=str(tmp / "out" / "hero"),
                repo_path=str(tmp / "repo" / "hero"),
                params={"seed": 7},
            )

        assert Path(result["output_path"]).exists()
        assert result["output_path"].endswith(".png")
        assert result["repo_path"] and result["repo_path"].endswith(".png")
        assert Path(result["repo_path"]).exists()
        assert result["media_type"] == "image"
        assert result["duration_ms"] == 1234
        assert result["cost_usd"] == pytest.approx(0.15)
        assert ctx.progress_events, "generate should report progress"
        assert any((event[0] or 0) >= 100 for event in ctx.progress_events)
        assert factory.closed_clients >= 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# Expected behavior: generate_batch should return partial failures without aborting successful items.
@pytest.mark.asyncio
async def test_generate_batch_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp = _workspace_tmp_dir()
    try:
        monkeypatch.setenv("FAL_KEY", "Key test")
        factory = _ClientFactory(fail_request_ids={"req-2"})

        async def _fake_get_client():
            return factory.make()

        monkeypatch.setattr(server, "_get_client", _fake_get_client)
        ctx = _Ctx()

        with respx.mock(assert_all_called=False) as mock:
            mock.get(re.compile(r"https://cdn\.fal\.ai/.*")).mock(
                return_value=httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"IMG")
            )
            result = await server.generate_batch(
                ctx=ctx,
                model_id="fal-ai/flux/dev",
                prompt="batch item",
                count=3,
                output_dir=str(tmp / "batch"),
            )

        assert len(result["files"]) == 2
        assert len(result["failed"]) == 1
        assert result["failed"][0]["index"] == 2
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# Expected behavior: generate_compare should return per-model failures while preserving successes.
@pytest.mark.asyncio
async def test_generate_compare_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp = _workspace_tmp_dir()
    try:
        monkeypatch.setenv("FAL_KEY", "Key test")
        factory = _ClientFactory(fail_models={"fal-ai/bad/model"})

        async def _fake_get_client():
            return factory.make()

        monkeypatch.setattr(server, "_get_client", _fake_get_client)
        ctx = _Ctx()

        with respx.mock(assert_all_called=False) as mock:
            mock.get(re.compile(r"https://cdn\.fal\.ai/.*")).mock(
                return_value=httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"IMG")
            )
            result = await server.generate_compare(
                ctx=ctx,
                model_ids=["fal-ai/good/model", "fal-ai/bad/model"],
                prompt="compare item",
                output_dir=str(tmp / "compare"),
            )

        assert len(result["files"]) == 1
        assert len(result["failed"]) == 1
        assert result["failed"][0]["model_id"] == "fal-ai/bad/model"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
