from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.modules.billing.infrastructure.usage_repository import (
    resource_usage_repository,
)


def test_account_usage_is_a_unique_union_of_library_and_owned_projects() -> None:
    document_ids = resource_usage_repository._completed_document_ids(user_id=17)
    sql = " ".join(
        str(
            select(document_ids.c.document_id).compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )

    assert " UNION SELECT " in sql
    assert "UNION ALL" not in sql
    assert "library_papers.user_id = 17" in sql
    assert "projects.owner_id = 17" in sql
    assert "project_collaborators" not in sql
