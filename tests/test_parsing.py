"""Tests for the pure logic: query routing, asset selection, result building."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from src.inline import build_results
from src.klipy import _to_item
from src.media import Asset, MediaItem, MediaType
from src.routing import parse, parse_page


class TestRouting:
    @pytest.mark.parametrize(
        "raw,expected_type,expected_text",
        [
            ("dancing cat", MediaType.GIF, "dancing cat"),
            ("", MediaType.GIF, ""),
            ("s: happy", MediaType.STICKER, "happy"),
            ("sticker:happy", MediaType.STICKER, "happy"),
            ("m: distracted", MediaType.MEME, "distracted"),
            ("c: star wars", MediaType.CLIP, "star wars"),
            ("  GIF:  spinning  ", MediaType.GIF, "spinning"),
        ],
    )
    def test_prefixes(self, raw, expected_type, expected_text):
        result = parse(raw)
        assert result.media_type is expected_type
        assert result.text == expected_text

    def test_unknown_prefix_is_treated_as_search_text(self):
        # "ratio: 16:9" is a search, not a media-type switch.
        result = parse("ratio: 16:9")
        assert result.media_type is MediaType.GIF
        assert result.text == "ratio: 16:9"

    @pytest.mark.parametrize(
        "offset,expected", [("", 1), ("0", 1), ("-3", 1), ("2", 2), ("junk", 1)]
    )
    def test_page_parsing_never_returns_invalid_page(self, offset, expected):
        assert parse_page(offset) == expected


class TestAssetSelection:
    def _item(self) -> MediaItem:
        return MediaItem(
            id="x",
            title="Test",
            assets=(
                Asset("http://e/s.jpg", "jpg", 100, 100),
                Asset("http://e/l.gif", "gif", 800, 800),
                Asset("http://e/s.gif", "gif", 200, 200),
                Asset("http://e/l.mp4", "mp4", 800, 800),
            ),
        )

    def test_best_prefers_format_order_over_size(self):
        # mp4 wins even though a gif of equal size exists.
        assert self._item().best("mp4", "gif").fmt == "mp4"

    def test_best_picks_largest_within_a_format(self):
        assert self._item().best("gif").url == "http://e/l.gif"

    def test_best_falls_through_missing_formats(self):
        assert self._item().best("webm", "gif").fmt == "gif"

    def test_preview_picks_smallest_still(self):
        assert self._item().preview().url == "http://e/s.jpg"

    def test_best_returns_none_when_nothing_matches(self):
        assert self._item().best("webm") is None


def _live_shape_item() -> dict:
    """The real /gifs/ item shape, captured from the live API via probe.py."""
    return {
        "id": 9647300348882249,
        "slug": "cat-scuba-cat-dance",
        "title": "Cat Scuba Cat Dance",
        "tags": ["cat", "dance"],
        "type": "gif",
        # Klipy attaches an inline base64 placeholder; it must never be
        # mistaken for a usable asset.
        "blur_preview": "data:image/jpeg;base64,/9j//gAQTGF2YzU5",
        "file": {
            "hd": {
                "gif": {"url": "https://s/a.gif", "width": 220, "height": 229,
                        "size": 273268},
                "webp": {"url": "https://s/a.webp", "width": 220, "height": 230,
                         "size": 71688},
                "jpg": {"url": "https://s/a.jpg", "width": 220, "height": 229,
                        "size": 8064},
                "mp4": {"url": "https://s/a.mp4", "width": 220, "height": 230,
                        "size": 75638},
                "webm": {"url": "https://s/a.webm", "width": 220, "height": 229,
                         "size": 60623},
            },
            "xs": {
                "gif": {"url": "https://s/x.gif", "width": 74, "height": 90},
                "jpg": {"url": "https://s/x.jpg", "width": 74, "height": 90},
            },
        },
    }


class TestKlipyNormalisation:
    def test_parses_the_live_gif_shape(self):
        item = _to_item(_live_shape_item())
        assert item is not None
        assert item.id == "9647300348882249"
        assert item.title == "Cat Scuba Cat Dance"
        assert {a.fmt for a in item.assets} == {"gif", "webp", "jpg", "mp4", "webm"}
        assert len(item.assets) == 7

    def test_blur_preview_data_uri_is_never_collected(self):
        item = _to_item(_live_shape_item())
        assert item is not None
        assert all(a.url.startswith("http") for a in item.assets)
        assert not any("base64" in a.url for a in item.assets)

    def test_format_comes_from_parent_key_not_extension(self):
        # Klipy URLs often have long hashes; some carry no extension at all.
        raw = {
            "id": "z",
            "file": {"hd": {"mp4": {"url": "https://s/34aQxa9DrNXvY", "width": 4,
                                    "height": 9}}},
        }
        item = _to_item(raw)
        assert item is not None
        assert item.assets[0].fmt == "mp4"

    def test_falls_back_to_whole_item_when_file_key_absent(self):
        # Other media families may not use the same envelope.
        item = _to_item({"id": "b", "media": {"url": "https://e/b.gif"}})
        assert item is not None
        assert item.assets[0].fmt == "gif"

    def test_format_from_content_type_when_no_hint_or_extension(self):
        item = _to_item(
            {"id": "c", "file": {"url": "https://e/render?id=9", "type": "video/mp4"}}
        )
        assert item is not None
        assert item.assets[0].fmt == "mp4"

    def test_item_with_no_usable_media_is_dropped(self):
        assert _to_item({"id": "d", "file": {}}) is None
        assert _to_item({"id": "e", "file": {"url": "https://e/f.txt"}}) is None

    def test_duplicate_urls_are_collapsed(self):
        raw = {
            "id": "f",
            "file": {
                "hd": {"gif": {"url": "https://e/same.gif"}},
                "md": {"gif": {"url": "https://e/same.gif"}},
            },
        }
        item = _to_item(raw)
        assert item is not None
        assert len(item.assets) == 1

    def test_parses_the_live_clip_shape(self):
        # /clips/ returns a flat {format: url} map with dimensions held in a
        # parallel file_meta object, unlike the nested /gifs/ shape.
        raw = {
            "slug": "star-wars-2--kqkEZgh9n",
            "title": "STAR WARS",
            "type": "clip",
            "url": "https://klipy.com/clips/star-wars-2",
            "file": {
                "mp4": "https://s/a.mp4",
                "gif": "https://s/a.gif",
                "webp": "https://s/a.webp",
            },
            "file_meta": {
                "mp4": {"width": 1280, "height": 534, "size": 287964},
                "gif": {"width": 320, "height": 133, "size": 339196},
                "webp": {"width": 320, "height": 133, "size": 148118},
            },
        }
        item = _to_item(raw)
        assert item is not None
        # Clips carry no "id" field, so the slug has to stand in.
        assert item.id == "star-wars-2--kqkEZgh9n"
        assert {a.fmt for a in item.assets} == {"mp4", "gif", "webp"}
        mp4 = item.best("mp4")
        assert mp4.width == 1280 and mp4.size == 287964

    def test_sizes_are_captured_from_the_live_shape(self):
        item = _to_item(_live_shape_item())
        assert item is not None
        assert item.best("mp4").size == 75638

    def test_selects_largest_gif_and_smallest_still_from_live_shape(self):
        item = _to_item(_live_shape_item())
        assert item is not None
        assert item.best("gif").url == "https://s/a.gif"
        assert item.preview().url == "https://s/x.jpg"


class TestResultBuilding:
    def _item(self, *assets: Asset) -> MediaItem:
        return MediaItem(id="i", title="T", assets=assets)

    def test_gif_prefers_mpeg4_over_gif(self):
        item = self._item(
            Asset("http://e/a.gif", "gif", 400, 400),
            Asset("http://e/a.mp4", "mp4", 400, 400),
        )
        results = build_results([item], MediaType.GIF)
        assert results[0]["type"] == "mpeg4_gif"
        assert results[0]["mpeg4_url"] == "http://e/a.mp4"

    def test_gif_falls_back_to_gif_type(self):
        item = self._item(Asset("http://e/a.gif", "gif", 400, 400))
        assert build_results([item], MediaType.GIF)[0]["type"] == "gif"

    def test_meme_builds_photo(self):
        item = self._item(Asset("http://e/a.jpg", "jpg", 600, 400))
        result = build_results([item], MediaType.MEME)[0]
        assert result["type"] == "photo"
        assert result["photo_url"] == "http://e/a.jpg"

    def test_animated_meme_falls_back_to_animation(self):
        item = self._item(Asset("http://e/a.mp4", "mp4", 600, 400))
        assert build_results([item], MediaType.MEME)[0]["type"] == "mpeg4_gif"

    def test_clip_builds_video_with_required_fields(self):
        item = self._item(Asset("http://e/a.mp4", "mp4", 600, 400))
        result = build_results([item], MediaType.CLIP)[0]
        assert result["type"] == "video"
        assert result["mime_type"] == "video/mp4"
        # Telegram rejects video results missing either of these.
        assert result["thumbnail_url"]
        assert result["title"]

    def test_webm_never_lands_in_mpeg4_url(self):
        # Klipy stickers ship webm but no mp4. Telegram requires H.264 MP4 in
        # mpeg4_url, so these must fall through to the gif result type.
        item = self._item(
            Asset("http://e/a.webm", "webm", 120, 120),
            Asset("http://e/a.gif", "gif", 120, 120),
        )
        result = build_results([item], MediaType.STICKER)[0]
        assert result["type"] == "gif"
        assert result["gif_url"] == "http://e/a.gif"
        assert "webm" not in str(result)

    def test_clip_video_never_uses_webm(self):
        item = self._item(Asset("http://e/a.webm", "webm", 600, 400))
        results = build_results([item], MediaType.CLIP)
        assert all(r.get("video_url", "").endswith(".mp4") for r in results)

    def test_oversized_rendition_is_rejected_for_a_smaller_one(self):
        item = self._item(
            Asset("http://e/huge.mp4", "mp4", 1920, 1080, size=9_000_000),
            Asset("http://e/small.mp4", "mp4", 320, 180, size=90_000),
        )
        result = build_results([item], MediaType.GIF)[0]
        assert result["mpeg4_url"] == "http://e/small.mp4"

    def test_smallest_is_used_when_every_rendition_is_oversized(self):
        item = self._item(
            Asset("http://e/big.mp4", "mp4", 1920, 1080, size=9_000_000),
            Asset("http://e/bigger.mp4", "mp4", 3840, 2160, size=20_000_000),
        )
        result = build_results([item], MediaType.GIF)[0]
        assert result["mpeg4_url"] == "http://e/big.mp4"

    def test_unknown_sizes_do_not_disqualify_a_rendition(self):
        item = self._item(Asset("http://e/a.mp4", "mp4", 400, 400))
        assert build_results([item], MediaType.GIF)[0]["mpeg4_url"] == "http://e/a.mp4"

    def test_unrenderable_items_are_skipped_not_crashed(self):
        item = self._item(Asset("http://e/a.svg", "svg", 10, 10))
        assert build_results([item], MediaType.GIF) == []

    def test_result_ids_are_unique_and_within_telegram_limit(self):
        items = [MediaItem(id="x" * 90, title="", assets=(
            Asset("http://e/a.mp4", "mp4", 1, 1),)) for _ in range(5)]
        ids = [r["id"] for r in build_results(items, MediaType.GIF)]
        assert len(set(ids)) == len(ids)
        assert all(len(i) <= 64 for i in ids)
