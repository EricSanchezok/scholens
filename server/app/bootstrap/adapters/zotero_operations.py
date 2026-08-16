"""External-only Zotero provider and object-storage operations."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.helpers.parser import extract_pdf_page_dimensions
from app.helpers.s3 import s3_service
from app.modules.integrations.zotero.application.zotero import (
    PageDimensions,
    PreparedZoteroCallback,
    ZoteroAccessToken,
    ZoteroCredentials,
    ZoteroCollectionSnapshot,
    ZoteroCollectionSnapshotPage,
    ZoteroItemSnapshot,
    ZoteroLibrarySnapshot,
    ZoteroRequestToken,
)
from app.modules.integrations.zotero.infrastructure.client import ZoteroApiClient
from app.modules.integrations.zotero.infrastructure.oauth import zotero_auth_client


logger = logging.getLogger(__name__)


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", normalized)
    if match:
        return match.group(1)
    if len(normalized) == 7 and normalized[4] == "-":
        return normalized + "-01"
    if len(normalized) == 4 and normalized.isdigit():
        return normalized + "-01-01"
    match = re.search(r"\b(\d{4})\b", normalized)
    return match.group(1) + "-01-01" if match else None


def _authors(creators: list[dict[str, Any]]) -> tuple[str, ...]:
    result: list[str] = []
    for creator in creators:
        if creator.get("creatorType") not in ("author", None):
            continue
        name = str(creator.get("name") or "").strip()
        if not name:
            first = str(creator.get("firstName") or "").strip()
            last = str(creator.get("lastName") or "").strip()
            name = f"{first} {last}".strip()
        if name:
            result.append(name)
    return tuple(result)


def _snapshot(
    item: dict[str, Any],
    *,
    pdf_parent_keys: set[str],
) -> ZoteroItemSnapshot:
    data = dict(item.get("data") or {})
    item_key = str(item.get("key") or "")
    title = str(data.get("title") or "").strip()
    doi = str(data.get("DOI") or "").strip() or None
    url = str(data.get("url") or "").strip()
    tags = tuple(
        name
        for entry in data.get("tags") or []
        if isinstance(entry, dict) and (name := str(entry.get("tag") or "").strip())
    )
    collection_keys = tuple(
        str(key) for key in data.get("collections") or [] if str(key)
    )
    venue = (
        data.get("publicationTitle")
        or data.get("proceedingsTitle")
        or data.get("conferenceName")
        or data.get("repository")
    )
    return ZoteroItemSnapshot(
        item_key=item_key,
        title=title,
        authors=_authors(list(data.get("creators") or [])),
        abstract=str(data.get("abstractNote") or "").strip() or None,
        publish_date=_parse_date(
            str(data["date"]) if data.get("date") is not None else None
        ),
        doi=doi,
        tags=tags,
        date_added=str(data.get("dateAdded") or "").strip() or None,
        item_type=str(data.get("itemType") or ""),
        venue=str(venue).strip() or None if venue is not None else None,
        collection_keys=collection_keys,
        has_pdf_attachment=item_key in pdf_parent_keys,
        has_resolvable_source=bool(url or doi),
        has_metadata=bool(title or doi or url),
        version=(
            int(item["version"])
            if isinstance(item.get("version"), int)
            and not isinstance(item.get("version"), bool)
            else None
        ),
    )


def _page_dimensions(content: bytes) -> PageDimensions:
    dimensions = extract_pdf_page_dimensions(content)
    return tuple(
        (page_index, float(width), float(height))
        for page_index, (width, height) in sorted(dimensions.items())
    )


class DefaultZoteroOperations:
    """Calls remote providers only; it never owns or receives a database Session."""

    def request_token(self) -> ZoteroRequestToken | None:
        result = zotero_auth_client.get_request_token()
        if result is None:
            return None
        return ZoteroRequestToken(
            token=result.oauth_token,
            secret=result.oauth_token_secret,
        )

    def authorize_url(self, *, request_token: ZoteroRequestToken) -> str:
        return zotero_auth_client.get_authorize_url(request_token.token)

    def exchange_access_token(
        self,
        *,
        callback: PreparedZoteroCallback,
        verifier: str,
    ) -> ZoteroAccessToken | None:
        result = zotero_auth_client.get_access_token(
            request_token=callback.request_token.token,
            request_token_secret=callback.request_token.secret,
            verifier=verifier,
        )
        if result is None:
            return None
        return ZoteroAccessToken(
            user_id=result.zotero_user_id,
            api_key=result.api_key,
        )

    def verify_access_token(self, *, access_token: ZoteroAccessToken) -> bool:
        info = ZoteroApiClient(
            zotero_user_id=access_token.user_id,
            api_key=access_token.api_key,
        ).key_info()
        if str(info.get("userID") or "") != access_token.user_id:
            return False
        access = info.get("access")
        if not isinstance(access, dict):
            return False
        user_access = access.get("user")
        if not isinstance(user_access, dict):
            return False
        if not all(
            user_access.get(name) is True for name in ("library", "notes", "files")
        ):
            return False
        groups = access.get("groups")
        return groups in (None, {}, [])

    def fetch_library(
        self,
        *,
        credentials: ZoteroCredentials,
        limit: int = 25,
        start: int = 0,
        query: str | None = None,
        collection_key: str | None = None,
        item_type: str | None = None,
        sort: str = "dateModified",
        direction: str = "desc",
    ) -> ZoteroLibrarySnapshot:
        client = self._client(credentials)
        page = client.get_top_importable_items_page(
            limit=limit,
            start=start,
            query=query,
            collection_key=collection_key,
            item_type=item_type,
            sort=sort,
            direction=direction,
        )
        visible_item_keys = [
            str(item.get("key") or "") for item in page.items if item.get("key")
        ]
        pdf_parent_keys = client.get_stored_pdf_parent_keys(visible_item_keys)
        return ZoteroLibrarySnapshot(
            items=tuple(
                _snapshot(
                    item,
                    pdf_parent_keys=pdf_parent_keys,
                )
                for item in page.items
                if item.get("key")
            ),
            start=start,
            limit=limit,
            total_count=page.total_count,
            library_version=page.library_version,
        )

    def fetch_collections(
        self,
        *,
        credentials: ZoteroCredentials,
        limit: int,
        start: int,
    ) -> ZoteroCollectionSnapshotPage:
        page = self._client(credentials).get_collections_page(
            limit=limit,
            start=start,
        )
        return ZoteroCollectionSnapshotPage(
            items=tuple(
                ZoteroCollectionSnapshot(
                    key=str(item.get("key") or item.get("data", {}).get("key") or ""),
                    name=str(item.get("data", {}).get("name") or "").strip(),
                )
                for item in page.items
                if (item.get("key") or item.get("data", {}).get("key"))
                and str(item.get("data", {}).get("name") or "").strip()
            ),
            start=start,
            limit=limit,
            total_count=page.total_count,
        )

    def current_library_version(self, *, credentials: ZoteroCredentials) -> int | None:
        return self._client(credentials).current_library_version()

    async def fetch_page_dimensions(self, *, source_key: str | None) -> PageDimensions:
        if not source_key:
            return ()
        try:
            content = await asyncio.to_thread(
                s3_service.download_bytes,
                source_key,
            )
            return await asyncio.to_thread(_page_dimensions, content)
        except Exception:
            logger.warning(
                "zotero.page_dimensions.unavailable",
                extra={"source_kind": "stored_document"},
                exc_info=True,
            )
            return ()

    async def upload_pdf(self, *, content: bytes) -> None:
        import hashlib

        await asyncio.to_thread(
            s3_service.upload_document_source,
            sha256=hashlib.sha256(content).hexdigest(),
            pdf_bytes=content,
        )

    async def download_job_pdf(self, *, object_key: str) -> bytes:
        if not object_key.startswith("zotero-imports/"):
            raise ValueError("zotero_job_object_key_invalid")
        return await asyncio.to_thread(s3_service.download_bytes, object_key)

    async def delete_job_pdf(self, *, object_key: str) -> None:
        if object_key.startswith("zotero-imports/"):
            await asyncio.to_thread(s3_service.delete_file, object_key)

    @staticmethod
    def _client(credentials: ZoteroCredentials) -> ZoteroApiClient:
        return ZoteroApiClient(
            zotero_user_id=credentials.user_id,
            api_key=credentials.api_key,
        )


__all__ = ["DefaultZoteroOperations"]
