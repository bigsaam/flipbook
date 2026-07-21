"""Klipy API client.

Klipy replaced Tenor for third-party GIF search after Google shut the Tenor API
down on 2026-06-30. Its search/trending endpoints are shaped per media family:

    https://api.klipy.com/api/v1/<API_KEY>/<media_type>/search?q=...

Verified item shape for /gifs/ (see scripts/probe.py):

    {id, slug, title, tags, type, blur_preview,
     file: {hd|md|sm|xs: {gif|webp|jpg|mp4|webm: {url, width, height, size}}}}

The format is the parent key rather than a field, and the nesting is not
documented or contractually stable, so ``_collect_assets`` walks the tree
generically and treats the parent key as a hint. Re-run the probe before
assuming this shape holds for stickers, memes, or clips.
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


class KlipyUnavailable(KlipyError):
    """The endpoint does not exist for this key.

    /memes/ 404s on test keys, so this is reported to the user as "not
    available" rather than silently looking like an empty search.
    """


def _normalise(fmt: str) -> str:
    return "jpg" if fmt == "jpeg" else fmt


def _guess_format(node: dict, url: str, hint: str | None) -> str | None:
    """Determine an asset's format.

    Klipy nests renditions as file -> <quality> -> <format> -> {url,...}, so the
    parent key is the authoritative format and is passed down as ``hint``. The
    metadata and extension checks are fallbacks for shapes that do not nest that
    way (other media families, or future changes).
    """
    if hint in _KNOWN_FORMATS:
        return _normalise(hint)

    for key in ("type", "format", "content_type", "mime_type"):
        raw = node.get(key)
        if isinstance(raw, str):
            for fmt in _KNOWN_FORMATS:
                if fmt in raw.lower():
                    return _normalise(fmt)

    path = url.split("?", 1)[0].lower()
    for fmt in _KNOWN_FORMATS:
        if path.endswith(f".{fmt}"):
            return _normalise(fmt)
    return None


def _as_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _collect_assets(
    node: object, found: list[Asset], hint: str | None = None
) -> None:
    """Recursively gather every {url, width, height} rendition under a node.

    ``hint`` carries the key a dict was reached under, which for Klipy is the
    format name. Only ``http`` URLs are collected, which also skips the
    ``blur_preview`` data URI Klipy attaches to each item.
    """
    if isinstance(node, dict):
        url = node.get("url")
        if isinstance(url, str) and url.startswith("http"):
            fmt = _guess_format(node, url, hint)
            if fmt:
                found.append(
                    Asset(
                        url=url,
                        fmt=fmt,
                        width=_as_int(node.get("width")),
                        height=_as_int(node.get("height")),
                        size=_as_int(node.get("size")),
                    )
                )
        for key, value in node.items():
            _collect_assets(value, found, key if isinstance(key, str) else None)
    elif isinstance(node, list):
        for value in node:
            _collect_assets(value, found, hint)


_DIMENSION_KEYS = ("width", "height", "size")


def _merge_file_meta(file_node: object, meta: object) -> object:
    """Normalise the flat clip shape into the nested shape used elsewhere.

    /gifs/ and /stickers/ nest as ``{quality: {format: {url, width, height}}}``,
    but /clips/ returns ``{format: "url"}`` with dimensions in a parallel
    ``file_meta`` map. Wrapping the bare strings lets one walker handle both.
    """
    if not isinstance(file_node, dict):
        return file_node

    merged: dict[str, object] = {}
    for key, value in file_node.items():
        # Only wrap format-keyed URL strings. Wrapping every string would
        # mangle flat nodes that already carry "url" and "type" siblings.
        if (
            not isinstance(value, str)
            or key not in _KNOWN_FORMATS
            or not value.startswith("http")
        ):
            merged[key] = value
            continue
        entry: dict[str, object] = {"url": value}
        dims = meta.get(key) if isinstance(meta, dict) else None
        if isinstance(dims, dict):
            entry.update({k: v for k, v in dims.items() if k in _DIMENSION_KEYS})
        merged[key] = entry
    return merged


def _to_item(raw: dict) -> MediaItem | None:
    """Convert one Klipy result into a MediaItem, or None if it has no usable media."""
    # Verified against the live API: the key is "file" (singular). Falling back
    # to the whole item keeps other media families working if they differ.
    file_node = _merge_file_meta(raw.get("file"), raw.get("file_meta"))
    assets: list[Asset] = []
    _collect_assets(file_node if file_node else raw, assets)
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
            if response.status == 404:
                raise KlipyUnavailable(
                    f"Klipy has no {media_type.value}/{endpoint} route for this key"
                )
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
