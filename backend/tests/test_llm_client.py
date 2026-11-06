from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel

from app.llm.client import LLMClient, LLMError, parse_json_object


class Profile(BaseModel):
    skills: list[str]
    years: float


class FakeCompletions:
    """Stands in for AsyncOpenAI().chat.completions: replays canned replies in order."""

    def __init__(self, replies: list[str | Exception]) -> None:
        self.replies = list(replies)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=reply))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )


def make_client(replies: list[str | Exception]) -> tuple[LLMClient, FakeCompletions]:
    completions = FakeCompletions(replies)
    fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = LLMClient(
        base_url="http://fake/v1",
        api_key="x",
        model="big",
        model_fast="small",
        client=fake,  # type: ignore[arg-type]
    )
    return client, completions


async def test_valid_json_first_try() -> None:
    client, completions = make_client(['{"skills": ["Python"], "years": 4}'])
    result = await client.structured_detailed("resume text", Profile)

    assert result.value == Profile(skills=["Python"], years=4)
    assert result.attempts == 1
    assert (result.prompt_tokens, result.completion_tokens) == (100, 20)
    call = completions.calls[0]
    assert call["model"] == "big"
    assert call["response_format"] == {"type": "json_object"}
    system = call["messages"][0]["content"]
    assert "JSON" in system  # OpenAI's JSON mode rejects prompts without the word
    assert '"skills"' in system  # schema is included


async def test_repair_retry_sends_validation_error_back() -> None:
    client, completions = make_client(
        ['{"skills": "Python", "years": "four"}', '{"skills": ["Python"], "years": 4}']
    )
    result = await client.structured_detailed("resume text", Profile)

    assert result.value.years == 4
    assert result.attempts == 2
    assert (result.prompt_tokens, result.completion_tokens) == (200, 40)
    retry_messages = completions.calls[1]["messages"]
    assert retry_messages[-2] == {
        "role": "assistant",
        "content": '{"skills": "Python", "years": "four"}',
    }
    assert "years" in retry_messages[-1]["content"]  # the validation error names the field


async def test_gives_up_after_one_repair() -> None:
    client, completions = make_client(["not json", "still not json"])
    with pytest.raises(LLMError, match="invalid output twice"):
        await client.structured("resume text", Profile)
    assert len(completions.calls) == 2


async def test_fast_flag_uses_fast_model() -> None:
    client, completions = make_client(['{"skills": [], "years": 0}'])
    await client.structured("x", Profile, fast=True)
    assert completions.calls[0]["model"] == "small"


async def test_provider_errors_become_llm_errors_without_retry() -> None:
    quota = openai.RateLimitError(
        "quota",
        response=httpx.Response(429, request=httpx.Request("POST", "http://fake/v1")),
        body={"message": "You exceeded your current quota", "code": "insufficient_quota"},
    )
    client, completions = make_client([quota])
    with pytest.raises(LLMError, match="HTTP 429: You exceeded your current quota"):
        await client.structured("x", Profile)
    assert len(completions.calls) == 1  # a bad key or empty quota won't fix itself


@pytest.mark.parametrize(
    "content",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        '```\n{"a": 1}\n```',
        'Sure! Here is the JSON:\n{"a": 1}\nLet me know if you need more.',
    ],
)
def test_parse_json_object_tolerates_wrapping(content: str) -> None:
    assert parse_json_object(content) == {"a": 1}


@pytest.mark.parametrize("content", ["", "   ", "[1, 2]", "no braces here", "{broken"])
def test_parse_json_object_rejects_non_objects(content: str) -> None:
    with pytest.raises(ValueError):
        parse_json_object(content)


def test_prompt_schema_is_flat() -> None:
    from app.llm.client import prompt_schema

    class Inner(BaseModel):
        title: str  # a field named "title" must survive title-stripping

    class Outer(BaseModel):
        items: list[Inner]

    schema = prompt_schema(Outer)
    assert "$defs" not in str(schema) and "$ref" not in str(schema)
    assert schema["properties"]["items"]["items"]["properties"]["title"] == {"type": "string"}
    assert "title" not in schema  # metadata title dropped
