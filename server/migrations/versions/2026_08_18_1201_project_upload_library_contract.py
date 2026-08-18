"""project uploads default to the personal library (contract)

Revision ID: 48cd53a3c1f84fbb95d93a2505db221c
Revises: 8a8f20189e5c45c5aceb09eb45dd8e87
Create Date: 2026-08-18 12:01:00+00:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "48cd53a3c1f84fbb95d93a2505db221c"
down_revision: str | None = "8a8f20189e5c45c5aceb09eb45dd8e87"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Backfill the split reference flags, bind the library quota owner, and
    retire the single reference_created flag.

    The expand revision added the new columns; this revision moves data into
    them, enforces the foreign key, and drops the superseded column. It is a
    contract-phase migration and advances the minimum compatible application
    revision in server/migrations/policy.json.
    """
    connection = op.get_bind()
    # Backfill the per-side reference flags from the pre-split boolean.
    # A personal (project_id IS NULL) reservation created a LibraryPaper; a
    # project reservation created a ProjectPaper.
    connection.execute(
        sa.text(
            """
            UPDATE scholens.upload_reservations AS reservation
            SET reference_created_library = reservation.reference_created,
                reference_created_project = false
            FROM scholens.jobs AS job
            WHERE job.id = reservation.id
              AND job.project_id IS NULL
            """
        )
    )
    connection.execute(
        sa.text(
            """
            UPDATE scholens.upload_reservations AS reservation
            SET reference_created_library = false,
                reference_created_project = reservation.reference_created
            FROM scholens.jobs AS job
            WHERE job.id = reservation.id
              AND job.project_id IS NOT NULL
            """
        )
    )
    op.create_foreign_key(
        "fk_upload_reservations_library_quota_owner",
        "upload_reservations",
        "users",
        ["library_quota_owner_id"],
        ["id"],
        source_schema="scholens",
        referent_schema="auth",
        ondelete="SET NULL",
    )
    op.drop_column("upload_reservations", "reference_created", schema="scholens")
