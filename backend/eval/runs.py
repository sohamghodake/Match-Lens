"""Cached parser runs: one parse per (document, model), reused by every report."""

import asyncio
import hashlib
import json
import re

from app.llm.client import LLMClient
from app.parsing.extract import extract
from app.parsing.redact import redact_contacts
from app.parsing.schema import ResumeProfile
from app.parsing.service import parse_resume
from eval import store


def _slug(model: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.-]+", "_", model)


async def parsed_profile(doc_id: str, llm: LLMClient, *, refresh: bool = False) -> ResumeProfile:
    data = await asyncio.to_thread(store.document_path(doc_id).read_bytes)
    key = hashlib.sha256(data).hexdigest()[:16]
    path = store.CACHE / "parse" / _slug(llm.model) / f"{key}.json"
    if path.is_file() and not refresh:
        return ResumeProfile.model_validate_json(path.read_text())
    text = redact_contacts(extract(data).text).text
    parsed = await parse_resume(text, llm)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**parsed.profile.model_dump(mode="json")}, indent=1))
    return parsed.profile
