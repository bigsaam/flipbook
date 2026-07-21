"""Minimal async Telegram Bot API client — only the calls flipbook needs."""

from __future__ import annotations

import json
import logging

import aiohttp

log = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)


class TelegramError(RuntimeError):
    """The Bot API rejected a call."""


class TelegramClient:
    def __init__(self, session: aiohttp.ClientSession, token: str) -> None:
        self._session = session
        self._token = token

    async def _call(self, method: str, payload: dict) -> dict:
        url = f"{API_BASE}/bot{self._token}/{method}"
        async with self._session.post(
            url, json=payload, timeout=REQUEST_TIMEOUT
        ) as response:
            body = await response.json()
        if not body.get("ok"):
            raise TelegramError(f"{method} failed: {body.get('description')}")
        return body.get("result", {})

    async def get_me(self) -> dict:
        return await self._call("getMe", {})

    async def answer_inline_query(
        self,
        inline_query_id: str,
        results: list[dict],
        *,
        cache_time: int = 300,
        next_offset: str = "",
    ) -> None:
        # results must be JSON-encoded as a string per the Bot API spec.
        await self._call(
            "answerInlineQuery",
            {
                "inline_query_id": inline_query_id,
                "results": json.dumps(results),
                "cache_time": cache_time,
                "next_offset": next_offset,
                "is_personal": False,
            },
        )

    async def set_webhook(self, url: str, secret_token: str) -> None:
        await self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                # We only ever act on inline queries; skip the rest.
                "allowed_updates": ["inline_query"],
                "drop_pending_updates": True,
            },
        )
        log.info("Webhook registered at %s", url)

    async def delete_webhook(self) -> None:
        await self._call("deleteWebhook", {"drop_pending_updates": True})
