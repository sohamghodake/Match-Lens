"""Known OpenAI-compatible providers, used by the smoke script to test several at once.

The app itself only ever uses the provider in LLM_BASE_URL / LLM_API_KEY / LLM_MODEL;
these presets just save typing when comparing providers.
"""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    base_url: str
    api_key_env: str | None  # None: the provider ignores the key (local Ollama)
    default_model: str

    def api_key(self) -> str | None:
        if self.api_key_env is None:
            return "ollama"
        return os.environ.get(self.api_key_env) or None


PRESETS: dict[str, ProviderPreset] = {
    p.name: p
    for p in (
        ProviderPreset("openai", "https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-5.4-mini"),
        ProviderPreset(
            "ollama-local",
            # Inside docker compose, the host's Ollama is at host.docker.internal.
            os.environ.get("OLLAMA_LOCAL_BASE_URL", "http://localhost:11434/v1"),
            None,
            "qwen2.5:7b",
        ),
        ProviderPreset("ollama-cloud", "https://ollama.com/v1", "OLLAMA_API_KEY", "gpt-oss:120b"),
    )
}
