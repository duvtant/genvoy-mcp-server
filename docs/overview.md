# Genvoy Overview

## Summary

Genvoy is an MCP server that lets AI agents use fal.ai media models from inside coding IDEs.

It is designed for practical build workflows:
- discover a model,
- estimate cost,
- generate output,
- save output to local disk,
- optionally copy output into project paths.

## Primary Use Cases

1. Single asset generation
- "Create a logo and save it to a local path."

2. Batch generation on one model
- "Create 8 variants of this icon prompt."

3. Side-by-side model comparison
- "Run the same prompt on Flux, Recraft, and another model and compare outputs."

4. Cost-aware generation
- "Estimate cost first, then proceed only after confirmation."

## User Experience Goals

- Keep users in-editor (no dashboard hopping).
- Make model selection easier with `search_models`.
- Make generation safer with `estimate_cost`.
- Make delivery practical with `output_path` and optional `repo_path`/`repo_dir`.

## Output Location Model

Genvoy resolves relative paths from the MCP process working directory (`cwd`).

So in some IDEs, outputs may land in IDE-managed artifact folders by default.
This is expected and safe.

If users want outputs directly in a repo, they should:
1. run MCP with repo root as `cwd`, or
2. pass explicit absolute `repo_path` / `repo_dir`.

## Local First Deployment Model

Genvoy currently targets local MCP deployment:
- users run their own local Genvoy process,
- users provide their own `FAL_KEY`,
- usage/billing follows each user's key.

Publishing to PyPI is for distribution convenience, not central hosting.

## Operational Constraints

- API key required for fal.ai calls.
- Admin key scope required for usage-history resource (`genvoy://recent`).
- Batch and compare are bounded by configured limits in `config.py`.

## Current MCP Surface

Core tools:
- `search_models`: first step for discovery; use it to find model IDs by keyword.
- `get_schema`: check required/optional inputs so prompts and params are valid.
- `estimate_cost`: preview cost before spending credits.
- `generate`: create one output file from one prompt.
- `generate_batch`: create multiple variants on one model in a single request.
- `generate_compare`: run the same prompt on multiple models for side-by-side review.
- `get_job_status`: check progress/result state for an async request.
- `cancel_job`: stop work you no longer want to wait/pay for.

Resources:
- `genvoy://models`: read-only model metadata snapshot.
- `genvoy://recent`: read-only usage-history snapshot (Admin scope).

Compatibility bridge tools:
- `list_resources`: discover resources in clients that only support tools.
- `read_resource`: fetch resource payload by URI.

## Success Criteria

A "ready" integration should prove:
1. model discovery works,
2. cost estimate works,
3. generation returns saved files,
4. resource reading works in clients with and without native Resources support.
