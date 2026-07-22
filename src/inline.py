"""Translate MediaItems into Telegram inline query results.

Telegram has a different result type per media shape, and each has its own
required fields. Notably ``InlineQueryResultCachedSticker`` only accepts a
``file_id`` already uploaded to Telegram, so Klipy stickers are delivered as
animations rather than native Telegram stickers. They look right in the chat;
they just are not addable to a sticker pack.
"""

from __future__ import annotations

from .media import STILL_FORMATS, Asset, MediaItem, MediaType

# Telegram rejects result IDs longer than 64 bytes.
MAX_ID_LEN = 64

# Cap the bytes we ask the client to fetch and cache per result. Klipy's
# reported sizes are exact (verified against Content-Length), so these are
# reliable. The hd gif of a single item can be 15 MB while its hd mp4 is
# 494 KB, so without a cap one result could outweigh a whole page.
#
# These caps were originally added to chase the macOS client's MediaBox
# stack-overflow. That turned out to be a mislabelled thumbnail (see
# ``_THUMB_MIME``), not volume — a stack overflow is a recursion signature, not
# a memory one. The caps are kept because they are independently worthwhile.
MAX_ANIMATION_BYTES = 1024 * 1024
MAX_STILL_BYTES = 512 * 1024

# Telegram allows only these three types in ``thumbnail_mime_type``, and the
# client selects a decoder from the declared type before it sees the bytes.
# Every other media URL we send is fetched straight from Klipy's CDN, which
# returns a correct Content-Type, so this field is the only place a client can
# be told something the bytes contradict.
#
# It previously mapped png and webp to image/jpeg, and webm to video/mp4, to
# satisfy the enum. Klipy stickers ship png/webp/gif/webm and no jpg, so every
# sticker result carried a png or webp labelled as JPEG. Thumbnails are what
# the client decodes while scrolling the result strip, which is where the macOS
# client was seen to stack-overflow.
_THUMB_MIME = {
    "jpg": "image/jpeg",
    "gif": "image/gif",
    "mp4": "video/mp4",
}

# Ordered by preference: a still costs the client least, and mp4 beats gif for
# the same frames. A rendition outside this set is skipped rather than
# relabelled, so some results ship with no thumbnail. Telegram renders those
# from the full media instead.
DECLARED_THUMB_FORMATS = ("jpg", "mp4", "gif")

# Photo and video results have no mime field, so the client learns the type
# from the CDN's Content-Type and png/webp are safe there. The constraint we
# are under is "never declare a type the bytes contradict", not "never send
# webp" — so these results keep the wider, still-first choice they had.
SNIFFED_THUMB_FORMATS = (*STILL_FORMATS, "gif", "mp4")


def thumbnail(item: MediaItem) -> Asset | None:
    """Thumbnail for results that declare ``thumbnail_mime_type``.

    Restricted to formats Telegram lets us name honestly, because the client
    chooses a decoder from the declared type before fetching the bytes.
    """
    return item.preview(*DECLARED_THUMB_FORMATS, max_bytes=MAX_STILL_BYTES)


def _sniffed_thumbnail(item: MediaItem) -> Asset | None:
    """Thumbnail for results that carry no mime field."""
    return item.preview(*SNIFFED_THUMB_FORMATS, max_bytes=MAX_STILL_BYTES)


def _result_id(item: MediaItem, index: int) -> str:
    return f"{index}:{item.id}"[:MAX_ID_LEN]


def _animation_result(item: MediaItem, result_id: str) -> dict | None:
    """Prefer mp4 over gif: same visual, far smaller payload for Telegram.

    Only genuine mp4 goes in ``mpeg4_url``. Telegram expects H.264 MP4 there,
    and Klipy stickers ship webm but no mp4 — sending webm made the client
    fetch a container it does not expect, so those fall through to gif.
    """
    thumb = thumbnail(item)
    mp4 = item.best("mp4", max_bytes=MAX_ANIMATION_BYTES)
    if mp4:
        result = {
            "type": "mpeg4_gif",
            "id": result_id,
            "mpeg4_url": mp4.url,
            "mpeg4_width": mp4.width,
            "mpeg4_height": mp4.height,
        }
    else:
        gif = item.best("gif", max_bytes=MAX_ANIMATION_BYTES)
        if not gif:
            return None
        result = {
            "type": "gif",
            "id": result_id,
            "gif_url": gif.url,
            "gif_width": gif.width,
            "gif_height": gif.height,
        }

    if thumb:
        result["thumbnail_url"] = thumb.url
        result["thumbnail_mime_type"] = _THUMB_MIME[thumb.fmt]
    if item.title:
        result["title"] = item.title
    return result


def _photo_result(item: MediaItem, result_id: str) -> dict | None:
    photo = item.best(*STILL_FORMATS, max_bytes=MAX_STILL_BYTES)
    if not photo:
        # Some "memes" come back animated; fall through rather than drop them.
        return _animation_result(item, result_id)
    thumb = _sniffed_thumbnail(item) or photo
    result = {
        "type": "photo",
        "id": result_id,
        "photo_url": photo.url,
        "thumbnail_url": thumb.url,
        "photo_width": photo.width,
        "photo_height": photo.height,
    }
    if item.title:
        result["title"] = item.title
    return result


def _video_result(item: MediaItem, result_id: str) -> dict | None:
    video = item.best("mp4", max_bytes=MAX_ANIMATION_BYTES)
    if not video:
        return _animation_result(item, result_id)
    thumb = _sniffed_thumbnail(item)
    # Telegram requires both thumbnail_url and title on video results.
    return {
        "type": "video",
        "id": result_id,
        "video_url": video.url,
        "mime_type": "video/mp4",
        "thumbnail_url": thumb.url if thumb else video.url,
        "video_width": video.width,
        "video_height": video.height,
        "title": item.title or "Clip",
    }


_BUILDERS = {
    MediaType.GIF: _animation_result,
    MediaType.STICKER: _animation_result,
    MediaType.MEME: _photo_result,
    MediaType.CLIP: _video_result,
}


def build_results(items: list[MediaItem], media_type: MediaType) -> list[dict]:
    """Build Telegram inline results, skipping items we cannot render."""
    build = _BUILDERS[media_type]
    results = []
    for index, item in enumerate(items):
        result = build(item, _result_id(item, index))
        if result is not None:
            results.append(result)
    return results


def no_results_article(query: str, media_type: MediaType) -> dict:
    """A single explanatory result, so the user sees why the list is empty."""
    return {
        "type": "article",
        "id": "empty",
        "title": f"No {media_type.label}s found",
        "description": f"Nothing matched {query!r}. Try a different search.",
        "input_message_content": {
            "message_text": f"No {media_type.label}s found for {query!r}."
        },
    }


def unavailable_article(media_type: MediaType) -> dict:
    """Shown when Klipy has no route for a media family on the current key."""
    return {
        "type": "article",
        "id": "unavailable",
        "title": f"{media_type.label.capitalize()}s are not available",
        "description": "This Klipy key has no access to this content type yet.",
        "input_message_content": {
            "message_text": (
                f"{media_type.label.capitalize()}s are not available on this "
                f"Klipy key — the endpoint returns 404. Requesting production "
                f"access in the Klipy partner panel may enable it."
            )
        },
    }
