import pytest

from app.core.config import Settings, to_asyncpg_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "postgresql://u:p@ep-cool-1.eu-central-1.aws.neon.tech/db?sslmode=require&channel_binding=require",
            "postgresql+asyncpg://u:p@ep-cool-1.eu-central-1.aws.neon.tech/db?ssl=require",
        ),
        ("postgres://u:p@localhost:5432/db", "postgresql+asyncpg://u:p@localhost:5432/db"),
        (
            "postgresql+asyncpg://u:p@db:5432/matchlens",
            "postgresql+asyncpg://u:p@db:5432/matchlens",
        ),
    ],
)
def test_to_asyncpg_url(url: str, expected: str) -> None:
    assert to_asyncpg_url(url) == expected


def test_cors_origins_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://matchlens.vercel.app/, http://localhost:3100")
    settings = Settings(_env_file=None)
    assert settings.cors_origins == ["https://matchlens.vercel.app", "http://localhost:3100"]


def test_model_defaults_follow_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "gpt-oss:120b")
    monkeypatch.setenv("LLM_MODEL_FAST", "")
    monkeypatch.setenv("EMBED_PROVIDER", "openai")
    settings = Settings(_env_file=None)
    assert settings.llm_model_fast == "gpt-oss:120b"
    assert settings.embed_model == "text-embedding-3-small"


def test_api_key_is_not_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-very-secret")
    settings = Settings(_env_file=None)
    assert "sk-very-secret" not in repr(settings)
    assert settings.llm_api_key.get_secret_value() == "sk-very-secret"
