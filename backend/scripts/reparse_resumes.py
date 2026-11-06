"""Re-parse stored resumes with the current parser (after a schema or prompt change).

    python -m scripts.reparse_resumes            # every resume that hasn't expired
    python -m scripts.reparse_resumes --id UUID  # just one

Uses the stored (already redacted) text, so no file is needed. Re-embeds the profile and
drops cached matches, which were computed from the old profile. One LLM call per resume.
"""

import argparse
import asyncio
import sys
import uuid

from sqlalchemy import delete, select

from app.db.models import MatchResult, Resume
from app.db.retention import resume_cutoff
from app.db.session import get_sessionmaker
from app.llm.client import get_llm_client
from app.llm.embeddings import get_embedder
from app.parsing.service import embedding_text, parse_resume


async def main(resume_id: uuid.UUID | None) -> int:
    llm, embedder = get_llm_client(), get_embedder()
    async with get_sessionmaker()() as session:
        query = select(Resume).where(Resume.created_at >= resume_cutoff())
        if resume_id:
            query = query.where(Resume.id == resume_id)
        resumes = list(await session.scalars(query))
        if not resumes:
            print("no resumes to re-parse")
            return 1
        for resume in resumes:
            parsed = await parse_resume(resume.text, llm)
            resume.parsed = parsed.profile.model_dump(mode="json")
            resume.embedding = await embedder.embed_query(embedding_text(parsed.profile))
            resume.embed_model = embedder.model_name
            resume.meta = {
                **resume.meta,
                "parse_method": parsed.method,
                "warnings": parsed.warnings,
            }
            await session.execute(delete(MatchResult).where(MatchResult.resume_id == resume.id))
            p = parsed.profile
            print(
                f"{resume.id}: {parsed.method}, {len(p.roles)} roles, {len(p.skills)} skills, "
                f"{len(p.projects)} projects, seniority {p.seniority}"
            )
            for project in p.projects:
                print(f"    project: {project.name} [{', '.join(project.skills[:6])}]")
        await session.commit()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--id", type=uuid.UUID)
    sys.exit(asyncio.run(main(parser.parse_args().id)))
