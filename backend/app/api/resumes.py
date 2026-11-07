import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ratelimit import rate_limit
from app.db.models import Resume
from app.db.retention import RESUME_RETENTION, resume_cutoff
from app.db.session import get_session
from app.llm.client import LLMClient, get_llm_client
from app.llm.embeddings import Embedder, get_embedder
from app.parsing.extract import UnsupportedFile, extract
from app.parsing.redact import redact_contacts
from app.parsing.schema import ResumeProfile
from app.parsing.service import embedding_text, parse_resume

log = logging.getLogger(__name__)

router = APIRouter(prefix="/resumes", tags=["resumes"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SAMPLE_RESUME = Path(__file__).parents[1] / "assets" / "sample_resume.pdf"
MIN_TEXT_CHARS = 200  # less than this is almost always a scanned (image-only) PDF


class FileInfo(BaseModel):
    kind: Literal["pdf", "docx"]
    pages: int | None
    columns: int
    tables: int
    chars: int
    has_email: bool
    has_phone: bool
    has_linkedin: bool


class ResumeOut(BaseModel):
    id: uuid.UUID
    created_at: datetime
    expires_at: datetime
    profile: ResumeProfile
    parse_method: Literal["llm", "fallback"]
    warnings: list[str]
    file: FileInfo
    sample: bool = False  # the shared demo resume, not someone's upload


def to_out(resume: Resume) -> ResumeOut:
    meta: dict[str, Any] = resume.meta
    return ResumeOut(
        id=resume.id,
        created_at=resume.created_at,
        expires_at=resume.created_at + RESUME_RETENTION,
        profile=ResumeProfile.model_validate(resume.parsed),
        parse_method=meta["parse_method"],
        warnings=meta["warnings"],
        file=FileInfo.model_validate(meta["file"]),
        sample=bool(meta.get("sample")),
    )


async def _store_resume(
    data: bytes,
    session: AsyncSession,
    llm: LLMClient,
    embedder: Embedder,
    extra_meta: dict[str, Any] | None = None,
) -> Resume:
    """Extract, redact, parse, embed and store one resume file."""
    try:
        extracted = await asyncio.to_thread(extract, data)  # CPU-bound; keep the loop free
    except UnsupportedFile as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    if len(extracted.text) < MIN_TEXT_CHARS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No readable text found. If this is a scanned PDF, export a text-based PDF "
            "from your editor instead.",
        )

    # Contact details are removed before the text goes to the LLM or the database.
    redacted = redact_contacts(extracted.text)
    parsed = await parse_resume(redacted.text, llm)

    vector, embed_model, warnings = None, None, list(parsed.warnings)
    try:
        vector = await embedder.embed_query(embedding_text(parsed.profile))
        embed_model = embedder.model_name
    except Exception:
        log.exception("resume embedding failed")
        warnings.append("Couldn't compute the matching embedding; matches may be unavailable.")

    resume = Resume(
        text=redacted.text,
        parsed=parsed.profile.model_dump(mode="json"),
        embedding=vector,
        embed_model=embed_model,
        meta={
            "parse_method": parsed.method,
            "warnings": warnings,
            "file": {
                "kind": extracted.kind,
                "pages": extracted.pages,
                "columns": extracted.columns,
                "tables": extracted.tables,
                "chars": len(extracted.text),
                "has_email": redacted.emails > 0,
                "has_phone": redacted.phones > 0,
                "has_linkedin": redacted.has_linkedin,
            },
            **(extra_meta or {}),
        },
    )
    session.add(resume)
    await session.commit()
    await session.refresh(resume)
    return resume


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={413: {}, 415: {}, 422: {}, 429: {}},
    dependencies=[Depends(rate_limit("upload", "rate_limit_uploads_per_hour"))],
)
async def upload_resume(
    file: Annotated[UploadFile, File(description="PDF or DOCX, up to 5 MB")],
    session: Annotated[AsyncSession, Depends(get_session)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
) -> ResumeOut:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 5 MB.")
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty.")
    return to_out(await _store_resume(data, session, llm, embedder))


@router.post(
    "/sample",
    responses={429: {}},
    dependencies=[Depends(rate_limit("sample", "rate_limit_samples_per_hour"))],
)
async def sample_resume(
    session: Annotated[AsyncSession, Depends(get_session)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
) -> ResumeOut:
    """The demo's shared sample resume (a fictional backend engineer). Parsed once and
    reused until it expires, so its matches are cached too: most visitors trying the demo
    cost no LLM requests."""
    existing = await session.scalar(
        select(Resume)
        .where(Resume.meta["sample"].as_boolean(), Resume.created_at >= resume_cutoff())
        .order_by(Resume.created_at.desc())
        .limit(1)
    )
    if existing is not None:
        return to_out(existing)
    data = await asyncio.to_thread(SAMPLE_RESUME.read_bytes)
    return to_out(await _store_resume(data, session, llm, embedder, {"sample": True}))


@router.get("/{resume_id}", responses={404: {}})
async def get_resume(
    resume_id: uuid.UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> ResumeOut:
    resume = await session.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.created_at >= resume_cutoff())
    )
    if resume is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Resume not found or expired.")
    return to_out(resume)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(
    resume_id: uuid.UUID, session: Annotated[AsyncSession, Depends(get_session)]
) -> Response:
    await session.execute(delete(Resume).where(Resume.id == resume_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
