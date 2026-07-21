"""Klipy API client.

Klipy replaced Tenor for third-party GIF search after Google shut the Tenor API
down on 2026-06-30. Its search/trending endpoints are shaped per media family:

    https://api.klipy.com/api/v1/<API_KEY>/<media_type>/search?q=...

The exact nesting of the per-item ``files`` object is not pinned down by the
public docs and differs between media families, so ``_collect_assets`` walks the
response generically instead of hard-coding a path. Run ``scripts/probe.py`` to
dump the real shape for an account.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

import aiohttp

from .media import Asset, MediaItem, MediaType

log = logging.getLogger(__name__)

BASE_URL = "https://api.klipy.com/api/v1"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=6)

# Extensions we can map to a Telegram result type.
_KNOWN_FORMATS = ("mp4", "gif", "webm", "webp", "jpeg", "jpg", "png")


class KlipyError(RuntimeError):
    """Klipy returned a non-success response."""


def _guess_format(node: dict, url: str) -> str | None:
    """Determine an asset's format from its metadata, falling back to the URL."""
    for key in ("type", "format", "content_type", "mime_type"):
        raw = node.get(key)
        if isinstance(raw, str):
            for fmt in _KNOWN_FORMATS:
                if fmt in raw.lower():
                    return "jpg" if fmt == "jpeg" else fmt

    path = url.split("?", 1)[0].lower()
    for fmt in _KNOWN_FORMATS:
        if path.endswith(f".{fmt}"):
            return "jpg" if fmt == "jpeg" else fmt
    return None


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _collect_assets(node: object, found: list[Asset]) -> None:
    """Recursively gather every {url, width, height} rendition under a node."""
    if isinstance(node, dict):
        url = node.get("url")
        if isinstance(url, str) and url.startswith("http"):
            fmt = _guess_format(node, url)
            if fmt:
                found.append(
                    Asset(
                        url=url,
                        fmt=fmt,
                        width=_as_int(node.get("width")),
                        height=_as_int(node.get("height")),
                    )
                )
        for value in node.values():
            _collect_assets(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_assets(value, found)


def _to_item(raw: dict) -> MediaItem | None:
    """Convert one Klipy result into a MediaItem, or None if it has no usable media."""
    assets: list[Asset] = []
    _collect_assets(raw.get("files", raw), assets)
    if not assets:
        return None

    # De-duplicate by URL; Klipy repeats the same rendition across quality tiers.
    unique = tuple({a.url: a for a in assets}.values())
    identifier = str(raw.get("id") or raw.get("slug") or hash(unique[0].url))
    title = str(raw.get("title") or raw.get("name") or "").strip()
    return MediaItem(id=identifier, title=title, assets=unique)


class KlipyClient:
    """Thin async wrapper over the Klipy content APIs."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        *,
        rating: str = "pg-13",
        locale: str = "en_US",
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._rating = rating
        self._locale = locale

    async def fetch(
        self,
        media_type: MediaType,
        query: str,
        *,
        page: int = 1,
        per_page: int = 30,
    ) -> tuple[list[MediaItem], bool]:
        """Search, or return trending when the query is blank.

        Returns the items plus whether another page is available.
        """
        endpoint = "search" if query else "trending"
        url = f"{BASE_URL}/{quote(self._api_key, safe='')}/{media_type.value}/{endpoint}"
        params = {
            "page": str(page),
            "per_page": str(per_page),
            "locale": self._locale,
            "rating": self._rating,
        }
        if query:
            params["q"] = query

        async with self._session.get(
            url, params=params, timeout=REQUEST_TIMEOUT
        ) as response:
            if response.status != 200:
                body = (await response.text())[:200]
                raise KlipyError(f"Klipy {endpoint} returned {response.status}: {body}")
            payload = await response.json()

        if not payload.get("result", True):
            raise KlipyError(f"Klipy reported failure: {str(payload)[:200]}")

        data = payload.get("data") or {}
        raw_items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(raw_items, list):
            log.warning("Unexpected Klipy payload shape: %s", str(payload)[:300])
            return [], False

        items = [item for item in map(_to_item, raw_items) if item is not None]
        dropped = len(raw_items) - len(items)
        if dropped:
            log.info("Dropped %d/%d %s results with no usable rendition",
                     dropped, len(raw_items), media_type.value)

        return items, bool(data.get("has_next"))
