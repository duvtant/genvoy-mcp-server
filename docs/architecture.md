# Genvoy Architecture

## 1. Purpose

This document is the technical source of truth for Genvoy runtime behavior.
It explains module responsibilities, runtime data flow, safety boundaries, and tool contracts.

## 2. Technology Choices

- FastMCP 3.x: MCP server framework, tool/resource registration, compatibility transforms.
- httpx (async): fal.ai API calls and queue polling/streaming.
- aiofiles: non-blocking file write for downloaded media.
- pydantic v2: request/response validation and schema generation.
- pathlib: normalized path handling across platforms.
- python-dotenv: environment variable loading.

## 3. High-Level Components

### `genvoy/config.py`
- loads `FAL_KEY`
- normalizes key prefix to `Key ...`
- configures logging to stderr
- defines limits:
  - `MAX_PROMPT_LENGTH`
  - `MAX_BATCH_COUNT`
  - `MAX_COMPARE_MODELS`
  - `MAX_CONCURRENT_JOBS`

### `genvoy/errors.py`
- defines `GenvoyToolError` with stable error code

### `genvoy/models.py`
- pydantic models for tool inputs/outputs
- includes `cursor` pagination field and legacy `page` alias normalization

### `genvoy/fal_client.py`
- only module that calls fal.ai HTTP endpoints
- platform API usage:
  - `/v1/models`
  - `/v1/models/pricing`
  - `/v1/models/pricing/estimate`
  - `/v1/models/usage`
- queue API usage:
  - submit, status, status stream, result, cancel
- maps HTTP and protocol failures to structured tool errors

### `genvoy/filesystem.py`
- output path resolution
- path traversal blocking
- unique filename collision handling
- media type detection via URL extension and content-type fallback
- CDN download to local disk
- optional copy to repo path

### `genvoy/server.py`
- defines MCP tools/resources
- orchestrates queue -> completion -> download -> optional repo copy
- applies `ResourcesAsTools` transform for client compatibility

## 4. MCP Surface

### Core tools
1. `search_models`: discovery entrypoint for finding usable model IDs.
2. `get_schema`: contract lookup for valid per-model input fields.
3. `estimate_cost`: preflight cost check before queue submission.
4. `generate`: single-run orchestration from queue submit to local file write.
5. `generate_batch`: repeated single-run orchestration on one model.
6. `generate_compare`: repeated single-run orchestration across multiple models.
7. `get_job_status`: queue status passthrough for previously submitted requests.
8. `cancel_job`: queue cancellation passthrough for submitted requests.

### Resources
1. `genvoy://models`: read-only resource projection of model metadata.
2. `genvoy://recent`: read-only resource projection of usage history (Admin scope).

### Compatibility bridge tools
Automatically exposed by transform:
1. `list_resources`: compatibility bridge for clients that only enumerate tools.
2. `read_resource`: compatibility bridge for clients that read resources via tool call.

## 5. Tool Contracts

### `search_models`
Inputs:
- `query` (required)
- `category` (optional)
- `cursor` (optional)
- `page` (optional, deprecated alias; mapped to `cursor`)

Behavior:
- rejects conflicting `cursor` + `page` values
- calls `GET /v1/models` with `q`, optional `category`, optional `cursor`

### `get_schema`
Input:
- `model_id`

Behavior:
- fetches openapi schema from `GET /v1/models?endpoint_id=...&expand=openapi-3.0`

### `estimate_cost`
Inputs:
- `model_id`
- `count` (default `1`)

Behavior:
- fetches pricing and estimate payloads from platform pricing endpoints

### `generate`
Inputs:
- `model_id`
- `prompt`
- `output_path`
- optional `repo_path`
- optional `params`

Behavior:
- submits queue job
- waits for completion using SSE stream first, polling fallback second
- fetches result URL
- downloads media to resolved output path
- optionally copies file to `repo_path`

Output fields include:
- `output_path`
- `repo_path`
- `media_type`
- `file_size_kb`
- `model_id`
- `cost_usd`
- `duration_ms`
- `result_url`

### `generate_batch`
Inputs:
- `model_id`, `prompt`, `count`, `output_dir`
- optional `repo_dir`, optional `params`

Behavior:
- starts N parallel generate pipelines
- returns partial successes and failures

### `generate_compare`
Inputs:
- `model_ids[]` (2..`MAX_COMPARE_MODELS`)
- `prompt`, `output_dir`
- optional `repo_dir`, optional `params`

Behavior:
- runs same prompt across multiple models in parallel
- returns per-model success/failure lists

### `get_job_status`
Inputs:
- `request_id`, `model_id`

Behavior:
- proxy to queue status endpoint

### `cancel_job`
Inputs:
- `request_id`, `model_id`

Behavior:
- proxy to queue cancel endpoint
- returns provider response payload

## 6. Output Path and Workspace Semantics

This is critical for IDE behavior.

- Relative paths are resolved from process `cwd`.
- If IDE runs MCP in its own workspace/artifact folder, outputs go there.
- This is expected behavior, not a bug.

Safety:
- resolved path must stay within allowed root (`cwd`) or request is blocked with `PATH_TRAVERSAL_BLOCKED`.
- filename collisions are auto-incremented.

Practical implication:
- use explicit absolute paths or configure MCP `cwd` when you need deterministic repo placement.

## 7. Error Model

All user-visible failures are raised as `GenvoyToolError(code, message)`.

Representative codes:
- `MISSING_FAL_KEY`
- `INVALID_MODEL_ID`
- `PROMPT_TOO_LONG`
- `AMBIGUOUS_PAGINATION_CURSOR`
- `RATE_LIMITED`
- `QUEUE_START_TIMEOUT`
- `MODEL_NOT_FOUND`
- `CDN_EXPIRED`
- `DOWNLOAD_FAILED`
- `PATH_TRAVERSAL_BLOCKED`
- `ADMIN_KEY_REQUIRED` (usage endpoint scope mismatch)

## 8. Authentication Model

- all fal requests send `Authorization: Key ...`
- most tools work with normal API key scope
- `genvoy://recent` (`/v1/models/usage`) requires Admin scope key

## 9. Concurrency and Performance

- global semaphore (`MAX_CONCURRENT_JOBS`) bounds parallel execution
- `generate_batch` and `generate_compare` use `asyncio.gather`
- non-blocking network and file I/O prevents event-loop stalls

## 10. Release and Deployment Model

Current target: local MCP package distribution.

- publishing to PyPI enables easier installation (`uvx genvoy`),
- but each user still runs local process and uses their own key by default.

A shared hosted multi-tenant server is a different architecture and is not part of current scope.
