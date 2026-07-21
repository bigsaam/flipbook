"""Parse an inline query string into a media type plus a search term.

Telegram gives an inline bot a single free-text box, so the media family is
selected with a short prefix:

    @fpbot dancing cat        -> GIF (the default)
    @fpbot s: dancing cat     -> sticker
    @fpbot meme: distracted   -> meme
    @fpbot c: star wars       -> clip

Prefixes are kept to one letter so the whole invocation stays short to type.
"""

from __future__ import annotations

from dataclasses import dataclass

from .media import MediaType

PREFIXES = {
    "g": MediaType.GIF,
    "gif": MediaType.GIF,
    "s": MediaType.STICKER,
    "sticker": MediaType.STICKER,
    "stickers": MediaType.STICKER,
    "m": MediaType.MEME,
    "meme": MediaType.MEME,
    "memes": MediaType.MEME,
    "c": MediaType.CLIP,
    "clip": MediaType.CLIP,
    "clips": MediaType.CLIP,
}

DEFAULT_MEDIA_TYPE = MediaType.GIF


@dataclass(frozen=True)
class Query:
    media_type: MediaType
    text: str


def parse(raw: str) -> Query:
    """Split an optional ``prefix:`` off the front of the query."""
    stripped = raw.strip()
    if ":" in stripped:
        prefix, _, rest = stripped.partition(":")
        media_type = PREFIXES.get(prefix.strip().lower())
        if media_type is not None:
            return Query(media_type=media_type, text=rest.strip())
    return Query(media_type=DEFAULT_MEDIA_TYPE, text=stripped)


def parse_page(offset: str) -> int:
    """Telegram echoes back whatever next_offset we sent; we store the page."""
    try:
        page = int(offset)
    except (TypeError, ValueError):
        return 1
    return page if page > 0 else 1
