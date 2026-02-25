from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import httpx

from genvoy.errors import GenvoyToolError

EXT_TO_MEDIA: dict[str, str] = {
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".mp4": "video",
    ".mp3": "audio",
    ".wav": "audio",
    ".flac": "audio",
}

CONTENT_TYPE_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
}


@dataclass(frozen=True)
class DownloadResult:
    path: Path
    media_type: str
    file_size_bytes: int
    content_type: str | None


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_safe_path(path: Path, cwd: Path | None = None) -> Path:
    root = (cwd or Path.cwd()).resolve()
    resolved = path.resolve()
    if not _is_within(resolved, root):
        raise GenvoyToolError(
            "PATH_TRAVERSAL_BLOCKED",
            f"Resolved path '{resolved}' is outside working directory '{root}'.",
        )
    return resolved


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    idx = 1
    while True:
        candidate = parent / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def detect_type_and_ext(url: str, content_type: str | None = None) -> tuple[str, str | None]:
    parsed = urlparse(url)
    ext = Path(parsed.path).suffix.lower()
    media_type = EXT_TO_MEDIA.get(ext, "unknown")
    if media_type != "unknown":
        return media_type, ext

    if not content_type:
        return "unknown", None
    norm = content_type.split(";")[0].strip().lower()
    canonical_ext = CONTENT_TYPE_TO_EXT.get(norm)
    if not canonical_ext:
        return "unknown", None
    return EXT_TO_MEDIA.get(canonical_ext, "unknown"), canonical_ext


def resolve_output_path(output_path: str | Path, preferred_ext: str | None = None) -> Path:
    raw = Path(output_path)
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    raw.parent.mkdir(parents=True, exist_ok=True)
    safe = ensure_safe_path(raw)
    if not safe.suffix and preferred_ext:
        safe = safe.with_suffix(preferred_ext)
    return unique_path(safe)


async def download_to_file(
    url: str,
    output_path: Path,
    headers: dict[str, str] | None = None,
    timeout_seconds: float = 120.0,
) -> DownloadResult:
    retries = [0.5, 1.0, 2.0]
    attempt = 0
    while True:
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
                async with client.stream("GET", url, headers=headers or {}) as response:
                    if response.status_code in {403, 404}:
                        raise GenvoyToolError("CDN_EXPIRED", "CDN URL expired or inaccessible.")
                    response.raise_for_status()

                    content_type = response.headers.get("Content-Type")
                    media_type, ext = detect_type_and_ext(url, content_type)
                    path = output_path
                    if not path.suffix and ext:
                        path = unique_path(path.with_suffix(ext))
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path = ensure_safe_path(path)

                    total = 0
                    async with aiofiles.open(path, "wb") as f:
                        async for chunk in response.aiter_bytes():
                            total += len(chunk)
                            await f.write(chunk)

                    return DownloadResult(
                        path=path,
                        media_type=media_type,
                        file_size_bytes=total,
                        content_type=content_type,
                    )
        except GenvoyToolError:
            raise
        except httpx.HTTPStatusError as exc:
            raise GenvoyToolError("DOWNLOAD_FAILED", f"CDN download failed: {exc}") from exc
        except httpx.HTTPError as exc:
            if attempt >= len(retries):
                raise GenvoyToolError("DOWNLOAD_FAILED", f"CDN download failed: {exc}") from exc
            await asyncio.sleep(retries[attempt])
            attempt += 1


async def copy_to_repo(src: Path, dst: str | Path) -> Path:
    target = Path(dst)
    if not target.is_absolute():
        target = Path.cwd() / target
    target.parent.mkdir(parents=True, exist_ok=True)
    target = ensure_safe_path(target)
    target = unique_path(target)
    await asyncio.to_thread(shutil.copy2, src, target)
    return target

