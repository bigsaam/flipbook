#!/usr/bin/env python3
"""Dump raw Klipy responses so the real payload shape can be confirmed.

The public Klipy docs do not pin down the nesting of the per-item ``files``
object, so ``src/klipy.py`` walks it generically. Run this once with a real key
to see what actually comes back, and to sanity-check that parsing finds assets.

    KLIPY_API_KEY=... python scripts/probe.py
    KLIPY_API_KEY=... python scripts/probe.py --media stickers --query cat
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402

from src.klipy import KlipyClient, _to_item  # noqa: E402
from src.media import MediaType  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--media",
        default="gifs",
        choices=[m.value for m in MediaType],
        help="Which Klipy content family to probe.",
    )
    parser.add_argument("--query", default="hello", help="Search term (blank = trending).")
    parser.add_argument("--raw", action="store_true", help="Print the full JSON payload.")
    args = parser.parse_args()

    api_key = os.environ.get("KLIPY_API_KEY", "").strip()
    if not api_key:
        print("Set KLIPY_API_KEY first.", file=sys.stderr)
        return 1

    media_type = MediaType(args.media)

    async with aiohttp.ClientSession() as session:
        url = f"https://api.klipy.com/api/v1/{api_key}/{media_type.value}/search"
        params = {"q": args.query, "per_page": "3", "page": "1"}
        async with session.get(url, params=params) as response:
            print(f"HTTP {response.status} {url}")
            payload = await response.json()

        if args.raw:
            print(json.dumps(payload, indent=2)[:8000])
            return 0

        data = (payload.get("data") or {}).get("data") or []
        print(f"\n{len(data)} raw items returned.\n")
        for index, raw in enumerate(data):
            print(f"--- item {index} keys: {sorted(raw.keys())}")
            print(json.dumps(raw.get("files", {}), indent=2)[:2000])
            item = _to_item(raw)
            if item is None:
                print(">>> PARSED: none (no usable rendition)\n")
                continue
            print(f">>> PARSED id={item.id} title={item.title!r}")
            for asset in item.assets:
                # Print URLs in full: truncating hides the extension, which
                # makes format detection look broken when it is not.
                print(f"      {asset.fmt:5} {asset.width}x{asset.height} {asset.url}")
            print()

        client = KlipyClient(session, api_key)
        items, has_next = await client.fetch(media_type, args.query, per_page=8)
        print(f"Client path: {len(items)} usable items, has_next={has_next}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
