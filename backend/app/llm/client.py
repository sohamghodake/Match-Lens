"""One client for every OpenAI-compatible provider: OpenAI, local Ollama, Ollama cloud.

Structured output uses JSON mode (`response_format={"type": "json_object"}`) plus
Pydantic validation rather than strict `json_schema`, because Ollama documents JSON
mode but not strict schemas. When validation fails, the model gets one repair attempt
with the validation error appended; after that the caller receives an `LLMError` and
falls back to rule-based logic.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings

log = logging.getLogger(__name__)

DEFAULT_SYSTEM = "You are a precise information-extraction assistant."
MAX_ERROR_CHARS = 2000


class LLMError(RuntimeError):
    """The provider failed, or returned output that stayed invalid after the repair retry."""


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    model: str
    attempts: int  # 1, or 2 when the repair retry was needed
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None


class LLMClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        model_fast: str | None = None,
        timeout: float = 120.0,
        max_retries: int = 2,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.model_fast = model_fast or model
        self.client = client or AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=max_retries
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> LLMClient:
        return cls(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key.get_secret_value(),
            model=settings.llm_model,
            model_fast=settings.llm_model_fast,
            timeout=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    async def structured[T: BaseModel](
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        fast: bool = False,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> T:
        """Ask for a JSON object matching `schema`; return it validated."""
        result = await self.structured_detailed(
            prompt, schema, system=system, fast=fast, model=model,
            reasoning_effort=reasoning_effort,
        )  # fmt: skip
        return result.value

    async def structured_detailed[T: BaseModel](
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        fast: bool = False,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> StructuredResult[T]:
        """Like `structured`, plus the attempt count, latency and token usage.

        `reasoning_effort` ("low" / "medium" / "high") is sent only when given: reasoning
        models such as gpt-oss accept it, and "low" cuts their hidden thinking tokens,
        which count against per-minute token limits.
        """
        model_name = model or (self.model_fast if fast else self.model)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _system_prompt(system, schema)},
            {"role": "user", "content": prompt},
        ]
        started = time.perf_counter()
        prompt_tokens = completion_tokens = 0
        usage_seen = False
        last_error = ""

        for attempt in (1, 2):
            content, usage = await self._complete(model_name, messages, reasoning_effort)
            if usage is not None:
                usage_seen = True
                prompt_tokens += usage.prompt_tokens or 0
                completion_tokens += usage.completion_tokens or 0
            try:
                value = schema.model_validate(parse_json_object(content))
            except (ValueError, ValidationError) as exc:
                last_error = str(exc)[:MAX_ERROR_CHARS]
                log.warning(
                    "LLM output failed validation (model=%s, attempt=%d): %s",
                    model_name,
                    attempt,
                    last_error.splitlines()[0] if last_error else "",
                )
                messages += [
                    {"role": "assistant", "content": content or ""},
                    {
                        "role": "user",
                        "content": (
                            "Your previous reply was not a valid JSON object for the schema. "
                            f"Error:\n{last_error}\n\n"
                            "Reply again with only the corrected JSON object."
                        ),
                    },
                ]
                continue
            return StructuredResult(
                value=value,
                model=model_name,
                attempts=attempt,
                latency_ms=round((time.perf_counter() - started) * 1000),
                prompt_tokens=prompt_tokens if usage_seen else None,
                completion_tokens=completion_tokens if usage_seen else None,
            )

        raise LLMError(f"{model_name} returned invalid output twice; last error: {last_error}")

    async def _complete(
        self, model: str, messages: list[dict[str, str]], reasoning_effort: str | None = None
    ) -> tuple[str, Any]:
        extra = {"reasoning_effort": reasoning_effort} if reasoning_effort else None
        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,  # type: ignore[arg-type]
                response_format={"type": "json_object"},
                extra_body=extra,
            )
        except openai.APIStatusError as exc:
            # e.g. 401 bad key, 404 unknown model, 429 rate limit / insufficient_quota.
            raise LLMError(
                f"{model} at {self.base_url} returned HTTP {exc.status_code}: {_error_text(exc)}"
            ) from exc
        except (openai.APITimeoutError, openai.APIConnectionError) as exc:
            raise LLMError(f"could not reach {self.base_url}: {exc}") from exc

        if not response.choices:
            return "", response.usage
        return response.choices[0].message.content or "", response.usage


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse a JSON object from model output, tolerating code fences and stray prose."""
    text = content.strip()
    if not text:
        raise ValueError("empty response")
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError(f"no JSON object in response: {content[:200]!r}") from None
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON: {exc}") from None
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
    return parsed


def _system_prompt(system: str | None, schema: type[BaseModel]) -> str:
    # JSON mode on OpenAI requires the word "JSON" to appear in the messages.
    return (
        f"{system or DEFAULT_SYSTEM}\n\n"
        "Respond with a single JSON object and nothing else: no prose, no markdown. "
        "It must validate against this JSON Schema:\n"
        f"{json.dumps(prompt_schema(schema), separators=(',', ':'))}"
    )


def prompt_schema(schema: type[BaseModel]) -> dict[str, Any]:
    """The model's JSON Schema with `$ref`s inlined and metadata titles dropped.

    Small models copy `$defs` / `$ref` plumbing into their answers instead of following
    it (qwen2.5:3b returned `{"$defs/LLMEducation": ...}`); a flat schema avoids that.
    """
    full = schema.model_json_schema()
    defs = full.get("$defs", {})

    def resolve(node: Any, depth: int = 0) -> Any:
        if depth > 20:  # recursive models would loop forever
            return node
        if isinstance(node, dict):
            if "$ref" in node:
                target = defs[node["$ref"].rsplit("/", 1)[-1]]
                merged = {**target, **{k: v for k, v in node.items() if k != "$ref"}}
                return resolve(merged, depth + 1)
            return {
                key: resolve(value, depth + 1)
                for key, value in node.items()
                # "title" metadata is a string; a field *named* title is a dict.
                if key != "$defs" and not (key == "title" and isinstance(value, str))
            }
        if isinstance(node, list):
            return [resolve(item, depth + 1) for item in node]
        return node

    return resolve(full)


def _error_text(exc: openai.APIStatusError) -> str:
    body = exc.body
    if isinstance(body, dict):
        err = body.get("error", body)
        if isinstance(err, dict):
            return str(err.get("message") or err.get("code") or err)
        return str(err)
    return exc.message


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient.from_settings(get_settings())
