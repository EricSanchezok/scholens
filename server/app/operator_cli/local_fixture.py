"""Seed deterministic, local-only Scholens paper and project fixtures."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from uuid import UUID, uuid4

from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.bootstrap.adapters.project_repository import project_repository
from app.database.database import SessionLocal
from app.database.models import AuthUser, DocumentProcessingStatus, Project
from app.helpers.s3 import s3_service
from app.modules.papers.infrastructure.repository import document_repository


@dataclass(frozen=True, slots=True)
class LocalFixturePaper:
    filename: str
    title: str
    authors: tuple[str, ...]
    identifier: str


FIXTURE_PROJECT_TITLE = "Local demo · Reading workspace"
FIXTURE_PROJECT_DESCRIPTION = (
    "Deterministic Scholens local fixture. Source PDFs are CC BY 4.0 and are "
    "committed under server/evals/seed_data."
)

FIXTURE_PAPERS: tuple[LocalFixturePaper, ...] = (
    LocalFixturePaper(
        filename="chain_of_thought_for_reasoning.pdf",
        title="Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
        authors=(
            "Jason Wei",
            "Xuezhi Wang",
            "Dale Schuurmans",
            "Maarten Bosma",
            "Brian Ichter",
            "Fei Xia",
            "Ed H. Chi",
            "Quoc V. Le",
            "Denny Zhou",
        ),
        identifier="arXiv:2201.11903v6",
    ),
    LocalFixturePaper(
        filename="human_gpt_coding_course.pdf",
        title="A comparison of human, GPT-3.5, and GPT-4 performance in a university-level coding course",
        authors=("Will Yeadon", "Alex Peach", "Craig Testrow"),
        identifier="doi:10.1038/s41598-024-73634-y",
    ),
)


def _fixture_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "evals" / "seed_data"


def _extract_text(pdf_bytes: bytes) -> tuple[str, int]:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages), len(
        reader.pages
    )


def _get_or_create_project(db: Session, *, owner_id: int) -> Project:
    project = db.scalars(
        select(Project).where(
            Project.owner_id == owner_id,
            Project.title == FIXTURE_PROJECT_TITLE,
        )
    ).first()
    if project is not None:
        return project
    return project_repository.create(
        db,
        owner_id=owner_id,
        title=FIXTURE_PROJECT_TITLE,
        description=FIXTURE_PROJECT_DESCRIPTION,
    )


def seed_local_fixture(*, email: str) -> dict[str, object]:
    """Create or repair the deterministic local paper/project fixture.

    This command deliberately uses the existing document/reference repositories
    and the isolated dev S3 bucket. It never creates Identity users and is safe
    to repeat for the same account.
    """

    db = SessionLocal()
    try:
        user = db.scalar(select(AuthUser).where(AuthUser.email == email))
        if user is None:
            raise ValueError(f"Identity account {email} does not exist")
        if str(user.status) != "active" or user.email_verified_at is None:
            raise ValueError(f"Identity account {email} is not active and verified")

        project = _get_or_create_project(db, owner_id=user.id)
        document_ids: list[UUID] = []
        created_documents = 0
        created_library_entries = 0
        created_project_links = 0

        for fixture in FIXTURE_PAPERS:
            path = _fixture_directory() / fixture.filename
            if not path.is_file():
                raise FileNotFoundError(f"Local fixture PDF is missing: {path}")
            pdf_bytes = path.read_bytes()
            digest = hashlib.sha256(pdf_bytes).hexdigest()
            object_key = s3_service.upload_document_source(
                sha256=digest,
                pdf_bytes=pdf_bytes,
            )
            raw_content, page_count = _extract_text(pdf_bytes)
            canonical = document_repository.get_or_create(
                db,
                sha256=digest,
                original_filename=fixture.filename,
                mime_type="application/pdf",
                size_bytes=len(pdf_bytes),
                s3_object_key=object_key,
                created_by_id=user.id,
                processing_job_id=uuid4(),
            )
            document = canonical.document
            if canonical.created:
                created_documents += 1
            document.title = fixture.title
            document.authors = list(fixture.authors)
            document.doi = fixture.identifier
            document.raw_content = raw_content
            document.page_count = page_count
            document.processing_status = DocumentProcessingStatus.COMPLETED.value
            document.parser_backend = "pymupdf4llm"
            document.parser_quality = "text_only"
            document.parser_version = "local-fixture"
            document.processing_job_id = None
            document_ids.append(document.id)
            library_reference = document_repository.attach_library(
                db,
                document_id=document.id,
                user_id=user.id,
            )
            created_library_entries += int(library_reference.created)
            project_reference = document_repository.attach_project(
                db,
                document_id=document.id,
                project_id=project.id,
                added_by_id=user.id,
            )
            created_project_links += int(project_reference.created)

        db.commit()
        return {
            "email": email,
            "project_id": project.id,
            "project_title": project.title,
            "document_ids": document_ids,
            "documents": len(document_ids),
            "created_documents": created_documents,
            "created_library_entries": created_library_entries,
            "created_project_links": created_project_links,
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


__all__ = [
    "FIXTURE_PAPERS",
    "FIXTURE_PROJECT_TITLE",
    "seed_local_fixture",
]
