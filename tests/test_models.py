from __future__ import annotations

import pytest
from pydantic import ValidationError

from genvoy import config
from genvoy.models import BatchInput, CompareInput, GenerateInput


# Expected behavior: valid generation input should parse successfully with defaults.
def test_generate_input_accepts_valid_payload() -> None:
    payload = GenerateInput(
        model_id="fal-ai/flux/dev",
        prompt="A cinematic mountain landscape at sunrise",
        output_path="./out/hero",
    )
    assert payload.model_id == "fal-ai/flux/dev"
    assert payload.params == {}


# Expected behavior: invalid model IDs should be rejected immediately at validation time.
def test_generate_input_rejects_invalid_model_id() -> None:
    with pytest.raises(ValidationError) as exc:
        GenerateInput(
            model_id="not a valid id",
            prompt="hello",
            output_path="./out/file",
        )
    assert "INVALID_MODEL_ID" in str(exc.value)


# Expected behavior: prompt length equal to MAX_PROMPT_LENGTH should be accepted.
def test_prompt_length_allows_exact_boundary() -> None:
    model = GenerateInput(
        model_id="fal-ai/flux/dev",
        prompt="x" * config.MAX_PROMPT_LENGTH,
        output_path="./out/file",
    )
    assert len(model.prompt) == config.MAX_PROMPT_LENGTH


# Expected behavior: prompt length above MAX_PROMPT_LENGTH should fail validation.
def test_prompt_length_rejects_above_boundary() -> None:
    with pytest.raises(ValidationError) as exc:
        GenerateInput(
            model_id="fal-ai/flux/dev",
            prompt="x" * (config.MAX_PROMPT_LENGTH + 1),
            output_path="./out/file",
        )
    assert "PROMPT_TOO_LONG" in str(exc.value)


# Expected behavior: batch input should enforce upper-bound count limit.
def test_batch_input_rejects_count_above_max() -> None:
    with pytest.raises(ValidationError):
        BatchInput(
            model_id="fal-ai/flux/dev",
            prompt="batch prompt",
            count=config.MAX_BATCH_COUNT + 1,
            output_dir="./out",
        )


# Expected behavior: compare input should accept exactly MAX_COMPARE_MODELS model IDs.
def test_compare_input_accepts_max_model_count_boundary() -> None:
    model_ids = [f"fal-ai/flux/dev-{idx}" for idx in range(config.MAX_COMPARE_MODELS)]
    payload = CompareInput(
        model_ids=model_ids,
        prompt="compare prompt",
        output_dir="./out",
    )
    assert len(payload.model_ids) == config.MAX_COMPARE_MODELS

