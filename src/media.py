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

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class MediaItem:
    """One searchable item, carrying every rendition Klipy returned for it."""

    id: str
    title: str
    assets: tuple[Asset, ...]

    def best(self, *formats: str, largest: bool = True) -> Asset | None:
        """Pick a rendition, preferring earlier formats in the given order.

        Falls through the format list so a caller can express "mp4 if you have
        it, otherwise gif" without knowing what Klipy actually returned.
        """
        for fmt in formats:
            matches = [a for a in self.assets if a.fmt == fmt]
            if not matches:
                continue
            # Assets with unknown dimensions sort as 0, so a sized rendition
            # always wins over an unsized one when asking for the largest.
            return max(matches, key=lambda a: a.area) if largest else min(
                matches, key=lambda a: (a.area or 1 << 30)
            )
        return None

    def preview(self) -> Asset | None:
        """Smallest still or animated rendition, for use as a thumbnail."""
        return self.best(*STILL_FORMATS, *ANIMATED_FORMATS, largest=False)
