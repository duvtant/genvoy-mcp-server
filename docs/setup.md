# Genvoy Setup and Release Guide

This guide defines the end-to-end path from local setup to release.
It is intentionally practical and implementation-oriented.

## Phase 1: Environment and Credentials

### 1. Install prerequisites

Required:
- Python `>=3.11`
- `uv`

Check:

```bash
python --version
uv --version
```

### 2. Create fal.ai key(s)

Required for all fal operations:
- API key (`FAL_KEY`)

Optional for usage history:
- Admin-scoped key (required for `genvoy://recent`)

### 3. Configure local environment

Create `.env` in repo root:

```env
FAL_KEY="Key your_fal_key_here"
```

Create `.env.example` with empty placeholder:

```env
FAL_KEY=""
```

### 4. Install dependencies

```bash
uv sync
```

Phase 1 checkpoint:

```bash
uv run python -c "from fastmcp import FastMCP; print('ok')"
```

## Phase 2: Core Implementation

Phase 2 is complete when these exist and operate:
- package modules in `genvoy/`
- 8 core tools
- 2 resources
- resources compatibility transform (`list_resources`, `read_resource`)

### Surface Reference (must match runtime)

Core tools:
- `search_models`: discover model IDs you can use (usually your first call).
- `get_schema`: confirm the model's accepted inputs before generating.
- `estimate_cost`: preview spend before committing to generation.
- `generate`: create one output and save it to the requested path.
- `generate_batch`: create multiple outputs on one model in one step.
- `generate_compare`: create outputs from multiple models for comparison.
- `get_job_status`: check state/progress of an async request.
- `cancel_job`: stop an async request that is still queued/running.

Resources:
- `genvoy://models`: read-only model metadata snapshot.
- `genvoy://recent`: read-only recent usage snapshot (Admin scope key required).

Local boot check:

```bash
uv run python -m genvoy.server
```

## Phase 3: Testing and QA

Non-negotiable testing principle:
- tests must prove correctness, not merely pass.

### Required test coverage dimensions

- Happy path
- Negative cases
- Edge cases
- Failure scenarios (dependency errors, timeouts, invalid responses)

### Test integrity rules

- Do not rewrite assertions to match broken output.
- Do not weaken test logic for convenience.
- Mock only true external boundaries.
- If internal mocking feels necessary, refactor design instead.

### Required quality gates

```bash
uv run ruff check .
uv run mypy genvoy
uv run pytest --cov --cov-report=term-missing
```

Phase 3 checkpoint:
- all gates pass,
- no skipped tests without explicit rationale,
- docs and implementation are behavior-consistent.

## Phase 4: Documentation, Packaging, and Release

### 1. Documentation hardening (must do before release)

Update and verify:
- `README.md`
- `docs/overview.md`
- `docs/architecture.md`
- `docs/setup.md`

Documentation standards:
- accurate to current behavior,
- explicit about path/cwd behavior,
- explicit about key scope requirements,
- readable by humans and machine agents.

### 2. Packaging metadata and build

Check `pyproject.toml`:
- package name/version
- script entrypoint: `genvoy = "genvoy.server:main"`

Build:

```bash
uv build
```

### 3. MCP client integration checks

Validate in at least one client (for example Antigravity/Cursor):
- tools load,
- generate works,
- resource bridge tools work,
- output paths behave as documented.

### 4. CI workflow

Set CI to require:
- `ruff`
- `mypy`
- `pytest`
- docs consistency review

### 5. Release mode decision

#### Option A: Publish package only (recommended now)

Publish to PyPI so users can install locally.
Users still run Genvoy on their machines with their own keys.

#### Option B: Host a shared centralized MCP server (future)

Only choose this if you want to run a multi-tenant service.
This requires separate auth, billing isolation, and operations controls.

Important:
- publishing to PyPI does **not** automatically create shared hosting.

Phase 4 checkpoint:
- package builds,
- docs are accurate,
- local install works,
- release model is explicitly documented.
