"""Domain types for Klipy media, independent of both Klipy and Telegram."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MediaType(str, Enum):
    """Klipy content families. The value is the API path segment."""

    GIF = "gifs"
    STICKER = "stickers"
    MEME = "memes"
    CLIP = "clips"

    @property
    def label(self) -> str:
        return _LABELS[self]


_LABELS = {
    MediaType.GIF: "GIF",
    MediaType.STICKER: "sticker",
    MediaType.MEME: "meme",
    MediaType.CLIP: "clip",
}

# Formats we know how to hand to Telegram. Anything else is ignored.
ANIMATED_FORMATS = ("mp4", "gif", "webm")
STILL_FORMATS = ("jpg", "jpeg", "png", "webp")


@dataclass(frozen=True)
class Asset:
    """A single renditon of a media item at one size and format."""

    url: str
    fmt: str
    width: int = 0
    height: int = 0
    size: int = 0

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class MediaItem:
    """One searchable item, carrying every rendition Klipy returned for it."""

    id: str
    title: str
    assets: tuple[Asset, ...]

    def best(
        self, *formats: str, largest: bool = True, max_bytes: int = 0
    ) -> Asset | None:
        """Pick a rendition, preferring earlier formats in the given order.

        Falls through the format list so a caller can express "mp4 if you have
        it, otherwise gif" without knowing what Klipy actually returned.

        ``max_bytes`` drops renditions larger than the cap when the size is
        known. If every rendition of a format exceeds it, the smallest is used
        rather than falling through to a worse format.
        """
        for fmt in formats:
            matches = [a for a in self.assets if a.fmt == fmt]
            if not matches:
                continue
            if max_bytes:
                within = [a for a in matches if 0 < a.size <= max_bytes]
                if within:
                    matches = within
                elif all(a.size for a in matches):
                    return min(matches, key=lambda a: a.size)
            # Assets with unknown dimensions sort as 0, so a sized rendition
            # always wins over an unsized one when asking for the largest.
            return max(matches, key=lambda a: a.area) if largest else min(
                matches, key=lambda a: (a.area or 1 << 30)
            )
        return None

    def preview(self, *formats: str, max_bytes: int = 0) -> Asset | None:
        """Smallest rendition for use as a thumbnail.

        Callers pass the formats they are able to describe truthfully to the
        consumer; a rendition we cannot label honestly is worse than no
        thumbnail at all. Defaults to any known format for callers that only
        need a representative asset rather than something to hand to Telegram.
        """
        candidates = formats or (*STILL_FORMATS, *ANIMATED_FORMATS)
        return self.best(*candidates, largest=False, max_bytes=max_bytes)
