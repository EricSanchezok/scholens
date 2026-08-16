"""Read-only Zotero Web API work executed inside the Jobs service."""

from __future__ import annotations

import ipaddress
import json
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlsplit

import pymupdf
import requests

from src.s3_service import s3_service

ZOTERO_API_BASE = "https://api.zotero.org"
IMPORTABLE_ITEM_TYPES = frozenset({"journalArticle", "conferencePaper", "preprint"})
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_AUTO_IMPORT_ITEMS = 50


class ZoteroJobError(RuntimeError):
    def __init__(self, code: str, *, invalid_credential: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.invalid_credential = invalid_credential


@dataclass(frozen=True, slots=True)
class ZoteroJobCredential:
    user_id: str
    api_key: str = field(repr=False)
    revision: str


class ZoteroClient:
    def __init__(self, credential: ZoteroJobCredential) -> None:
        self._credential = credential
        self._session = requests.Session()
        self._session.headers.update(
            {
                "Zotero-API-Key": credential.api_key,
                "Zotero-API-Version": "3",
            }
        )

    @property
    def _base(self) -> str:
        return f"{ZOTERO_API_BASE}/users/{self._credential.user_id}"

    def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        url = path if path.startswith("https://") else f"{self._base}{path}"
        for attempt in range(3):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=(10, 60),
                    stream=stream,
                )
            except requests.RequestException as exc:
                if attempt == 2:
                    raise ZoteroJobError("zotero_unavailable") from exc
                time.sleep(2**attempt)
                continue
            if response.status_code in {401, 403}:
                raise ZoteroJobError(
                    "zotero_credentials_invalid",
                    invalid_credential=True,
                )
            if response.status_code == 429:
                if attempt == 2:
                    raise ZoteroJobError("zotero_rate_limited")
                time.sleep(min(_safe_header_seconds(response, "Retry-After", 2), 10))
                continue
            if response.status_code == 404:
                raise ZoteroJobError("zotero_item_not_found")
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                raise ZoteroJobError("zotero_unavailable") from exc
            backoff = response.headers.get("Backoff")
            if backoff:
                time.sleep(min(_safe_header_seconds(response, "Backoff", 0), 10))
            return response
        raise ZoteroJobError("zotero_unavailable")

    def items(self, item_keys: Iterable[str]) -> list[dict[str, Any]]:
        keys = list(item_keys)
        if not keys:
            return []
        response = self._request(
            "/items",
            params={"itemKey": ",".join(keys), "limit": min(len(keys), 50)},
        )
        value = response.json()
        return (
            [item for item in value if isinstance(item, dict)]
            if isinstance(value, list)
            else []
        )

    def children(self, item_key: str) -> list[dict[str, Any]]:
        response = self._request(
            f"/items/{item_key}/children",
            params={"limit": 100},
        )
        value = response.json()
        return (
            [item for item in value if isinstance(item, dict)]
            if isinstance(value, list)
            else []
        )

    def download_attachment(self, attachment_key: str) -> bytes:
        response = self._request(f"/items/{attachment_key}/file", stream=True)
        return _bounded_response_bytes(response)

    def items_since(
        self,
        version: int,
        *,
        is_active: Callable[[], bool] | None = None,
    ) -> tuple[list[dict[str, Any]], int | None]:
        results: list[dict[str, Any]] = []
        start = 0
        library_version: int | None = None
        while True:
            _require_active(is_active)
            response = self._request(
                "/items/top",
                params={
                    "since": version,
                    "limit": 100,
                    "start": start,
                    "itemType": " || ".join(sorted(IMPORTABLE_ITEM_TYPES)),
                },
            )
            library_version = _header_int(response, "Last-Modified-Version")
            value = response.json()
            page = (
                [item for item in value if isinstance(item, dict)]
                if isinstance(value, list)
                else []
            )
            results.extend(page)
            if len(page) < 100:
                break
            start += 100
        return results, library_version

    def current_library_version(self) -> int | None:
        response = self._request("/items/top", params={"limit": 1})
        return _header_int(response, "Last-Modified-Version")


def import_items(
    *,
    task_id: str,
    credential: ZoteroJobCredential,
    item_keys: list[str],
    is_active: Callable[[], bool] | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    client = ZoteroClient(credential)
    _require_active(is_active)
    raw_by_key = {
        str(item.get("key")): item
        for item in client.items(item_keys)
        if item.get("key")
    }
    results: list[dict[str, Any]] = []
    for item_key in item_keys:
        _require_active(is_active)
        results.append(
            _prepare_import_item(
                task_id=task_id,
                client=client,
                item=raw_by_key.get(item_key),
                item_key=item_key,
            )
        )
    return results, client.current_library_version()


def sync_items(
    *,
    task_id: str,
    credential: ZoteroJobCredential,
    targets: list[dict[str, Any]],
    auto_import_version: int | None,
    is_active: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    client = ZoteroClient(credential)
    _require_active(is_active)
    updates: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for index, target in enumerate(targets):
        if index % 10 == 0:
            _require_active(is_active)
        item_key = str(target.get("item_key") or "")
        attachment_key = str(target.get("attachment_key") or "")
        if not item_key or not attachment_key:
            continue
        try:
            annotations = [
                {"key": value.get("key"), "data": value.get("data") or {}}
                for value in client.children(attachment_key)
                if value.get("key")
                and value.get("data", {}).get("itemType") == "annotation"
            ]
        except ZoteroJobError as exc:
            if exc.invalid_credential:
                raise
            failures.append({"item_key": item_key, "error_code": exc.code})
            continue
        updates.append(
            {
                "item_key": item_key,
                "attachment_key": attachment_key,
                "annotations_json": _annotations_json(annotations),
            }
        )

    auto_imports: list[dict[str, Any]] = []
    library_version: int | None = None
    if auto_import_version is not None:
        new_items, observed_version = client.items_since(
            auto_import_version,
            is_active=is_active,
        )
        ordered_items = sorted(new_items, key=_item_version)
        selected_items = _bounded_version_batch(ordered_items)
        library_version = (
            observed_version
            if len(selected_items) == len(ordered_items)
            else max((_item_version(item) for item in selected_items), default=None)
        )
        for item in selected_items:
            _require_active(is_active)
            key = str(item.get("key") or "")
            if key:
                auto_imports.append(
                    _prepare_import_item(
                        task_id=task_id,
                        client=client,
                        item=item,
                        item_key=key,
                    )
                )
    return {
        "updates": updates,
        "failures": failures,
        "auto_imports": auto_imports,
        "library_version": library_version,
    }


def _prepare_import_item(
    *,
    task_id: str,
    client: ZoteroClient,
    item: dict[str, Any] | None,
    item_key: str,
) -> dict[str, Any]:
    if item is None:
        return _failed_item(item_key, "zotero_item_not_found")
    data = item.get("data") or {}
    if data.get("itemType") not in IMPORTABLE_ITEM_TYPES:
        return _failed_item(item_key, "zotero_item_not_supported")
    try:
        children = client.children(item_key)
        attachment = _stored_pdf(children)
        source_url: str | None = None
        if attachment is not None:
            attachment_key = str(attachment.get("key") or "")
            pdf = client.download_attachment(attachment_key)
            import_source = "pdf_attachment"
        else:
            attachment_key = ""
            pdf, source_url = _resolve_open_pdf(data)
            import_source = "url"
        _validate_pdf(pdf)
        object_key = f"zotero-imports/{task_id}/{item_key}.pdf"
        s3_service.upload_bytes_to_key(pdf, object_key, "application/pdf")
        annotations = (
            [
                {"key": value.get("key"), "data": value.get("data") or {}}
                for value in client.children(attachment_key)
                if value.get("key")
                and value.get("data", {}).get("itemType") == "annotation"
            ]
            if attachment_key
            else []
        )
        return {
            "item_key": item_key,
            "status": "ready",
            "s3_object_key": object_key,
            "metadata": _metadata(item),
            "attachment": {
                "item_key": item_key,
                "import_source": import_source,
                "attachment_key": attachment_key or None,
                "source_url": source_url,
                "annotations_json": _annotations_json(annotations),
                "version": (
                    attachment.get("version") if attachment is not None else None
                ),
            },
            "page_dimensions": _page_dimensions(pdf),
        }
    except ZoteroJobError as exc:
        if exc.invalid_credential:
            raise
        return _failed_item(item_key, exc.code, title=str(data.get("title") or ""))


def _annotations_json(annotations: list[dict[str, Any]]) -> str:
    stable = [
        {"key": value.get("key"), "data": value.get("data") or {}}
        for value in annotations
        if value.get("key")
    ]
    return json.dumps(stable, separators=(",", ":"), sort_keys=True)


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data") or {}
    creators = []
    for creator in data.get("creators") or []:
        if not isinstance(creator, dict) or creator.get("creatorType") not in {
            None,
            "author",
        }:
            continue
        name = str(creator.get("name") or "").strip()
        if not name:
            name = " ".join(
                value
                for value in (
                    str(creator.get("firstName") or "").strip(),
                    str(creator.get("lastName") or "").strip(),
                )
                if value
            )
        if name:
            creators.append(name)
    return {
        "item_key": str(item.get("key") or ""),
        "title": str(data.get("title") or "").strip(),
        "authors": creators,
        "abstract": str(data.get("abstractNote") or "").strip() or None,
        "publish_date": str(data.get("date") or "").strip() or None,
        "doi": str(data.get("DOI") or "").strip() or None,
        "tags": [
            str(tag.get("tag"))
            for tag in data.get("tags") or []
            if isinstance(tag, dict) and tag.get("tag")
        ],
        "date_added": str(data.get("dateAdded") or "").strip() or None,
        "item_type": str(data.get("itemType") or ""),
        "venue": str(
            data.get("publicationTitle")
            or data.get("proceedingsTitle")
            or data.get("conferenceName")
            or data.get("repository")
            or ""
        ).strip()
        or None,
        "collection_keys": [str(value) for value in data.get("collections") or []],
        "has_pdf_attachment": False,
        "has_resolvable_source": bool(data.get("url") or data.get("DOI")),
        "has_metadata": bool(data.get("title") or data.get("url") or data.get("DOI")),
        "version": item.get("version")
        if isinstance(item.get("version"), int)
        else None,
    }


def _stored_pdf(children: list[dict[str, Any]]) -> dict[str, Any] | None:
    for child in children:
        data = child.get("data") or {}
        content_type = str(data.get("contentType") or "").casefold()
        filename = str(data.get("filename") or "").casefold()
        if (
            data.get("itemType") == "attachment"
            and (content_type == "application/pdf" or filename.endswith(".pdf"))
            and str(data.get("linkMode") or "").casefold()
            in {"imported_file", "imported_url"}
        ):
            return child
    return None


def _resolve_open_pdf(data: dict[str, Any]) -> tuple[bytes, str]:
    candidates = []
    url = str(data.get("url") or "").strip()
    if url:
        candidates.append(url)
    doi = str(data.get("DOI") or "").strip()
    if doi:
        candidates.append(doi if doi.startswith("http") else f"https://doi.org/{doi}")
    for candidate in candidates:
        try:
            return _fetch_public_pdf(candidate), candidate
        except ZoteroJobError:
            continue
    raise ZoteroJobError("zotero_pdf_unavailable")


def _fetch_public_pdf(url: str) -> bytes:
    session = requests.Session()
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        _require_public_url(current)
        try:
            response = session.get(
                current,
                timeout=(10, 60),
                stream=True,
                allow_redirects=False,
                headers={"Accept": "application/pdf"},
            )
        except requests.RequestException as exc:
            raise ZoteroJobError("zotero_pdf_unavailable") from exc
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            if not location:
                raise ZoteroJobError("zotero_pdf_unavailable")
            current = urljoin(current, location)
            continue
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ZoteroJobError("zotero_pdf_unavailable") from exc
        return _bounded_response_bytes(response)
    raise ZoteroJobError("zotero_pdf_unavailable")


def _require_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username:
        raise ZoteroJobError("zotero_pdf_unsafe_address")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443)
    except socket.gaierror as exc:
        raise ZoteroJobError("zotero_pdf_unavailable") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ZoteroJobError("zotero_pdf_unsafe_address")


def _bounded_response_bytes(response: requests.Response) -> bytes:
    declared = response.headers.get("Content-Length")
    try:
        declared_size = int(declared) if declared else None
    except ValueError:
        declared_size = None
    if declared_size is not None and declared_size > MAX_FILE_BYTES:
        raise ZoteroJobError("zotero_pdf_too_large")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        size += len(chunk)
        if size > MAX_FILE_BYTES:
            raise ZoteroJobError("zotero_pdf_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def _validate_pdf(content: bytes) -> None:
    if not content.startswith(b"%PDF-"):
        raise ZoteroJobError("zotero_pdf_unavailable")
    try:
        document = pymupdf.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise ZoteroJobError("zotero_pdf_unavailable") from exc
    try:
        if document.needs_pass:
            raise ZoteroJobError("zotero_pdf_encrypted")
        if document.page_count <= 0:
            raise ZoteroJobError("zotero_pdf_unavailable")
    finally:
        document.close()


def _page_dimensions(content: bytes) -> list[list[float | int]]:
    document = pymupdf.open(stream=content, filetype="pdf")
    try:
        return [
            [page.number, float(page.rect.width), float(page.rect.height)]
            for page_number in range(document.page_count)
            for page in (document.load_page(page_number),)
        ]
    finally:
        document.close()


def _failed_item(
    item_key: str, code: str, *, title: str | None = None
) -> dict[str, Any]:
    return {
        "item_key": item_key,
        "status": "failed",
        "title": title or None,
        "error_code": code,
    }


def _header_int(response: requests.Response, name: str) -> int | None:
    value = response.headers.get(name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _safe_header_seconds(
    response: requests.Response,
    name: str,
    default: int,
) -> int:
    value = _header_int(response, name)
    return max(0, value) if value is not None else default


def _require_active(is_active: Callable[[], bool] | None) -> None:
    if is_active is not None and not is_active():
        raise ZoteroJobError("zotero_operation_cancelled")


def _item_version(item: dict[str, Any]) -> int:
    value = item.get("version")
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _bounded_version_batch(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(items) <= MAX_AUTO_IMPORT_ITEMS:
        return items
    boundary = _item_version(items[MAX_AUTO_IMPORT_ITEMS - 1])
    return [item for item in items if _item_version(item) <= boundary]
