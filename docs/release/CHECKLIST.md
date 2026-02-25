# Release Checklist

Use this checklist before cutting any `v*` tag.

## 1. Versioning

- [ ] Update `version` in `pyproject.toml`.
- [ ] Confirm `genvoy/__init__.py` still resolves version correctly.

## 2. Quality gates (local)

- [ ] `uv run python scripts/check_docs_consistency.py`
- [ ] `uv run ruff check .`
- [ ] `uv run mypy genvoy`
- [ ] `uv run pytest --cov --cov-report=term-missing`

## 3. Build artifacts

- [ ] Build package (`uv build`)
- [ ] Verify `dist/` contains `.whl` and `.tar.gz`

## 4. Documentation

- [ ] `README.md` reflects current behavior.
- [ ] `docs/architecture.md`, `docs/setup.md`, `docs/overview.md` are consistent.
- [ ] Local-vs-hosted model explanation remains explicit.

## 5. Integration smoke

- [ ] Confirm MCP client loads all tools/resources.
- [ ] Confirm at least one real generation completes.
- [ ] Confirm `genvoy://recent` behavior with Admin vs non-Admin key.

## 6. Tag and publish

- [ ] Create annotated tag: `git tag vX.Y.Z`
- [ ] Push tag: `git push origin vX.Y.Z`
- [ ] Verify GitHub `Publish` workflow succeeded.
- [ ] Verify package is available on PyPI.

## 7. Post-release

- [ ] Add release notes entry from template.
- [ ] Announce upgrade command (`uvx genvoy` / `uv tool upgrade genvoy`).
