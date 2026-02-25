from __future__ import annotations

import logging
import sys

import pytest

from genvoy.config import configure_logging, get_settings


# Expected behavior: missing FAL_KEY should raise an explicit startup error when key is required.
def test_get_settings_raises_when_key_required_and_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAL_KEY", "")
    with pytest.raises(RuntimeError):
        get_settings(require_key=True)


# Expected behavior: raw keys should be normalized with "Key " prefix.
def test_get_settings_normalizes_raw_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAL_KEY", "abc123")
    settings = get_settings(require_key=True)
    assert settings.fal_key == "Key abc123"


# Expected behavior: pre-prefixed keys should remain unchanged.
def test_get_settings_keeps_prefixed_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FAL_KEY", "Key abc123")
    settings = get_settings(require_key=True)
    assert settings.fal_key == "Key abc123"


# Expected behavior: logging configuration should attach a stderr stream handler when none exist.
def test_configure_logging_targets_stderr() -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    try:
        root.handlers = []
        configure_logging()
        assert root.handlers, "configure_logging should add at least one handler"
        handler = root.handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr
    finally:
        root.handlers = original_handlers
