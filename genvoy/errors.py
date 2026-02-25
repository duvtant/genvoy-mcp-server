from __future__ import annotations

from fastmcp.exceptions import ToolError


class GenvoyToolError(ToolError):
    """ToolError carrying a stable machine-readable code."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def ensure(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise GenvoyToolError(code, message)

