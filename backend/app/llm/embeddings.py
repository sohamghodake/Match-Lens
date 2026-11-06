"""Embedding providers. Both produce EMBED_DIM-wide vectors so they share one schema.

Resumes go through `embed_query` and job postings through `embed_documents`. Today both
providers embed the two sides identically (fastembed adds no instruction prefix for
bge-small, which suits resume-vs-job matching: long text on both sides). The split is
there so bge's query instruction, or an asymmetric model, can be A/B-tested in Phase 6
without touching callers.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

from openai import AsyncOpenAI

from app.core.config import EMBED_DIM, Settings, get_settings

if TYPE_CHECKING:
    from fastembed import TextEmbedding


class Embedder(Protocol):
    model_name: str
    dim: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """fastembed (ONNX on CPU, no PyTorch): small enough for a 512 MB server."""

    def __init__(
        self, model_name: str, *, cache_dir: str | None = None, batch_size: int = 32
    ) -> None:
        self.model_name = model_name
        self.dim = EMBED_DIM
        self._cache_dir = cache_dir
        self._batch_size = batch_size
        self._model: TextEmbedding | None = None
        self._lock = threading.Lock()

    def _load(self) -> TextEmbedding:
        # Loaded on first use, not at import: the model takes a few seconds to load
        # (and is downloaded the first time), which shouldn't slow API startup.
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self.model_name, cache_dir=self._cache_dir)
            return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []

        def run() -> list[list[float]]:
            vectors = self._load().passage_embed(list(texts), batch_size=self._batch_size)
            return [v.tolist() for v in vectors]

        return _check_dims(await asyncio.to_thread(run), self.dim, self.model_name)

    async def embed_query(self, text: str) -> list[float]:
        def run() -> list[list[float]]:
            return [v.tolist() for v in self._load().query_embed(text)]

        return _check_dims(await asyncio.to_thread(run), self.dim, self.model_name)[0]


class OpenAIEmbedder:
    """OpenAI embeddings, requested at EMBED_DIM dimensions to fit the vector columns."""

    MAX_BATCH = 256

    def __init__(
        self, model_name: str, *, base_url: str, api_key: str, client: AsyncOpenAI | None = None
    ) -> None:
        self.model_name = model_name
        self.dim = EMBED_DIM
        self.client = client or AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=60)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.MAX_BATCH):
            batch = list(texts[start : start + self.MAX_BATCH])
            response = await self.client.embeddings.create(
                model=self.model_name, input=batch, dimensions=self.dim
            )
            vectors += [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        return _check_dims(vectors, self.dim, self.model_name)

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed_documents([text]))[0]


def _check_dims(vectors: list[list[float]], dim: int, model: str) -> list[list[float]]:
    for vector in vectors:
        if len(vector) != dim:
            raise ValueError(
                f"{model} returned {len(vector)}-d vectors; the schema stores {dim}-d. "
                "Pick a model that outputs (or can be truncated to) that size."
            )
    return vectors


def build_embedder(settings: Settings) -> Embedder:
    assert settings.embed_model is not None  # filled in by Settings
    if settings.embed_provider == "openai":
        if settings.embed_api_key is None:
            raise ValueError("EMBED_PROVIDER=openai needs EMBED_API_KEY")
        return OpenAIEmbedder(
            settings.embed_model,
            base_url=settings.embed_base_url,
            api_key=settings.embed_api_key.get_secret_value(),
        )
    return LocalEmbedder(settings.embed_model, cache_dir=settings.embed_cache_dir)


@lru_cache
def get_embedder() -> Embedder:
    return build_embedder(get_settings())
