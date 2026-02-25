from __future__ import annotations

from pathlib import Path
import shutil
import uuid

import httpx
import pytest
import respx

from genvoy.errors import GenvoyToolError
from genvoy.filesystem import (
    detect_type_and_ext,
    download_to_file,
    ensure_safe_path,
    unique_path,
)


def _workspace_tmp_dir() -> Path:
    base = Path.cwd() / ".pytest_codex_tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"fs-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


# Expected behavior: known URL extension should determine media type without content-type fallback.
def test_detect_type_and_ext_from_url_extension() -> None:
    media_type, ext = detect_type_and_ext("https://cdn.fal.ai/file/output.mp4?token=abc")
    assert media_type == "video"
    assert ext == ".mp4"


# Expected behavior: ambiguous URL should use content-type fallback to infer type/extension.
def test_detect_type_and_ext_from_content_type_fallback() -> None:
    media_type, ext = detect_type_and_ext("https://cdn.fal.ai/file/noext", "image/png; charset=utf-8")
    assert media_type == "image"
    assert ext == ".png"


# Expected behavior: paths resolving outside working directory should be blocked.
def test_ensure_safe_path_blocks_path_traversal() -> None:
    tmp = _workspace_tmp_dir()
    try:
        root = tmp / "root"
        root.mkdir()
        outside = tmp / "outside.txt"
        outside.touch()
        with pytest.raises(GenvoyToolError) as exc:
            ensure_safe_path(outside, cwd=root)
        assert exc.value.code == "PATH_TRAVERSAL_BLOCKED"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# Expected behavior: filename collisions should produce deterministic auto-incremented names.
def test_unique_path_auto_increments() -> None:
    tmp = _workspace_tmp_dir()
    try:
        first = tmp / "hero.png"
        first.write_bytes(b"x")
        second = unique_path(first)
        assert second.name == "hero_1.png"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# Expected behavior: successful CDN download should write bytes to disk and infer extension when missing.
@pytest.mark.asyncio
async def test_download_to_file_success() -> None:
    tmp = _workspace_tmp_dir()
    try:
        url = "https://cdn.fal.ai/artifact/abc"
        with respx.mock(assert_all_called=True) as mock:
            mock.get(url).mock(
                return_value=httpx.Response(
                    200,
                    headers={"Content-Type": "image/png"},
                    content=b"PNGDATA",
                )
            )
            result = await download_to_file(url, tmp / "result")

        assert result.path.exists()
        assert result.path.suffix == ".png"
        assert result.media_type == "image"
        assert result.file_size_bytes == len(b"PNGDATA")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# Expected behavior: CDN 403/404 responses should be surfaced as CDN_EXPIRED tool errors.
@pytest.mark.asyncio
async def test_download_to_file_cdn_expired() -> None:
    tmp = _workspace_tmp_dir()
    try:
        url = "https://cdn.fal.ai/artifact/expired"
        with respx.mock(assert_all_called=True) as mock:
            mock.get(url).mock(return_value=httpx.Response(404, content=b"missing"))
            with pytest.raises(GenvoyToolError) as exc:
                await download_to_file(url, tmp / "result.png")
        assert exc.value.code == "CDN_EXPIRED"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
