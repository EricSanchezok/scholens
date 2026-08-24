"""Explicit persistence boundary for canonical documents and logical references."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import false, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, load_only, selectinload

from app.database.models import (
    AuthUser,
    Document,
    DocumentProcessingStatus,
    DurableJob,
    LibraryPaper,
    PaperStatus,
    ProjectPaper,
    UploadReservation,
)
from app.helpers.postgres import sanitize_for_postgres
from app.modules.papers.application.contracts.documents import (
    DocumentUpdate,
    LibraryPaperUpdateRequest,
)
from app.modules.papers.domain import normalize_doi
from app.modules.papers.infrastructure.access import (
    get_document_access,
    require_document_access,
)
from app.modules.papers.infrastructure.document_loading import (
    DOCUMENT_LIBRARY_RESPONSE_COLUMNS,
    DOCUMENT_PUBLIC_SHARE_COLUMNS,
    DOCUMENT_RESPONSE_COLUMNS,
    DocumentColumns,
)
from app.shared.application import Actor
from app.shared.domain import AppError, FailureKind


@dataclass(frozen=True, slots=True)
class CanonicalDocumentResult:
    document: Document
    created: bool


@dataclass(frozen=True, slots=True)
class ReferenceResult:
    created: bool


@dataclass(frozen=True, slots=True)
class PublicLibraryPaper:
    entry: LibraryPaper
    document: Document
    owner: AuthUser


@dataclass(frozen=True, slots=True)
class UpdatedLibraryPaper:
    library_entry_id: uuid.UUID
    document_id: uuid.UUID
    changed: bool


class DocumentRepository:
    def find_accessible(
        self,
        db: Session,
        *,
        document_id: object,
        user: Actor,
        update_last_accessed: bool = False,
        document_columns: DocumentColumns = DOCUMENT_RESPONSE_COLUMNS,
    ) -> Document | None:
        """Return an authorized Document with an explicit bounded column profile.

        Metadata is the safe default. Consumers of parsed content must pass one
        of the content profiles from ``document_loading`` deliberately.
        """
        try:
            parsed_id = uuid.UUID(str(document_id))
        except (TypeError, ValueError):
            return None
        access = get_document_access(
            db,
            document_id=parsed_id,
            user_id=user.id,
            document_columns=document_columns,
        )
        if access is None:
            return None
        if update_last_accessed and access.library_paper is not None:
            access.library_paper.last_accessed_at = datetime.now(timezone.utc)
            db.flush()
        return access.document

    def update_canonical(
        self,
        db: Session,
        *,
        document: Document,
        update: DocumentUpdate,
        user: Actor | None = None,
        refresh_result: bool = True,
    ) -> Document:
        """Update canonical metadata after optional explicit access validation."""
        if user is not None:
            require_document_access(
                db,
                document_id=document.id,
                user_id=user.id,
            )
        values = update.model_dump(exclude_unset=True)
        sanitized = sanitize_for_postgres(values)
        for field, value in sanitized.items():
            setattr(document, field, value)
        if refresh_result:
            db.flush()
            db.refresh(document)
        else:
            db.flush()
        return document

    def find_by_upload_job(
        self,
        db: Session,
        *,
        upload_job_id: str,
        user: Actor,
    ) -> Document | None:
        """Return the Document produced by one of the user's durable jobs."""
        return db.scalar(
            select(Document)
            .join(DurableJob, DurableJob.document_id == Document.id)
            .join(UploadReservation, UploadReservation.id == DurableJob.id)
            .where(
                UploadReservation.id == upload_job_id,
                DurableJob.requested_by_id == user.id,
            )
        )

    def list_available_library_documents(
        self,
        db: Session,
        *,
        user: Actor,
        query: str | None = None,
        document_ids: list[str] | None = None,
    ) -> list[Document]:
        statement = (
            select(Document)
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .where(
                LibraryPaper.user_id == user.id,
                Document.ts_vector.isnot(None),
            )
        )
        if document_ids:
            statement = statement.where(Document.id.in_(document_ids))
        if query:
            ts_query = func.to_tsquery("english", " & ".join(query.split()))
            statement = statement.where(Document.ts_vector.op("@@")(ts_query))
        return list(db.scalars(statement.order_by(Document.updated_at.desc())).all())

    def find_library_document_by_doi(
        self,
        db: Session,
        *,
        user_id: int,
        doi: str,
    ) -> Document | None:
        normalized = normalize_doi(doi)
        if not normalized:
            return None
        escaped = (
            normalized.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        return db.scalars(
            select(Document)
            .join(LibraryPaper, LibraryPaper.document_id == Document.id)
            .options(
                load_only(
                    Document.id,
                    Document.s3_object_key,
                    raiseload=True,
                )
            )
            .where(
                LibraryPaper.user_id == user_id,
                func.lower(Document.doi).like(f"%{escaped}", escape="\\"),
            )
        ).first()

    def list_library(self, db: Session, *, user_id: int) -> list[LibraryPaper]:
        return list(
            db.scalars(
                select(LibraryPaper)
                .options(
                    selectinload(LibraryPaper.document).load_only(
                        *DOCUMENT_LIBRARY_RESPONSE_COLUMNS,
                        raiseload=True,
                    ),
                    selectinload(LibraryPaper.tags),
                )
                .where(LibraryPaper.user_id == user_id)
                .order_by(LibraryPaper.updated_at.desc(), LibraryPaper.id.desc())
            ).all()
        )

    def require_library_paper(
        self,
        db: Session,
        *,
        library_paper_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> LibraryPaper:
        statement = select(LibraryPaper).where(
            LibraryPaper.id == library_paper_id,
            LibraryPaper.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        entry = db.scalar(statement)
        if entry is None:
            raise AppError(
                code="library_paper_not_found",
                message="Library paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        return entry

    def require_library_paper_by_document(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> LibraryPaper:
        statement = (
            select(LibraryPaper)
            .options(
                selectinload(LibraryPaper.document).load_only(
                    *DOCUMENT_LIBRARY_RESPONSE_COLUMNS,
                    raiseload=True,
                ),
                selectinload(LibraryPaper.tags),
            )
            .where(
                LibraryPaper.document_id == document_id,
                LibraryPaper.user_id == user_id,
            )
        )
        if for_update:
            statement = statement.with_for_update()
        entry = db.scalar(statement)
        if entry is None:
            raise AppError(
                code="library_paper_not_found",
                message="Library paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        return entry

    def require_library_paper_id_by_document(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        for_update: bool = False,
    ) -> uuid.UUID:
        """Resolve a Library mutation target without hydrating relationships."""

        statement = select(LibraryPaper.id).where(
            LibraryPaper.document_id == document_id,
            LibraryPaper.user_id == user_id,
        )
        if for_update:
            statement = statement.with_for_update()
        entry_id = db.scalar(statement)
        if entry_id is None:
            raise AppError(
                code="library_paper_not_found",
                message="Library paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        return entry_id

    def update_library_paper(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
        request: LibraryPaperUpdateRequest,
    ) -> UpdatedLibraryPaper:
        change_checks = []
        if request.status is not None:
            change_checks.append(
                LibraryPaper.status.is_distinct_from(request.status.value)
            )
        metadata_overrides: dict[str, object] | None = None
        if request.metadata_overrides is not None:
            metadata_overrides = request.metadata_overrides.model_dump(
                mode="json",
                exclude_none=True,
            )
            change_checks.append(
                LibraryPaper.metadata_overrides.is_distinct_from(metadata_overrides)
            )
        changed_expression = or_(*change_checks) if change_checks else false()
        row = db.execute(
            select(
                LibraryPaper.id.label("library_entry_id"),
                LibraryPaper.document_id,
                changed_expression.label("changed"),
            )
            .where(
                LibraryPaper.document_id == document_id,
                LibraryPaper.user_id == user_id,
            )
            .with_for_update()
        ).one_or_none()
        if row is None:
            raise AppError(
                code="library_paper_not_found",
                message="Library paper not found",
                kind=FailureKind.NOT_FOUND,
            )
        values: dict[str, object] = {
            "last_accessed_at": datetime.now(timezone.utc),
        }
        if request.status is not None:
            values["status"] = request.status.value
        if metadata_overrides is not None:
            values["metadata_overrides"] = metadata_overrides
        db.execute(
            update(LibraryPaper)
            .where(LibraryPaper.id == row.library_entry_id)
            .values(**values)
        )
        db.flush()
        return UpdatedLibraryPaper(
            library_entry_id=row.library_entry_id,
            document_id=row.document_id,
            changed=bool(row.changed),
        )

    def rotate_public_share(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> str:
        entry_id = self.require_library_paper_id_by_document(
            db,
            document_id=document_id,
            user_id=user_id,
            for_update=True,
        )
        token = secrets.token_urlsafe(32)
        db.execute(
            update(LibraryPaper)
            .where(LibraryPaper.id == entry_id)
            .values(
                share_token_hash=hashlib.sha256(token.encode()).hexdigest(),
                is_public=True,
            )
        )
        db.flush()
        return token

    def revoke_public_share(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> bool:
        entry_id = self.require_library_paper_id_by_document(
            db,
            document_id=document_id,
            user_id=user_id,
            for_update=True,
        )
        changed_id = db.scalar(
            update(LibraryPaper)
            .where(
                LibraryPaper.id == entry_id,
                or_(
                    LibraryPaper.is_public.is_(True),
                    LibraryPaper.share_token_hash.is_not(None),
                ),
            )
            .values(share_token_hash=None, is_public=False)
            .returning(LibraryPaper.id)
        )
        db.flush()
        return changed_id is not None

    def require_public_share_document_id(
        self,
        db: Session,
        *,
        token: str,
    ) -> uuid.UUID:
        token_hash = self._public_share_token_hash(token)
        document_id = db.scalar(
            select(LibraryPaper.document_id)
            .where(
                LibraryPaper.share_token_hash == token_hash,
                LibraryPaper.is_public.is_(True),
            )
            .with_for_update(of=LibraryPaper)
        )
        if document_id is None:
            raise self._public_paper_not_found()
        return document_id

    def require_public_share(
        self,
        db: Session,
        *,
        token: str,
    ) -> PublicLibraryPaper:
        token_hash = self._public_share_token_hash(token)
        entry = db.scalar(
            select(LibraryPaper)
            .options(
                selectinload(LibraryPaper.document).load_only(
                    *DOCUMENT_PUBLIC_SHARE_COLUMNS,
                    raiseload=True,
                ),
                selectinload(LibraryPaper.user).load_only(
                    AuthUser.id,
                    AuthUser.display_name,
                    AuthUser.email,
                    raiseload=True,
                ),
            )
            .where(
                LibraryPaper.share_token_hash == token_hash,
                LibraryPaper.is_public.is_(True),
            )
        )
        if entry is None:
            raise self._public_paper_not_found()
        return PublicLibraryPaper(
            entry=entry,
            document=entry.document,
            owner=entry.user,
        )

    @staticmethod
    def _public_share_token_hash(token: str) -> str:
        if not token or len(token) > 512:
            raise DocumentRepository._public_paper_not_found()
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    def _public_paper_not_found() -> AppError:
        return AppError(
            code="public_paper_not_found",
            message="Public paper not found",
            kind=FailureKind.NOT_FOUND,
        )

    def get_by_sha256(
        self,
        db: Session,
        *,
        sha256: str,
        for_update: bool = False,
    ) -> Document | None:
        statement = select(Document).where(Document.sha256 == sha256)
        if for_update:
            statement = statement.with_for_update()
        return db.scalar(statement)

    def get_or_create(
        self,
        db: Session,
        *,
        sha256: str,
        original_filename: str,
        mime_type: str,
        size_bytes: int,
        s3_object_key: str,
        created_by_id: int,
        processing_job_id: uuid.UUID,
    ) -> CanonicalDocumentResult:
        created_id = db.scalar(
            insert(Document)
            .values(
                sha256=sha256,
                original_filename=original_filename,
                mime_type=mime_type,
                size_bytes=size_bytes,
                s3_object_key=s3_object_key,
                title=original_filename,
                created_by_id=created_by_id,
                processing_status=DocumentProcessingStatus.PROCESSING.value,
                processing_job_id=processing_job_id,
            )
            .on_conflict_do_nothing(index_elements=[Document.sha256])
            .returning(Document.id)
        )
        if created_id is not None:
            document = db.get(Document, created_id)
            if document is None:
                raise RuntimeError("created_document_not_found")
            return CanonicalDocumentResult(document=document, created=True)

        document = self.get_by_sha256(db, sha256=sha256, for_update=True)
        if document is None:
            raise RuntimeError("canonical_document_conflict_not_found")
        if document.size_bytes != size_bytes:
            raise RuntimeError("sha256_size_mismatch")
        document.gc_after = None
        return CanonicalDocumentResult(document=document, created=False)

    def attach_library(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        user_id: int,
    ) -> ReferenceResult:
        created_id = db.scalar(
            insert(LibraryPaper)
            .values(
                user_id=user_id,
                document_id=document_id,
                status=PaperStatus.reading.value,
                last_accessed_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(
                index_elements=[LibraryPaper.user_id, LibraryPaper.document_id]
            )
            .returning(LibraryPaper.id)
        )
        db.execute(
            update(Document)
            .where(Document.id == document_id, Document.gc_after.isnot(None))
            .values(gc_after=None)
        )
        return ReferenceResult(created=created_id is not None)

    def attach_project(
        self,
        db: Session,
        *,
        document_id: uuid.UUID,
        project_id: uuid.UUID,
        added_by_id: int,
    ) -> ReferenceResult:
        created_id = db.scalar(
            insert(ProjectPaper)
            .values(
                document_id=document_id,
                project_id=project_id,
                added_by_id=added_by_id,
            )
            .on_conflict_do_nothing(
                index_elements=[ProjectPaper.project_id, ProjectPaper.document_id]
            )
            .returning(ProjectPaper.id)
        )
        db.execute(
            update(Document)
            .where(Document.id == document_id, Document.gc_after.isnot(None))
            .values(gc_after=None)
        )
        return ReferenceResult(created=created_id is not None)

    def mark_for_reprocessing(
        self,
        document: Document,
        *,
        processing_job_id: uuid.UUID,
    ) -> None:
        document.processing_status = DocumentProcessingStatus.PROCESSING.value
        document.processing_job_id = processing_job_id
        document.parser_warning_code = None


document_repository = DocumentRepository()
