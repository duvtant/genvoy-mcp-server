# Genvoy MCP

Genvoy is a production-grade MCP server for fal.ai media workflows.

It gives AI agents a safe, structured interface to:
- discover fal.ai models,
- estimate cost,
- generate media,
- compare outputs across models,
- save outputs to local disk and optionally copy into a repo path.

Genvoy is built for local MCP usage first (BYOK: bring your own key).

## What Genvoy Does

Core tools:
1. `search_models` - find model IDs before generating (example: search `flux`).
2. `get_schema` - see exactly which inputs a model accepts before calling it.
3. `estimate_cost` - check likely cost first so you can decide to proceed or not.
4. `generate` - create one output from one prompt and save it to a file path.
5. `generate_batch` - create multiple variations on the same model in one call.
6. `generate_compare` - run one prompt across multiple models to compare results.
7. `get_job_status` - check progress for a previously submitted async request.
8. `cancel_job` - stop a queued/running request you no longer want.

Resources:
1. `genvoy://models` - quick read-only snapshot of model metadata.
2. `genvoy://recent` - quick read-only snapshot of recent usage (Admin key required).

Compatibility bridge tools (added by FastMCP `ResourcesAsTools` transform):
1. `list_resources` - lets clients discover resources even without native resource UI.
2. `read_resource` - fetch resource content directly by URI.

## Installation Modes

### Mode A: Local Source (development)

Run directly from this repo:

```bash
uv run python -m genvoy.server
```

### Mode B: Local Installed Package (still local)

Install package locally:

```bash
uv tool install .
```

Then run:

```bash
genvoy
```

### Mode C: Published Package via PyPI (still local by default)

After publishing, users can install and run locally (`uvx genvoy` or local install).

Important: publishing to PyPI does **not** mean a shared hosted server.
It still runs on each user's machine unless you deploy and host a central server yourself.

## Local vs Hosted Model

### Local MCP (current project focus)
- each user runs Genvoy locally,
- each user sets their own `FAL_KEY`,
- billing is on each user's fal account.

### Hosted shared MCP (optional future architecture)
- one centralized server serves many users,
- server key(s) are managed by you,
- billing and multi-tenant auth become your operational responsibility.

Genvoy currently targets Local MCP.

## Requirements

- Python `>=3.11`
- `uv`
- fal.ai API key in environment

Optional:
- fal.ai Admin API key scope if you need `genvoy://recent` / usage history.

## Configuration

Create `.env` in repo root:

```env
FAL_KEY="Key your_fal_key_here"
```

If you provide a key without `Key ` prefix, Genvoy auto-normalizes it.

## MCP Client Configuration

Use your client's MCP config to run the published package locally:

```json
{
  "mcpServers": {
    "genvoy": {
      "command": "uvx",
      "args": ["genvoy"],
      "env": {
        "FAL_KEY": "Key your_fal_key_here"
      }
    }
  }
}
```

For contributors (run directly from source in a cloned repo), use:

```json
{
  "mcpServers": {
    "genvoy-dev": {
      "command": "<path-to-repo>\\.venv\\Scripts\\python.exe",
      "args": ["-m", "genvoy.server"],
      "cwd": "<path-to-repo>",
      "env": {
        "FAL_KEY": "Key your_fal_key_here"
      }
    }
  }
}
```

## Output Path Behavior (Important)

Genvoy resolves relative output paths from the MCP process working directory (`cwd`).

What this means:
- in some IDEs, relative outputs may land in the IDE artifact/workspace folder,
- not automatically in your project repo root.

Use one of these patterns when you want deterministic placement:
1. set MCP `cwd` to your project root,
2. pass explicit absolute `output_path` / `repo_path`,
3. pass relative `repo_path` only when `cwd` is your repo root.

Security behavior:
- path traversal outside allowed root is blocked with `PATH_TRAVERSAL_BLOCKED`.

## Quick Validation Flow

In your MCP-enabled IDE, run:

1. `search_models` for `flux`
2. `get_schema` for `fal-ai/flux/dev`
3. `estimate_cost` for count `1`
4. `generate` with an `output_path`
5. `list_resources` then `read_resource` for `genvoy://models`

If using Admin scope key:
6. `read_resource` for `genvoy://recent`

## Tool Contract Snapshot

### `search_models`
- inputs: `query`, optional `category`, optional `cursor`
- compatibility alias: optional `page` (mapped to `cursor`)

### `get_schema`
- input: `model_id`

### `estimate_cost`
- input: `model_id`, optional `count` (default `1`)

### `generate`
- input: `model_id`, `prompt`, `output_path`, optional `repo_path`, optional `params`
- output: includes `output_path`, `repo_path`, `media_type`, `cost_usd`, `duration_ms`

### `generate_batch`
- input: `model_id`, `prompt`, `count`, `output_dir`, optional `repo_dir`, optional `params`
- output: `files[]` and `failed[]`

### `generate_compare`
- input: `model_ids[]`, `prompt`, `output_dir`, optional `repo_dir`, optional `params`
- output: `files[]` and `failed[]`

### `get_job_status`
- input: `request_id`, `model_id`

### `cancel_job`
- input: `request_id`, `model_id`

## Reliability and Safety

- queue-first fal.ai execution (`queue.fal.run`)
- SSE status stream with polling fallback
- rate-limit mapping (`RATE_LIMITED`)
- queue start timeout mapping (`QUEUE_START_TIMEOUT`)
- usage scope mapping (`ADMIN_KEY_REQUIRED`)
- non-blocking I/O (`httpx` async + `aiofiles`)
- output filename collision handling (`_1`, `_2`, ...)

## Development Commands

```bash
uv run ruff check .
uv run mypy genvoy
uv run pytest --cov --cov-report=term-missing
```

## Documentation Map

- System architecture: [`docs/architecture.md`](docs/architecture.md)
- Build/test/release phases: [`docs/setup.md`](docs/setup.md)
- Product-level behavior overview: [`docs/overview.md`](docs/overview.md)

## License

MIT
