from __future__ import annotations
from pathlib import Path

import pytest
from fastmcp.server.transforms import ResourcesAsTools

import genvoy.server as server


# Expected behavior: MCP server must register 8 core tools plus resource bridge tools from ResourcesAsTools.
@pytest.mark.asyncio
async def test_mcp_registration_contract() -> None:
    tools = await server.mcp.list_tools()
    resources = await server.mcp.list_resources()

    tool_names = {tool.name for tool in tools}
    resource_uris = {str(resource.uri) for resource in resources}

    assert tool_names == {
        "search_models",
        "get_schema",
        "estimate_cost",
        "generate",
        "generate_batch",
        "generate_compare",
        "get_job_status",
        "cancel_job",
        "list_resources",
        "read_resource",
    }
    assert resource_uris == {"genvoy://models", "genvoy://recent"}


# Expected behavior: server should enable ResourcesAsTools compatibility transform for clients without resource support.
def test_server_enables_resources_as_tools_transform() -> None:
    assert any(isinstance(transform, ResourcesAsTools) for transform in server.mcp.transforms)


# Expected behavior: startup should fail fast before server run if FAL_KEY is missing.
def test_main_fails_fast_without_fal_key(monkeypatch: pytest.MonkeyPatch) -> None:
    run_called = False

    def _fake_run() -> None:
        nonlocal run_called
        run_called = True

    monkeypatch.setenv("FAL_KEY", "")
    monkeypatch.setattr(server.mcp, "run", _fake_run)

    with pytest.raises(RuntimeError):
        server.main()
    assert run_called is False


# Expected behavior: startup should call MCP run when FAL_KEY is present.
def test_main_starts_when_fal_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    run_called = False

    def _fake_run() -> None:
        nonlocal run_called
        run_called = True

    monkeypatch.setenv("FAL_KEY", "abc123")
    monkeypatch.setattr(server.mcp, "run", _fake_run)

    server.main()
    assert run_called is True


# Expected behavior: server source should not use print(), preserving stdout for MCP JSON-RPC only.
def test_server_source_avoids_print_statements() -> None:
    source = Path("genvoy/server.py").read_text(encoding="utf-8")
    assert "print(" not in source


# Expected behavior: resource methods should return JSON string payloads when client calls succeed.
@pytest.mark.asyncio
async def test_resource_methods_return_json_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeClient:
        async def list_models(self):
            return {"models": [{"endpoint_id": "fal-ai/flux/dev"}]}

        async def list_recent(self):
            return {"usage": []}

        async def aclose(self):
            return None

    async def _fake_get_client():
        return _FakeClient()

    monkeypatch.setattr(server, "_get_client", _fake_get_client)
    models_payload = await server.models_resource()
    recent_payload = await server.recent_resource()

    assert '"models"' in models_payload
    assert '"usage"' in recent_payload
