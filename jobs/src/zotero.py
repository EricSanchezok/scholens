"""Read-only Zotero Web API work executed inside the Jobs service."""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable
from urllib.parse import urljoin, urlsplit

import pymupdf
import requests
from scholens_job_contracts import (
    MAX_ZOTERO_CALLBACK_BYTES,
    ZOTERO_SYNC_AUTO_IMPORT_RESERVE_BYTES,
)

from src.s3_service import s3_service
from src.webhook_signing import encode_json_body

ZOTERO_API_BASE = "https://api.zotero.org"
IMPORTABLE_ITEM_TYPES = frozenset({"journalArticle", "conferencePaper", "preprint"})
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_AUTO_IMPORT_ITEMS = 50
MAX_ANNOTATIONS_BYTES = 2 * 1024 * 1024
ZOTERO_KEY = re.compile(r"^[A-Z0-9]{8}$")
_MAX_VERSION_SENTINEL = 2**63 - 1

logger = logging.getLogger(__name__)


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
        self._session.trust_env = False
        self._api_headers = {
            "Zotero-API-Key": credential.api_key,
            "Zotero-API-Version": "3",
        }

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> ZoteroClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def _base(self) -> str:
        return f"{ZOTERO_API_BASE}/users/{self._credential.user_id}"

    def _request(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        stream: bool = False,
        allow_cross_origin_redirect: bool = False,
    ) -> requests.Response:
        initial_url = path if path.startswith("https://") else f"{self._base}{path}"
        for attempt in range(3):
            url = initial_url
            request_params = params
            redirects = 0
            try:
                while True:
                    same_origin = _same_origin(url, ZOTERO_API_BASE)
                    if not same_origin:
                        if not allow_cross_origin_redirect:
                            raise ZoteroJobError("zotero_unavailable")
                        _require_public_url(url)
                    response = self._session.get(
                        url,
                        params=request_params,
                        timeout=(10, 60),
                        stream=stream,
                        allow_redirects=False,
                        headers=self._api_headers if same_origin else {},
                    )
                    if not same_origin:
                        try:
                            _require_global_peer(response)
                        except ZoteroJobError:
                            response.close()
                            raise
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    try:
                        location = response.headers.get("Location")
                        if not location or redirects >= MAX_REDIRECTS:
                            raise ZoteroJobError("zotero_unavailable")
                        next_url = urljoin(url, location)
                        if (
                            not _same_origin(next_url, url)
                            and not allow_cross_origin_redirect
                        ):
                            raise ZoteroJobError("zotero_unavailable")
                        url = next_url
                        request_params = None
                        redirects += 1
                    finally:
                        response.close()
            except requests.RequestException as exc:
                if attempt == 2:
                    raise ZoteroJobError("zotero_unavailable") from exc
                time.sleep(2**attempt)
                continue
            if response.status_code in {401, 403}:
                response.close()
                raise ZoteroJobError(
                    "zotero_credentials_invalid",
                    invalid_credential=True,
                )
            if response.status_code == 429:
                if attempt == 2:
                    response.close()
                    raise ZoteroJobError("zotero_rate_limited")
                retry_after = min(_safe_header_seconds(response, "Retry-After", 2), 10)
                response.close()
                time.sleep(retry_after)
                continue
            if response.status_code == 404:
                response.close()
                raise ZoteroJobError("zotero_item_not_found")
            try:
                response.raise_for_status()
            except requests.RequestException as exc:
                response.close()
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
        for item_key in keys:
            _require_zotero_key(item_key)
        response = self._request(
            "/items",
            params={"itemKey": ",".join(keys), "limit": min(len(keys), 50)},
        )
        try:
            value = response.json()
        finally:
            response.close()
        return (
            [item for item in value if isinstance(item, dict)]
            if isinstance(value, list)
            else []
        )

    def children(self, item_key: str) -> list[dict[str, Any]]:
        _require_zotero_key(item_key)
        response = self._request(
            f"/items/{item_key}/children",
            params={"limit": 100},
        )
        try:
            value = response.json()
        finally:
            response.close()
        return (
            [item for item in value if isinstance(item, dict)]
            if isinstance(value, list)
            else []
        )

    def download_attachment(self, attachment_key: str) -> bytes:
        _require_zotero_key(attachment_key)
        response = self._request(
            f"/items/{attachment_key}/file",
            stream=True,
            allow_cross_origin_redirect=True,
        )
        try:
            return _bounded_response_bytes(response)
        finally:
            response.close()

    def items_since(
        self,
        version: int,
        *,
        start: int = 0,
        limit: int = MAX_AUTO_IMPORT_ITEMS,
        is_active: Callable[[], bool] | None = None,
    ) -> tuple[list[dict[str, Any]], int | None, bool]:
        _require_active(is_active)
        page_limit = min(limit, MAX_AUTO_IMPORT_ITEMS)
        response = self._request(
            "/items/top",
            params={
                "since": version,
                "limit": page_limit,
                "start": start,
                "sort": "dateModified",
                "direction": "asc",
                "itemType": " || ".join(sorted(IMPORTABLE_ITEM_TYPES)),
            },
        )
        library_version = _header_int(response, "Last-Modified-Version")
        total = _header_int(response, "Total-Results")
        try:
            value = response.json()
            page = (
                [item for item in value if isinstance(item, dict)]
                if isinstance(value, list)
                else []
            )
        finally:
            response.close()
        has_more = (
            start + len(page) < total if total is not None else len(page) == page_limit
        )
        return page, library_version, has_more

    def current_library_version(self) -> int | None:
        response = self._request("/items/top", params={"limit": 1})
        try:
            return _header_int(response, "Last-Modified-Version")
        finally:
            response.close()


def zotero_callback_payload_size(payload: dict[str, Any]) -> int:
    """Return the exact UTF-8 body size used by the signed JSON transport."""
    return len(encode_json_body(payload))


def validate_zotero_callback_payload(payload: dict[str, Any]) -> None:
    if zotero_callback_payload_size(payload) > MAX_ZOTERO_CALLBACK_BYTES:
        raise ZoteroJobError("zotero_callback_budget_exceeded")


def discard_unsubmitted_items(items: Iterable[dict[str, Any]]) -> None:
    _delete_uploaded_keys(
        [
            object_key
            for item in items
            if isinstance(item, dict)
            and isinstance((object_key := item.get("s3_object_key")), str)
            and object_key.startswith("zotero-imports/")
        ]
    )


def _array_growth(encoded_sum: int, count: int) -> int:
    return encoded_sum + max(0, count - 1)


def _import_callback_base_size(
    *,
    task_id: str,
    credential_revision: str,
) -> int:
    return zotero_callback_payload_size(
        {
            "task_id": task_id,
            "operation": "import",
            "credential_revision": credential_revision,
            "credential_outcome": "verified",
            "error_code": None,
            "items": [],
            "library_version": _MAX_VERSION_SENTINEL,
        }
    )


def _sync_callback_base_size(
    *,
    task_id: str,
    credential_revision: str,
    auto_import_version: int | None,
    auto_import_start: int,
) -> int:
    auto_import_active = auto_import_version is not None
    return zotero_callback_payload_size(
        {
            "task_id": task_id,
            "operation": "sync",
            "credential_revision": credential_revision,
            "credential_outcome": "verified",
            "error_code": None,
            "updates": [],
            "failures": [],
            "auto_imports": [],
            "library_version": (_MAX_VERSION_SENTINEL if auto_import_active else None),
            "auto_import_base_version": auto_import_version,
            "auto_import_base_start": auto_import_start,
            "auto_import_caught_up_version": (
                _MAX_VERSION_SENTINEL if auto_import_active else None
            ),
        }
    )


def _discard_prepared_item(
    item: dict[str, Any],
    *,
    uploaded_keys: list[str],
) -> None:
    object_key = item.get("s3_object_key")
    if not isinstance(object_key, str) or not object_key.startswith("zotero-imports/"):
        return
    _delete_uploaded_keys([object_key])
    if object_key in uploaded_keys:
        uploaded_keys.remove(object_key)


def import_items(
    *,
    task_id: str,
    credential: ZoteroJobCredential,
    item_keys: list[str],
    is_active: Callable[[], bool] | None = None,
) -> tuple[list[dict[str, Any]], int | None]:
    uploaded_keys: list[str] = []
    try:
        for item_key in item_keys:
            _require_zotero_key(item_key)
        budget_errors = [
            _failed_item(item_key, "zotero_callback_budget_exceeded")
            for item_key in item_keys
        ]
        error_sizes = [zotero_callback_payload_size(error) for error in budget_errors]
        error_suffix_sizes = [0] * (len(item_keys) + 1)
        for index in range(len(item_keys) - 1, -1, -1):
            error_suffix_sizes[index] = (
                error_suffix_sizes[index + 1] + error_sizes[index]
            )
        callback_base_size = _import_callback_base_size(
            task_id=task_id,
            credential_revision=credential.revision,
        )
        callback_commas = max(0, len(item_keys) - 1)
        with ZoteroClient(credential) as client:
            _require_active(is_active)
            raw_by_key = {
                str(item.get("key")): item
                for item in client.items(item_keys)
                if item.get("key")
            }
            results: list[dict[str, Any]] = []
            encoded_results_size = 0
            for index, item_key in enumerate(item_keys):
                _require_active(is_active)
                prepared = _prepare_import_item(
                    task_id=task_id,
                    client=client,
                    item=raw_by_key.get(item_key),
                    item_key=item_key,
                    uploaded_keys=uploaded_keys,
                )
                prepared_size = zotero_callback_payload_size(prepared)
                projected_size = (
                    callback_base_size
                    + encoded_results_size
                    + prepared_size
                    + error_suffix_sizes[index + 1]
                    + callback_commas
                )
                if projected_size > MAX_ZOTERO_CALLBACK_BYTES:
                    _discard_prepared_item(prepared, uploaded_keys=uploaded_keys)
                    results.extend(budget_errors[index:])
                    break
                results.append(prepared)
                encoded_results_size += prepared_size
            return results, client.current_library_version()
    except Exception:
        _delete_uploaded_keys(uploaded_keys)
        raise


def sync_items(
    *,
    task_id: str,
    credential: ZoteroJobCredential,
    targets: list[dict[str, Any]],
    auto_import_version: int | None,
    auto_import_start: int = 0,
    is_active: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    uploaded_keys: list[str] = []
    try:
        return _sync_items(
            task_id=task_id,
            credential=credential,
            targets=targets,
            auto_import_version=auto_import_version,
            auto_import_start=auto_import_start,
            is_active=is_active,
            uploaded_keys=uploaded_keys,
        )
    except Exception:
        _delete_uploaded_keys(uploaded_keys)
        raise


def _sync_items(
    *,
    task_id: str,
    credential: ZoteroJobCredential,
    targets: list[dict[str, Any]],
    auto_import_version: int | None,
    auto_import_start: int,
    is_active: Callable[[], bool] | None,
    uploaded_keys: list[str],
) -> dict[str, Any]:
    with ZoteroClient(credential) as client:
        return _sync_items_with_client(
            task_id=task_id,
            client=client,
            credential_revision=credential.revision,
            targets=targets,
            auto_import_version=auto_import_version,
            auto_import_start=auto_import_start,
            is_active=is_active,
            uploaded_keys=uploaded_keys,
        )


def _sync_items_with_client(
    *,
    task_id: str,
    client: ZoteroClient,
    credential_revision: str,
    targets: list[dict[str, Any]],
    auto_import_version: int | None,
    auto_import_start: int,
    is_active: Callable[[], bool] | None,
    uploaded_keys: list[str],
) -> dict[str, Any]:
    for target in targets:
        _require_zotero_key(str(target.get("item_key") or ""))
        _require_zotero_key(str(target.get("attachment_key") or ""))
    _require_active(is_active)
    updates: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    callback_base_size = _sync_callback_base_size(
        task_id=task_id,
        credential_revision=credential_revision,
        auto_import_version=auto_import_version,
        auto_import_start=auto_import_start,
    )
    annotation_budget = MAX_ZOTERO_CALLBACK_BYTES - (
        ZOTERO_SYNC_AUTO_IMPORT_RESERVE_BYTES if auto_import_version is not None else 0
    )
    encoded_updates_size = 0
    encoded_failures_size = 0
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
            candidate_failure = {
                "item_key": item_key,
                "error_code": (
                    "zotero_attachment_not_found"
                    if exc.code == "zotero_item_not_found"
                    else exc.code
                ),
            }
            candidate_size = zotero_callback_payload_size(candidate_failure)
            projected_size = (
                callback_base_size
                + _array_growth(encoded_updates_size, len(updates))
                + _array_growth(
                    encoded_failures_size + candidate_size,
                    len(failures) + 1,
                )
            )
            if projected_size > annotation_budget:
                break
            failures.append(candidate_failure)
            encoded_failures_size += candidate_size
            continue
        try:
            annotations_json = _annotations_json(annotations)
        except ZoteroJobError as exc:
            candidate_failure = {"item_key": item_key, "error_code": exc.code}
            candidate_size = zotero_callback_payload_size(candidate_failure)
            projected_size = (
                callback_base_size
                + _array_growth(encoded_updates_size, len(updates))
                + _array_growth(
                    encoded_failures_size + candidate_size,
                    len(failures) + 1,
                )
            )
            if projected_size > annotation_budget:
                break
            failures.append(candidate_failure)
            encoded_failures_size += candidate_size
            continue
        candidate_update = {
            "item_key": item_key,
            "attachment_key": attachment_key,
            "annotations_json": annotations_json,
        }
        candidate_size = zotero_callback_payload_size(candidate_update)
        projected_size = (
            callback_base_size
            + _array_growth(
                encoded_updates_size + candidate_size,
                len(updates) + 1,
            )
            + _array_growth(encoded_failures_size, len(failures))
        )
        if projected_size > annotation_budget:
            break
        updates.append(candidate_update)
        encoded_updates_size += candidate_size

    auto_imports: list[dict[str, Any]] = []
    encoded_auto_imports_size = 0
    library_version: int | None = None
    auto_import_caught_up_version: int | None = None
    if auto_import_version is not None:
        new_items, observed_version, has_more = client.items_since(
            auto_import_version,
            start=auto_import_start,
            limit=MAX_AUTO_IMPORT_ITEMS,
            is_active=is_active,
        )
        selected_items = _bounded_version_batch(new_items)
        library_version = observed_version
        auto_import_truncated = False
        for item in selected_items:
            _require_active(is_active)
            key = str(item.get("key") or "")
            if not key:
                auto_import_truncated = True
                break
            prepared = _prepare_import_item(
                task_id=task_id,
                client=client,
                item=item,
                item_key=key,
                uploaded_keys=uploaded_keys,
            )
            prepared_size = zotero_callback_payload_size(prepared)
            projected_size = (
                callback_base_size
                + _array_growth(encoded_updates_size, len(updates))
                + _array_growth(encoded_failures_size, len(failures))
                + _array_growth(
                    encoded_auto_imports_size + prepared_size,
                    len(auto_imports) + 1,
                )
            )
            if projected_size > MAX_ZOTERO_CALLBACK_BYTES:
                _discard_prepared_item(prepared, uploaded_keys=uploaded_keys)
                auto_import_truncated = True
                break
            auto_imports.append(prepared)
            encoded_auto_imports_size += prepared_size
        if not has_more and not auto_import_truncated:
            auto_import_caught_up_version = observed_version
    return {
        "updates": updates,
        "failures": failures,
        "auto_imports": auto_imports,
        "library_version": library_version,
        "auto_import_base_version": auto_import_version,
        "auto_import_base_start": auto_import_start,
        "auto_import_caught_up_version": auto_import_caught_up_version,
    }


def _prepare_import_item(
    *,
    task_id: str,
    client: ZoteroClient,
    item: dict[str, Any] | None,
    item_key: str,
    uploaded_keys: list[str],
) -> dict[str, Any]:
    _require_zotero_key(item_key)
    if item is None:
        return _failed_item(item_key, "zotero_item_not_found")
    data = item.get("data") or {}
    if data.get("itemType") not in IMPORTABLE_ITEM_TYPES:
        return _failed_item(
            item_key,
            "zotero_item_not_supported",
            version=_item_version(item),
        )
    object_key: str | None = None
    try:
        children = client.children(item_key)
        attachment = _stored_pdf(children)
        source_url: str | None = None
        if attachment is not None:
            attachment_key = str(attachment.get("key") or "")
            _require_zotero_key(attachment_key)
            pdf = client.download_attachment(attachment_key)
            import_source = "pdf_attachment"
        else:
            attachment_key = ""
            pdf, source_url = _resolve_open_pdf(data)
            import_source = "url"
        _validate_pdf(pdf)
        object_key = f"zotero-imports/{task_id}/{item_key}.pdf"
        s3_service.upload_bytes_to_key(pdf, object_key, "application/pdf")
        uploaded_keys.append(object_key)
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
            "version": _item_version(item),
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
        if object_key is not None:
            _delete_uploaded_keys([object_key])
            uploaded_keys.remove(object_key)
        return _failed_item(
            item_key,
            exc.code,
            title=str(data.get("title") or ""),
            version=_item_version(item),
        )


def _delete_uploaded_keys(object_keys: list[str]) -> None:
    for object_key in reversed(object_keys):
        try:
            s3_service.delete_file(object_key)
        except Exception:
            logger.warning(
                "job.zotero_import.cleanup_failed",
                extra={"object_key": object_key},
            )


def _annotations_json(annotations: list[dict[str, Any]]) -> str:
    stable = []
    for value in annotations:
        key = str(value.get("key") or "")
        if not key:
            continue
        _require_zotero_key(key)
        stable.append({"key": key, "data": value.get("data") or {}})
    serialized = json.dumps(stable, separators=(",", ":"), sort_keys=True)
    if len(serialized.encode()) > MAX_ANNOTATIONS_BYTES:
        raise ZoteroJobError("zotero_annotations_too_large")
    return serialized


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
    metadata = {
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
    _validate_metadata(metadata)
    return metadata


def _require_zotero_key(value: str) -> str:
    if ZOTERO_KEY.fullmatch(value) is None:
        raise ZoteroJobError("zotero_request_invalid")
    return value


def _validate_metadata(metadata: dict[str, Any]) -> None:
    scalar_limits = {
        "title": 2_000,
        "abstract": 200_000,
        "publish_date": 128,
        "doi": 512,
        "date_added": 64,
        "venue": 2_000,
    }
    if any(
        value is not None and len(str(value)) > limit
        for name, limit in scalar_limits.items()
        if (value := metadata.get(name)) is not None
    ):
        raise ZoteroJobError("zotero_item_too_large")
    for field_name, limit in (
        ("authors", 100),
        ("tags", 100),
        ("collection_keys", 100),
    ):
        values = metadata.get(field_name) or []
        if len(values) > limit:
            raise ZoteroJobError("zotero_item_too_large")
        if field_name == "collection_keys":
            for value in values:
                _require_zotero_key(str(value))
        elif any(len(str(value)) > 512 for value in values):
            raise ZoteroJobError("zotero_item_too_large")


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
    transient_error: ZoteroJobError | None = None
    for candidate in candidates:
        try:
            return _fetch_public_pdf(candidate), candidate
        except ZoteroJobError as exc:
            if exc.code in {"zotero_unavailable", "zotero_rate_limited"}:
                transient_error = exc
            continue
    if transient_error is not None:
        raise transient_error
    raise ZoteroJobError("zotero_pdf_unavailable")


def _fetch_public_pdf(url: str) -> bytes:
    with requests.Session() as session:
        session.trust_env = False
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
                raise ZoteroJobError("zotero_unavailable") from exc
            try:
                _require_global_peer(response)
                if response.is_redirect or response.is_permanent_redirect:
                    location = response.headers.get("Location")
                    if not location:
                        raise ZoteroJobError("zotero_pdf_unavailable")
                    current = urljoin(current, location)
                    continue
                if response.status_code == 429:
                    raise ZoteroJobError("zotero_rate_limited")
                if response.status_code >= 500:
                    raise ZoteroJobError("zotero_unavailable")
                response.raise_for_status()
                return _bounded_response_bytes(response)
            except requests.RequestException as exc:
                raise ZoteroJobError("zotero_pdf_unavailable") from exc
            finally:
                response.close()
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


def _require_global_peer(response: requests.Response) -> None:
    raw = response.raw
    connection = getattr(raw, "_connection", None) or getattr(raw, "connection", None)
    peer_socket = getattr(connection, "sock", None)
    if peer_socket is None:
        original = getattr(raw, "_original_response", None)
        file_pointer = getattr(original, "fp", None)
        peer_socket = getattr(getattr(file_pointer, "raw", None), "_sock", None)
    if peer_socket is None:
        raise ZoteroJobError("zotero_pdf_unsafe_address")
    try:
        peer = peer_socket.getpeername()
        address = peer[0]
        ip = ipaddress.ip_address(address)
    except (AttributeError, IndexError, TypeError, ValueError, OSError) as exc:
        raise ZoteroJobError("zotero_pdf_unsafe_address") from exc
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
    item_key: str,
    code: str,
    *,
    title: str | None = None,
    version: int | None = None,
) -> dict[str, Any]:
    return {
        "item_key": item_key,
        "version": version,
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
    return items[:MAX_AUTO_IMPORT_ITEMS]


def _same_origin(left: str, right: str) -> bool:
    def origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlsplit(url)
        port = parsed.port
        if port is None:
            port = (
                443
                if parsed.scheme == "https"
                else 80
                if parsed.scheme == "http"
                else None
            )
        return parsed.scheme.casefold(), (parsed.hostname or "").casefold(), port

    return origin(left) == origin(right)
