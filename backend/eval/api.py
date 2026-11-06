"""Local-only endpoints behind the /label pages. Mounted only when EVAL_TOOLS=true,
never in production: they read and write files under eval/."""

import asyncio
import hashlib
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.llm.client import LLMClient, get_llm_client
from app.parsing.extract import extract
from app.parsing.redact import redact_contacts
from app.parsing.service import parse_resume
from eval import store

router = APIRouter(prefix="/eval", tags=["eval (local only)"])

_text_cache: dict[str, str] = {}


def _document_text(doc_id: str) -> str:
    """Extracted, redacted text: what the parser (and the labeler) sees."""
    try:
        path = store.document_path(doc_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such document.") from exc
    data = path.read_bytes()
    key = hashlib.sha256(data).hexdigest()
    if key not in _text_cache:
        _text_cache[key] = redact_contacts(extract(data).text).text
    return _text_cache[key]


class DocumentDetail(BaseModel):
    document: store.Document
    text: str
    label: store.ParserLabel | None


@router.get("/documents")
async def documents() -> list[store.Document]:
    return store.list_documents()


@router.get("/documents/{doc_id}")
async def document(doc_id: str) -> DocumentDetail:
    text = await asyncio.to_thread(_document_text, doc_id)
    doc = next(d for d in store.list_documents() if d.id == doc_id)
    return DocumentDetail(document=doc, text=text, label=store.load_label(doc_id))


@router.post("/documents/{doc_id}/draft")
async def draft(
    doc_id: str, llm: Annotated[LLMClient, Depends(get_llm_client)]
) -> store.ParserLabel:
    """The parser's answer as a starting point. Not saved; the labeler corrects it."""
    text = await asyncio.to_thread(_document_text, doc_id)
    parsed = await parse_resume(text, llm)
    p = parsed.profile
    return store.ParserLabel(
        file=doc_id.partition(":")[2],
        seniority=p.seniority,
        roles=[
            store.LabelRole(title=r.title, company=r.company, start=r.start, end=r.end)
            for r in p.roles
        ],  # fmt: skip
        education=[
            store.LabelEducation(
                institution=e.institution, degree=e.degree, field=e.field, year=e.end
            )
            for e in p.education
        ],
        skills=p.skills,
        verified=False,
    )


@router.put("/documents/{doc_id}/label")
async def save(doc_id: str, label: store.ParserLabel) -> store.ParserLabel:
    try:
        store.save_label(doc_id, label)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such document.") from exc
    saved = store.load_label(doc_id)
    assert saved is not None
    return saved


class RelevanceState(BaseModel):
    pool: dict | None
    judgments: dict[str, dict[str, int]]


@router.get("/relevance")
async def relevance() -> RelevanceState:
    return RelevanceState(pool=store.load_pool(), judgments=store.load_judgments())


class Judgment(BaseModel):
    grade: Literal[0, 1, 2] | None  # None clears it


@router.put("/relevance/{resume_key}/{job_id}")
async def judge(resume_key: str, job_id: int, body: Judgment) -> dict[str, int]:
    pool = store.load_pool()
    entry = next((r for r in (pool or {}).get("resumes", []) if r["key"] == resume_key), None)
    if entry is None or job_id not in entry["jobs"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That job isn't in this resume's pool.")
    store.save_judgment(resume_key, job_id, body.grade)
    return store.load_judgments().get(resume_key, {})
