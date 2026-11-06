"""Labeling tools (eval/store.py, eval/api.py) and the report's precision maths.

Every test points the store at a temporary folder, so real labels are never touched.
"""

import json
import shutil
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.llm.client import get_llm_client
from app.main import create_app
from app.parsing.schema import LLMResume, LLMRole
from eval import report, store

SAMPLES = Path(__file__).parents[1] / "eval" / "samples"


@pytest.fixture
def folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    samples = tmp_path / "samples"
    samples.mkdir()
    shutil.copy(SAMPLES / "alex_chen_backend.pdf", samples)
    all_labels = json.loads((SAMPLES / "labels.json").read_text())
    labels = [item for item in all_labels if item["file"] == "alex_chen_backend.pdf"]
    (samples / "labels.json").write_text(json.dumps(labels))
    private = tmp_path / "private"
    (private / "resumes").mkdir(parents=True)
    shutil.copy(SAMPLES / "priya_nair_fullstack.docx", private / "resumes" / "friend.docx")
    (private / "resumes" / "notes.txt").write_text("not a resume")
    for name, path in {
        "SAMPLES": samples, "PRIVATE": private, "PRIVATE_RESUMES": private / "resumes",
        "PRIVATE_LABELS": private / "labels", "RELEVANCE": private / "relevance",
        "CACHE": private / "cache",
    }.items():  # fmt: skip
        monkeypatch.setattr(store, name, path)
    return tmp_path


def test_documents_and_label_lifecycle(folders: Path) -> None:
    docs = {d.id: d.status for d in store.list_documents()}
    assert docs == {"sample:alex_chen_backend.pdf": "verified", "private:friend.docx": "none"}

    label = store.ParserLabel(file="ignored", roles=[store.LabelRole(title="SDE", company="X")])
    store.save_label("private:friend.docx", label)
    assert store.load_label("private:friend.docx").file == "friend.docx"  # type: ignore[union-attr]
    assert {d.id: d.status for d in store.list_documents()}["private:friend.docx"] == "draft"

    store.save_label("private:friend.docx", label.model_copy(update={"verified": True}))
    assert set(store.verified_labels()) == {"sample:alex_chen_backend.pdf", "private:friend.docx"}


@pytest.mark.parametrize(
    "doc_id",
    [
        "private:../labels/x.pdf",
        "private:notes.txt",
        "other:friend.docx",
        "private:",
        "private:.env",
    ],
)
def test_document_path_rejects_anything_else(folders: Path, doc_id: str) -> None:
    with pytest.raises(KeyError):
        store.document_path(doc_id)


def test_sample_labels_are_read_only(folders: Path) -> None:
    with pytest.raises(PermissionError):
        store.save_label("sample:alex_chen_backend.pdf", store.ParserLabel(file="x"))


def test_judgments_save_and_clear(folders: Path) -> None:
    store.save_judgment("private:friend.docx", 7, 2)
    store.save_judgment("private:friend.docx", 8, 0)
    store.save_judgment("private:friend.docx", 7, None)
    assert store.load_judgments() == {"private:friend.docx": {"8": 0}}


class FakeLLM:
    async def structured[T: BaseModel](self, prompt: str, schema: type[T], **_: object) -> T:
        return LLMResume(  # type: ignore[return-value]
            seniority="mid", skills=["Java"],
            roles=[LLMRole(title="SDE II", company="Zentrix", start="June 2022", end="Present")],
        )  # fmt: skip


async def test_api(folders: Path, settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"eval_tools": True}), run_sweeper=False)
    app.dependency_overrides[get_llm_client] = lambda: FakeLLM()
    store.save_pool(
        {"k": 10, "systems": ["vector"], "jobs": {"5": {}},
         "resumes": [{"key": "private:friend.docx", "profile": "", "runs": {}, "jobs": [5]}]}
    )  # fmt: skip
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        detail = (await c.get("/eval/documents/private:friend.docx")).json()
        draft = (await c.post("/eval/documents/private:friend.docx/draft")).json()
        saved = await c.put(
            "/eval/documents/private:friend.docx/label", json={**draft, "verified": True}
        )
        sample_write = await c.put("/eval/documents/sample:alex_chen_backend.pdf/label", json=draft)
        judged = await c.put("/eval/relevance/private:friend.docx/5", json={"grade": 1})
        not_in_pool = await c.put("/eval/relevance/private:friend.docx/6", json={"grade": 1})

    assert "[email]" in detail["text"] and "Zentrix" in detail["text"]  # redacted, like the parser
    assert detail["label"] is None
    assert draft["roles"] == [
        {"title": "SDE II", "company": "Zentrix", "start": "2022-06", "end": "present"}
    ]
    assert draft["verified"] is False
    assert saved.status_code == 200 and saved.json()["verified"] is True
    assert sample_write.status_code == 403
    assert judged.json() == {"5": 1} and not_in_pool.status_code == 404


async def test_eval_routes_are_absent_by_default(settings: Settings) -> None:
    app = create_app(settings, run_sweeper=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/eval/documents")).status_code == 404


def test_precision_and_ranking_table() -> None:
    grades = {"1": 2, "2": 1, "3": 0}
    assert report.precision_at_k([1, 2, 3, 4], grades, k=10, threshold=2) == 0.1
    assert report.precision_at_k([1, 2, 3, 4], grades, k=10, threshold=1) == 0.2

    pool = {
        "k": 2,
        "systems": ["vector", "hybrid"],
        "resumes": [
            {"key": "a", "runs": {"vector": [1, 2], "hybrid": [3, 1]}, "jobs": [1, 2, 3]},
            {"key": "b", "runs": {"vector": [4], "hybrid": [4]}, "jobs": [4]},  # not judged
        ],
    }
    table, judged = report.ranking_table(pool, {"a": {"1": 2, "2": 1, "3": 0}})
    assert judged == 1
    assert "| vector | 0.50 | 1.00 |" in table and "| hybrid | 0.50 | 0.50 |" in table
