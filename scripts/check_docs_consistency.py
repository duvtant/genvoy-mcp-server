from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

CORE_TOOLS = [
    "search_models",
    "get_schema",
    "estimate_cost",
    "generate",
    "generate_batch",
    "generate_compare",
    "get_job_status",
    "cancel_job",
]
RESOURCES = ["genvoy://models", "genvoy://recent"]
BRIDGE_TOOLS = ["list_resources", "read_resource"]

DOC_FILES = {
    "README": ROOT / "README.md",
    "OVERVIEW": ROOT / "docs" / "overview.md",
    "ARCH": ROOT / "docs" / "architecture.md",
    "SETUP": ROOT / "docs" / "setup.md",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _require_contains(label: str, text: str, token: str, errors: list[str]) -> None:
    if token not in text:
        errors.append(f"{label}: missing `{token}`")


def _check_docs() -> list[str]:
    errors: list[str] = []
    data = {label: _read(path) for label, path in DOC_FILES.items()}

    for label, text in data.items():
        for tool in CORE_TOOLS:
            _require_contains(label, text, tool, errors)
        for resource in RESOURCES:
            _require_contains(label, text, resource, errors)

    for label in ("README", "ARCH", "SETUP"):
        for bridge_tool in BRIDGE_TOOLS:
            _require_contains(label, data[label], bridge_tool, errors)

    _require_contains("README", data["README"], "ADMIN_KEY_REQUIRED", errors)
    _require_contains("ARCH", data["ARCH"], "ADMIN_KEY_REQUIRED", errors)
    _require_contains("README", data["README"], "cursor", errors)
    _require_contains("ARCH", data["ARCH"], "cursor", errors)
    _require_contains("README", data["README"], "page", errors)
    _require_contains("ARCH", data["ARCH"], "deprecated alias", errors)

    mojibake_pattern = re.compile(r"â€”|â†’|Ã—|â€‹")
    for label, text in data.items():
        if mojibake_pattern.search(text):
            errors.append(f"{label}: contains mojibake characters")

    return errors


def main() -> int:
    errors = _check_docs()
    if errors:
        print("Docs consistency check failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Docs consistency check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
