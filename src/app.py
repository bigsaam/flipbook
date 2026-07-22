"""aiohttp webhook server wiring Telegram inline queries to Klipy."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from aiohttp import web

from .config import Config, ConfigError
from .inline import (
    MAX_ANIMATION_BYTES,
    build_results,
    no_results_article,
    thumbnail,
    unavailable_article,
)
from .klipy import KlipyClient, KlipyError, KlipyUnavailable
from .routing import parse, parse_page
from .telegram import TelegramClient, TelegramError

log = logging.getLogger(__name__)

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _result_bytes(item, media_type) -> int:
    """Bytes this item will make the client download, for volume logging."""
    chosen = item.best("mp4", max_bytes=MAX_ANIMATION_BYTES) or item.best(
        "gif", max_bytes=MAX_ANIMATION_BYTES
    )
    thumb = thumbnail(item)
    return (chosen.size if chosen else 0) + (thumb.size if thumb else 0)


async def _handle_inline_query(app: web.Application, query: dict) -> None:
    """Resolve one inline query and answer it. Runs detached from the webhook."""
    config: Config = app["config"]
    klipy: KlipyClient = app["klipy"]
    telegram: TelegramClient = app["telegram"]

    query_id = query.get("id", "")
    parsed = parse(query.get("query", ""))
    page = parse_page(query.get("offset", ""))

    unavailable = False
    try:
        items, has_next = await klipy.fetch(
            parsed.media_type,
            parsed.text,
            page=page,
            per_page=config.per_page,
        )
    except KlipyUnavailable:
        log.warning("No Klipy route for %s", parsed.media_type.value)
        items, has_next, unavailable = [], False, True
    except (KlipyError, aiohttp.ClientError, asyncio.TimeoutError):
        log.exception("Klipy lookup failed for %r", parsed.text)
        # Answer with nothing rather than let Telegram show a spinner until timeout.
        items, has_next = [], False

    results = build_results(items, parsed.media_type)

    # Only explain on the first page; a blank page 2 is just the end of results.
    if not results and page == 1:
        if unavailable:
            results = [unavailable_article(parsed.media_type)]
        elif parsed.text:
            results = [no_results_article(parsed.text, parsed.media_type)]
        has_next = False

    # Log shape, not content: enough to correlate a client-side crash with what
    # was served, without recording what anyone searched for.
    log.info(
        "inline %s page=%d results=%d bytes=%d",
        parsed.media_type.value,
        page,
        len(results),
        sum(_result_bytes(item, parsed.media_type) for item in items),
    )

    try:
        await telegram.answer_inline_query(
            query_id,
            results,
            cache_time=config.cache_time,
            next_offset=str(page + 1) if has_next and results else "",
        )
    except (TelegramError, aiohttp.ClientError, asyncio.TimeoutError):
        # Inline queries expire after ~10s; a failure here is not recoverable.
        log.exception("Failed to answer inline query %s", query_id)


async def webhook(request: web.Request) -> web.Response:
    app = request.app
    if request.headers.get(SECRET_HEADER) != app["config"].webhook_secret:
        log.warning("Rejected webhook call with bad secret token")
        return web.Response(status=403, text="forbidden")

    try:
        update = await request.json()
    except ValueError:
        return web.Response(status=400, text="bad json")

    inline_query = update.get("inline_query")
    if inline_query:
        # Answer out of band so Telegram gets its 200 immediately and does not
        # retry the update while we are still talking to Klipy.
        task = asyncio.create_task(_handle_inline_query(app, inline_query))
        app["tasks"].add(task)
        task.add_done_callback(app["tasks"].discard)

    return web.Response(text="ok")


async def health(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "bot": request.app.get("username", "")})


async def _on_startup(app: web.Application) -> None:
    config: Config = app["config"]
    session = aiohttp.ClientSession()
    app["session"] = session
    app["telegram"] = TelegramClient(session, config.telegram_token)
    app["klipy"] = KlipyClient(
        session,
        config.klipy_api_key,
        rating=config.rating,
        locale=config.locale,
    )
    app["tasks"] = set()

    me = await app["telegram"].get_me()
    app["username"] = me.get("username", "")
    log.info("Authenticated as @%s", app["username"])

    if config.webhook_url:
        await app["telegram"].set_webhook(config.webhook_url, config.webhook_secret)
    else:
        log.warning(
            "No PUBLIC_DOMAIN/RAILWAY_PUBLIC_DOMAIN set — webhook not registered. "
            "Generate a domain, then redeploy."
        )


async def _on_cleanup(app: web.Application) -> None:
    for task in list(app.get("tasks", ())):
        task.cancel()
    session = app.get("session")
    if session:
        await session.close()


def create_app(config: Config) -> web.Application:
    app = web.Application()
    app["config"] = config
    app.router.add_post("/webhook", webhook)
    app.router.add_get("/health", health)
    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        config = Config.from_env()
    except ConfigError as exc:
        raise SystemExit(f"Configuration error: {exc}") from exc

    web.run_app(create_app(config), port=config.port, print=None)


if __name__ == "__main__":
    main()
