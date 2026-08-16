from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit

import requests

logger = logging.getLogger(__name__)

ZOTERO_API_BASE = "https://api.zotero.org"
MAX_RETRIES = 3
MAX_REDIRECTS = 5
IMPORTABLE_ITEM_TYPES = ("journalArticle", "conferencePaper", "preprint")
MAX_BACKOFF_SECONDS = 10
MAX_ATTACHMENT_CHILDREN_PER_ITEM = 1_000
_ZOTERO_KEY = re.compile(r"^[A-Z0-9]{8}$")


@dataclass(frozen=True, slots=True)
class ZoteroApiPage:
    items: tuple[dict[str, Any], ...]
    total_count: int
    library_version: int | None


class ZoteroAttachmentScanLimitError(RuntimeError):
    pass


class ZoteroApiClient:
    """Read-only Zotero Web API v3 client."""

    def __init__(self, zotero_user_id: str, api_key: str):
        self.zotero_user_id = zotero_user_id
        self._session = requests.Session()
        self._session.trust_env = False
        self._api_headers = {
            "Zotero-API-Key": api_key,
            "Zotero-API-Version": "3",
        }

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> ZoteroApiClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def _user_base(self) -> str:
        return f"{ZOTERO_API_BASE}/users/{self.zotero_user_id}"

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                current_url = url
                request_params = params
                redirects = 0
                while True:
                    response = self._session.request(
                        method,
                        current_url,
                        params=request_params,
                        timeout=60,
                        allow_redirects=False,
                        stream=stream,
                        headers=self._api_headers,
                    )
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    try:
                        location = response.headers.get("Location")
                        if not location or redirects >= MAX_REDIRECTS:
                            raise requests.exceptions.TooManyRedirects(
                                response=response
                            )
                        next_url = urljoin(current_url, location)
                        if not _same_origin(next_url, ZOTERO_API_BASE):
                            raise requests.exceptions.InvalidURL(
                                "Zotero metadata endpoint redirected across origins",
                                response=response,
                            )
                        current_url = next_url
                        request_params = None
                        redirects += 1
                    finally:
                        response.close()
                if response.status_code == 429:
                    retry_after = _safe_retry_after(response)
                    logger.warning(
                        "zotero.api.rate_limited",
                        extra={
                            "method": method,
                            "retry_after_seconds": retry_after,
                            "attempt": attempt + 1,
                            "max_attempts": MAX_RETRIES,
                        },
                    )
                    # Record an error so a persistent 429 surfaces real context
                    # instead of the generic RuntimeError below.
                    last_error = requests.HTTPError(
                        f"429 Too Many Requests for url: {url}", response=response
                    )
                    response.close()
                    time.sleep(retry_after)
                    continue
                backoff = response.headers.get("Backoff")
                if backoff:
                    time.sleep(_safe_header_seconds(response, "Backoff", 0))
                response.raise_for_status()
                return response
            except requests.RequestException as exc:
                last_error = exc
                resp = getattr(exc, "response", None)
                status = resp.status_code if resp is not None else "no response"
                logger.warning(
                    "zotero.api.request_failed",
                    extra={
                        "method": method,
                        "status_code": status,
                        "attempt": attempt + 1,
                        "max_attempts": MAX_RETRIES,
                        "exception_type": type(exc).__name__,
                    },
                )
                if resp is not None:
                    resp.close()
                if isinstance(
                    exc,
                    (
                        requests.exceptions.InvalidURL,
                        requests.exceptions.TooManyRedirects,
                    ),
                ):
                    raise
                if isinstance(status, int) and 400 <= status < 500 and status != 429:
                    raise
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2**attempt)
        logger.error(
            "zotero.api.retries_exhausted",
            extra={"method": method, "max_attempts": MAX_RETRIES},
        )
        raise last_error or RuntimeError("Zotero API request failed")

    def get_top_importable_items_page(
        self,
        *,
        limit: int = 25,
        start: int = 0,
        query: str | None = None,
        collection_key: str | None = None,
        item_type: str | None = None,
        sort: str = "dateModified",
        direction: str = "desc",
    ) -> ZoteroApiPage:
        url = (
            f"{self._user_base}/collections/{collection_key}/items/top"
            if collection_key
            else f"{self._user_base}/items/top"
        )
        params = {
            "limit": min(limit, 100),
            "start": start,
            "sort": sort,
            "direction": direction,
            "itemType": item_type or " || ".join(IMPORTABLE_ITEM_TYPES),
        }
        if query:
            params["q"] = query
            params["qmode"] = "titleCreatorYear"
        response = self._request("GET", url, params=params)
        try:
            items = response.json()
            if not isinstance(items, list):
                items = []
            filtered = tuple(
                item
                for item in items
                if item.get("data", {}).get("itemType") in IMPORTABLE_ITEM_TYPES
            )
            return ZoteroApiPage(
                items=filtered,
                total_count=_header_int(response, "Total-Results") or len(filtered),
                library_version=_header_int(response, "Last-Modified-Version"),
            )
        finally:
            response.close()

    def get_collections_page(
        self,
        *,
        limit: int = 100,
        start: int = 0,
    ) -> ZoteroApiPage:
        response = self._request(
            "GET",
            f"{self._user_base}/collections",
            params={"limit": min(limit, 100), "start": start, "sort": "title"},
        )
        try:
            items = response.json()
            if not isinstance(items, list):
                items = []
            return ZoteroApiPage(
                items=tuple(items),
                total_count=_header_int(response, "Total-Results") or len(items),
                library_version=_header_int(response, "Last-Modified-Version"),
            )
        finally:
            response.close()

    def current_library_version(self) -> int | None:
        response = self._request(
            "GET",
            f"{self._user_base}/items/top",
            params={"limit": 1},
        )
        try:
            return _header_int(response, "Last-Modified-Version")
        finally:
            response.close()

    def key_info(self) -> dict[str, Any]:
        response = self._request("GET", f"{ZOTERO_API_BASE}/keys/current")
        try:
            payload = response.json()
            return payload if isinstance(payload, dict) else {}
        finally:
            response.close()

    def get_stored_pdf_parent_keys(
        self,
        item_keys: list[str],
        *,
        max_children_per_item: int = MAX_ATTACHMENT_CHILDREN_PER_ITEM,
    ) -> set[str]:
        """Classify only visible papers, failing instead of truncating silently."""
        parents: set[str] = set()
        for item_key in item_keys:
            if _ZOTERO_KEY.fullmatch(item_key) is None:
                raise ValueError("zotero_item_key_invalid")
            url = f"{self._user_base}/items/{item_key}/children"
            start = 0
            while start < max_children_per_item:
                page_limit = min(100, max_children_per_item - start)
                response = self._request(
                    "GET",
                    url,
                    params={
                        "itemType": "attachment",
                        "limit": page_limit,
                        "start": start,
                    },
                )
                try:
                    values = response.json()
                    children = values if isinstance(values, list) else []
                    total = _header_int(response, "Total-Results")
                finally:
                    response.close()
                if any(
                    self._attachment_is_pdf(data) and self._attachment_is_stored(data)
                    for child in children
                    if isinstance(child, dict)
                    and isinstance((data := child.get("data")), dict)
                ):
                    parents.add(item_key)
                    break
                scanned = start + len(children)
                if not children or (total is not None and scanned >= total):
                    break
                start = scanned
            else:
                raise ZoteroAttachmentScanLimitError(
                    "Zotero attachment classification exceeded its safety limit"
                )
        return parents

    @staticmethod
    def _attachment_is_pdf(data: dict[str, Any]) -> bool:
        """True if an attachment's ``data`` describes a PDF (by content type or filename)."""
        content_type = (data.get("contentType") or "").lower()
        filename = (data.get("filename") or "").lower()
        return content_type == "application/pdf" or filename.endswith(".pdf")

    @staticmethod
    def _attachment_is_stored(data: dict[str, Any]) -> bool:
        """True if the attachment's file is stored in Zotero's cloud (downloadable via API).

        ``linkMode`` ``"imported_file"`` / ``"imported_url"`` are stored copies;
        ``"linked_url"`` / ``"linked_file"`` are mere references the file API cannot
        return as a usable PDF.
        """
        return (data.get("linkMode") or "").lower() in ("imported_file", "imported_url")


def _header_int(response: requests.Response, name: str) -> int | None:
    value = response.headers.get(name)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _safe_retry_after(response: requests.Response) -> int:
    return _safe_header_seconds(response, "Retry-After", 2)


def _safe_header_seconds(
    response: requests.Response,
    name: str,
    default: int,
) -> int:
    value = _header_int(response, name)
    return min(max(value if value is not None else default, 0), MAX_BACKOFF_SECONDS)


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
