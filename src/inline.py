"""Translate MediaItems into Telegram inline query results.

Telegram has a different result type per media shape, and each has its own
required fields. Notably ``InlineQueryResultCachedSticker`` only accepts a
``file_id`` already uploaded to Telegram, so Klipy stickers are delivered as
animations rather than native Telegram stickers. They look right in the chat;
they just are not addable to a sticker pack.
"""

from __future__ import annotations

from .media import STILL_FORMATS, MediaItem, MediaType

# Telegram rejects result IDs longer than 64 bytes.
MAX_ID_LEN = 64

_THUMB_MIME = {
    "jpg": "image/jpeg",
    "png": "image/jpeg",  # Telegram only allows jpeg/gif/mp4 here.
    "webp": "image/jpeg",
    "gif": "image/gif",
    "mp4": "video/mp4",
    "webm": "video/mp4",
}


def _result_id(item: MediaItem, index: int) -> str:
    return f"{index}:{item.id}"[:MAX_ID_LEN]


def _animation_result(item: MediaItem, result_id: str) -> dict | None:
    """Prefer mp4 over gif: same visual, far smaller payload for Telegram."""
    thumb = item.preview()
    mp4 = item.best("mp4", "webm")
    if mp4:
        result = {
            "type": "mpeg4_gif",
            "id": result_id,
            "mpeg4_url": mp4.url,
            "mpeg4_width": mp4.width,
            "mpeg4_height": mp4.height,
        }
    else:
        gif = item.best("gif")
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
        result["thumbnail_mime_type"] = _THUMB_MIME.get(thumb.fmt, "image/jpeg")
    if item.title:
        result["title"] = item.title
    return result


def _photo_result(item: MediaItem, result_id: str) -> dict | None:
    photo = item.best(*STILL_FORMATS)
    if not photo:
        # Some "memes" come back animated; fall through rather than drop them.
        return _animation_result(item, result_id)
    thumb = item.preview() or photo
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
    video = item.best("mp4", "webm")
    if not video:
        return _animation_result(item, result_id)
    thumb = item.preview()
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
