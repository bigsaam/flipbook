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


class TestKlipyNormalisation:
    def test_walks_arbitrarily_nested_files(self):
        raw = {
            "id": 42,
            "title": "Nested",
            "files": {
                "hd": {"gif": {"url": "http://e/a.gif", "width": 480, "height": 270}},
                "sm": {"mp4": {"url": "http://e/a.mp4", "width": 240, "height": 135}},
            },
        }
        item = _to_item(raw)
        assert item is not None
        assert item.id == "42"
        assert {a.fmt for a in item.assets} == {"gif", "mp4"}

    def test_flat_files_shape_also_works(self):
        item = _to_item({"id": "b", "files": {"url": "http://e/b.gif"}})
        assert item is not None
        assert item.assets[0].fmt == "gif"

    def test_format_from_content_type_when_url_has_no_extension(self):
        item = _to_item(
            {"id": "c", "files": {"url": "http://e/render?id=9", "type": "video/mp4"}}
        )
        assert item is not None
        assert item.assets[0].fmt == "mp4"

    def test_item_with_no_usable_media_is_dropped(self):
        assert _to_item({"id": "d", "files": {}}) is None
        assert _to_item({"id": "e", "files": {"url": "http://e/f.txt"}}) is None

    def test_duplicate_urls_are_collapsed(self):
        raw = {
            "id": "f",
            "files": {
                "hd": {"gif": {"url": "http://e/same.gif"}},
                "md": {"gif": {"url": "http://e/same.gif"}},
            },
        }
        item = _to_item(raw)
        assert item is not None
        assert len(item.assets) == 1


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

    def test_unrenderable_items_are_skipped_not_crashed(self):
        item = self._item(Asset("http://e/a.svg", "svg", 10, 10))
        assert build_results([item], MediaType.GIF) == []

    def test_result_ids_are_unique_and_within_telegram_limit(self):
        items = [MediaItem(id="x" * 90, title="", assets=(
            Asset("http://e/a.mp4", "mp4", 1, 1),)) for _ in range(5)]
        ids = [r["id"] for r in build_results(items, MediaType.GIF)]
        assert len(set(ids)) == len(ids)
        assert all(len(i) <= 64 for i in ids)
