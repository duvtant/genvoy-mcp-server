from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

MAX_PROMPT_LENGTH = 10_000
MAX_BATCH_COUNT = 10
MAX_COMPARE_MODELS = 6
MAX_CONCURRENT_JOBS = 8


@dataclass(frozen=True)
class Settings:
    fal_key: str


def configure_logging(level: int = logging.INFO) -> None:
    """Send all Python logs to stderr to keep stdout clean for JSON-RPC."""
    root = logging.getLogger()
    root.setLevel(level)
    if root.handlers:
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root.addHandler(handler)


def get_settings(*, require_key: bool = False) -> Settings:
    load_dotenv()
    key = os.getenv("FAL_KEY", "").strip()
    if key and not key.lower().startswith("key "):
        key = f"Key {key}"

    if require_key and not key:
        raise RuntimeError("FAL_KEY is required but not set.")

    return Settings(fal_key=key)


configure_logging()

