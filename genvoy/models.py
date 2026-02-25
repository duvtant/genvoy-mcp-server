from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from genvoy import config

MODEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


class GenerateInput(BaseModel):
    model_id: str
    prompt: str
    output_path: str
    repo_path: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        if not MODEL_ID_PATTERN.match(value):
            raise ValueError("INVALID_MODEL_ID")
        return value

    @field_validator("prompt")
    @classmethod
    def validate_prompt_length(cls, value: str) -> str:
        if len(value) > config.MAX_PROMPT_LENGTH:
            raise ValueError("PROMPT_TOO_LONG")
        return value


class BatchInput(BaseModel):
    model_id: str
    prompt: str
    count: int = Field(ge=1, le=config.MAX_BATCH_COUNT)
    output_dir: str
    repo_dir: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        if not MODEL_ID_PATTERN.match(value):
            raise ValueError("INVALID_MODEL_ID")
        return value

    @field_validator("prompt")
    @classmethod
    def validate_prompt_length(cls, value: str) -> str:
        if len(value) > config.MAX_PROMPT_LENGTH:
            raise ValueError("PROMPT_TOO_LONG")
        return value


class CompareInput(BaseModel):
    model_ids: list[str] = Field(min_length=2, max_length=config.MAX_COMPARE_MODELS)
    prompt: str
    output_dir: str
    repo_dir: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("model_ids")
    @classmethod
    def validate_model_ids(cls, value: list[str]) -> list[str]:
        for model_id in value:
            if not MODEL_ID_PATTERN.match(model_id):
                raise ValueError("INVALID_MODEL_ID")
        return value

    @field_validator("prompt")
    @classmethod
    def validate_prompt_length(cls, value: str) -> str:
        if len(value) > config.MAX_PROMPT_LENGTH:
            raise ValueError("PROMPT_TOO_LONG")
        return value


class SearchModelsInput(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    category: str | None = None
    cursor: str | None = None
    page: str | None = None

    @model_validator(mode="after")
    def normalize_cursor(self) -> "SearchModelsInput":
        # Backward compatibility: accept `page` as a deprecated alias for `cursor`.
        if self.cursor and self.page and self.cursor != self.page:
            raise ValueError("AMBIGUOUS_PAGINATION_CURSOR")
        if self.cursor is None:
            self.cursor = self.page
        return self


class EstimateCostInput(BaseModel):
    model_id: str
    count: int = Field(default=1, ge=1)

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        if not MODEL_ID_PATTERN.match(value):
            raise ValueError("INVALID_MODEL_ID")
        return value


class JobLookupInput(BaseModel):
    request_id: str = Field(min_length=1)
    model_id: str

    @field_validator("model_id")
    @classmethod
    def validate_model_id(cls, value: str) -> str:
        if not MODEL_ID_PATTERN.match(value):
            raise ValueError("INVALID_MODEL_ID")
        return value


class GenerateResult(BaseModel):
    request_id: str
    output_path: str
    repo_path: str | None = None
    media_type: Literal["image", "video", "audio", "unknown"]
    file_size_kb: float
    model_id: str
    cost_usd: float | None = None
    duration_ms: int | None = None
    result_url: str


class BatchResult(BaseModel):
    files: list[GenerateResult]
    failed: list[dict[str, Any]]


class CompareResult(BaseModel):
    files: list[GenerateResult]
    failed: list[dict[str, Any]]
