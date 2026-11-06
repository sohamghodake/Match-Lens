import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import EMBED_DIM, Settings
from app.db.models import Resume
from app.db.retention import purge_expired_resumes
from app.db.session import get_session
from app.llm.client import LLMError, get_llm_client
from app.llm.embeddings import get_embedder
from app.main import create_app
from app.parsing.schema import LLMResume, LLMRole

SAMPLES = Path(__file__).parents[1] / "eval" / "samples"


class FakeLLM:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.prompts: list[str] = []

    async def structured[T: BaseModel](self, prompt: str, schema: type[T], **_: object) -> T:
        self.prompts.append(prompt)
        if self.fail:
            raise LLMError("provider down")
        return LLMResume(  # type: ignore[return-value]
            headline="Software Development Engineer II",
            seniority="mid",
            skills=["Java", "Postgres"],
            roles=[
                LLMRole(
                    title="Software Development Engineer II",
                    company="Zentrix Technologies",
                    start="June 2022",
                    end="Present",
                )
            ],
        )


class FakeEmbedder:
    model_name = "fake-embedder"
    dim = EMBED_DIM

    async def embed_query(self, text: str) -> list[float]:
        return [0.1] * EMBED_DIM

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * EMBED_DIM for _ in texts]


@pytest.fixture
def llm() -> FakeLLM:
    return FakeLLM()


@pytest.fixture
def app(settings: Settings, llm: FakeLLM):
    app = create_app(settings, run_sweeper=False)
    app.dependency_overrides[get_llm_client] = lambda: llm
    app.dependency_overrides[get_embedder] = lambda: FakeEmbedder()
    return app


def client_for(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def upload(app, name: str, data: bytes) -> httpx.Response:
    async with client_for(app) as client:
        return await client.post("/resumes", files={"file": (name, data)})


# ── Validation (no database needed) ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("data", "status", "detail"),
    [
        (b"", 422, "The file is empty."),
        (b"plain text resume", 415, "Upload a PDF or DOCX file."),
        (b"%PDF-1.4\n" + b"\x00" * (5 * 1024 * 1024), 413, "The file is larger than 5 MB."),
    ],
)
async def test_upload_rejections(app, data: bytes, status: int, detail: str) -> None:
    response = await upload(app, "resume.pdf", data)
    assert response.status_code == status
    assert response.json()["detail"] == detail


async def test_oversized_request_is_rejected_before_parsing(app) -> None:
    async with client_for(app) as client:
        response = await client.post(
            "/resumes",
            content=b"x" * 10,
            headers={"content-length": str(7 * 1024 * 1024), "content-type": "multipart/form-data"},
        )
    assert response.status_code == 413


async def test_image_only_pdf_is_rejected(app, tmp_path: Path) -> None:
    from reportlab.pdfgen import canvas

    path = tmp_path / "scan.pdf"
    pdf = canvas.Canvas(str(path))
    pdf.rect(50, 50, 200, 200)
    pdf.save()
    response = await upload(app, "scan.pdf", path.read_bytes())
    assert response.status_code == 422
    assert "scanned PDF" in response.json()["detail"]


# ── Full flow against Postgres ────────────────────────────────────────────────────


@pytest.fixture
def db_app(app, db_session: AsyncSession):
    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    return app


@pytest.mark.db
async def test_upload_get_delete(db_app, db_session: AsyncSession, llm: FakeLLM) -> None:
    data = (SAMPLES / "priya_nair_fullstack.docx").read_bytes()
    response = await upload(db_app, "priya.docx", data)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["parse_method"] == "llm"
    assert body["profile"]["skills"] == ["Java", "PostgreSQL"]
    assert body["profile"]["roles"][0]["start"] == "2022-06"
    assert body["file"] == {
        "kind": "docx", "pages": None, "columns": 1, "tables": 0, "chars": body["file"]["chars"],
        "has_email": True, "has_phone": True, "has_linkedin": True,
    }  # fmt: skip
    created = datetime.fromisoformat(body["created_at"])
    assert datetime.fromisoformat(body["expires_at"]) - created == timedelta(hours=24)

    # Neither the LLM nor the database ever sees the email or phone number.
    stored = await db_session.scalar(select(Resume).where(Resume.id == uuid.UUID(body["id"])))
    assert stored is not None
    for secret in ("priya.nair@example.com", "98765"):
        assert secret not in stored.text
        assert secret not in llm.prompts[0]
    assert stored.embed_model == "fake-embedder" and stored.embedding is not None

    async with client_for(db_app) as client:
        assert (await client.get(f"/resumes/{body['id']}")).json() == body
        assert (await client.delete(f"/resumes/{body['id']}")).status_code == 204
        assert (await client.get(f"/resumes/{body['id']}")).status_code == 404
        assert (await client.delete(f"/resumes/{body['id']}")).status_code == 204  # idempotent


@pytest.mark.db
async def test_llm_outage_still_returns_a_profile(db_app, llm: FakeLLM) -> None:
    llm.fail = True
    response = await upload(db_app, "alex.pdf", (SAMPLES / "alex_chen_backend.pdf").read_bytes())
    assert response.status_code == 201
    body = response.json()
    assert body["parse_method"] == "fallback"
    assert "PostgreSQL" in body["profile"]["skills"]
    assert body["warnings"]


@pytest.mark.db
async def test_expired_resumes_are_hidden_then_purged(db_app, db_session: AsyncSession) -> None:
    old = Resume(
        text="old",
        parsed={},
        meta={},
        created_at=datetime.now(UTC) - timedelta(hours=25),
    )
    fresh = Resume(text="fresh", parsed={}, meta={})
    db_session.add_all([old, fresh])
    await db_session.flush()

    async with client_for(db_app) as client:
        assert (await client.get(f"/resumes/{old.id}")).status_code == 404

    assert await purge_expired_resumes(db_session) == 1
    remaining = (await db_session.scalars(select(Resume.id))).all()
    assert old.id not in remaining and fresh.id in remaining
