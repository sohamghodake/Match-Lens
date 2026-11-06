import math
import os
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.config import EMBED_DIM, Settings
from app.llm.embeddings import LocalEmbedder, OpenAIEmbedder, build_embedder


class FakeEmbeddings:
    def __init__(self, dim: int = EMBED_DIM) -> None:
        self.dim = dim
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        # Return items out of order to check they're re-sorted by index.
        items = [
            SimpleNamespace(index=i, embedding=[float(i)] * self.dim)
            for i in range(len(kwargs["input"]))
        ]
        return SimpleNamespace(data=list(reversed(items)))


def openai_embedder(dim: int = EMBED_DIM) -> tuple[OpenAIEmbedder, FakeEmbeddings]:
    fake = FakeEmbeddings(dim)
    embedder = OpenAIEmbedder(
        "text-embedding-3-small",
        base_url="http://fake/v1",
        api_key="x",
        client=SimpleNamespace(embeddings=fake),  # type: ignore[arg-type]
    )
    return embedder, fake


async def test_openai_embedder_batches_and_requests_schema_dims() -> None:
    embedder, fake = openai_embedder()
    texts = [f"job {i}" for i in range(300)]
    vectors = await embedder.embed_documents(texts)

    assert len(vectors) == 300
    assert [len(c["input"]) for c in fake.calls] == [256, 44]
    assert all(c["dimensions"] == EMBED_DIM for c in fake.calls)
    assert vectors[0][0] == 0.0 and vectors[255][0] == 255.0 and vectors[256][0] == 0.0


async def test_wrong_dimension_is_rejected() -> None:
    embedder, _ = openai_embedder(dim=1536)
    with pytest.raises(ValueError, match="1536-d"):
        await embedder.embed_query("x")


def test_openai_provider_requires_key() -> None:
    with pytest.raises(ValueError, match="EMBED_API_KEY"):
        build_embedder(Settings(_env_file=None, embed_provider="openai"))


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("RUN_SLOW"), reason="set RUN_SLOW=1 to load fastembed")
async def test_local_embedder_ranks_related_text_higher() -> None:
    embedder = LocalEmbedder("BAAI/bge-small-en-v1.5", cache_dir=os.environ.get("EMBED_CACHE_DIR"))
    query = await embedder.embed_query("Python backend engineer with FastAPI")
    related, unrelated = await embedder.embed_documents(
        ["Hiring a backend developer for Python and FastAPI services", "Bakery seeks a pastry chef"]
    )

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        return dot / (math.hypot(*a) * math.hypot(*b))

    assert len(query) == EMBED_DIM
    assert cosine(query, related) > cosine(query, unrelated) + 0.1
