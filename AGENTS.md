# AGENTS.md

Guidance for AI agents working in this repo. Read this before changing code.

## What this is

`flipbook` is a self-hosted Telegram **inline bot** that serves GIFs, stickers,
memes, and clips from the Klipy API. It exists because Google shut down the
Tenor API on 2026-06-30, which broke Telegram's built-in `@gif` bot (Tenor-backed)
along with GIF pickers in Discord, WhatsApp, X, and Bluesky.

Inline bots work in every chat — DMs, groups, channels — via `@fpbot query`,
with no install required by the other party. That is the whole point of the
design: one bot that follows the user everywhere.

## Architecture

Request flow, one hop per module:

```
Telegram ──POST /webhook──> app.py
                              │  routing.py   parse "s: cat" -> (STICKER, "cat")
                              │  klipy.py     fetch + normalise into MediaItem
                              │  inline.py    MediaItem -> Telegram result dict
                              └──answerInlineQuery──> Telegram
```

| Module | Responsibility |
|---|---|
| `src/config.py` | Env parsing. Fails fast at startup on missing/invalid vars. |
| `src/media.py` | Domain types (`MediaType`, `Asset`, `MediaItem`). Knows nothing about Klipy or Telegram. |
| `src/klipy.py` | Klipy HTTP client + normalisation into `MediaItem`. |
| `src/inline.py` | `MediaItem` -> Telegram inline result dicts, one builder per media type. |
| `src/routing.py` | Inline query string -> media type + search text; offset -> page. |
| `src/telegram.py` | Minimal Bot API client (`getMe`, `answerInlineQuery`, `setWebhook`). |
| `src/app.py` | aiohttp server, webhook auth, task orchestration. |

`media.py` is deliberately the dependency floor. Keep Klipy-shaped and
Telegram-shaped concerns out of it — that separation is what makes adding a
media type or swapping the provider cheap.

## Non-obvious constraints

These have already caused or would cause bugs. Do not "simplify" them away.

- **Klipy's media shape differs per family, and is undocumented.** Verified
  against the live API:
  - `/gifs/`, `/stickers/`: `file: {hd|md|sm|xs: {gif|webp|jpg|mp4|webm:
    {url, width, height, size}}}` — format is the *parent key*, not a field.
  - `/clips/`: `file: {format: "url"}` flat, with dimensions in a **parallel**
    `file_meta: {format: {width, height, size}}`. `_merge_file_meta` normalises
    this into the nested shape so one walker handles both.
  - Items also carry `blur_preview`, a base64 data URI. The `http` prefix check
    in `_collect_assets` is what keeps it out of the asset list — do not relax it.
  `_collect_assets` walks generically on purpose. Run `scripts/probe.py` against
  a real key before assuming any shape; do not hard-code paths without probe
  output justifying it.
- **`/memes/` does not exist on a test key.** Both `search` and `trending` return
  404 "Route not found" (`memes/list` returns 204 empty). `KlipyUnavailable` is
  raised on any 404 so the user sees "not available" rather than a misleading
  "no results". Re-check after obtaining production access.
- **Never put webm in Telegram's `mpeg4_url`.** It requires H.264 MP4. Klipy
  stickers ship gif/webp/webm/**png but no mp4**, so `_animation_result` asks for
  mp4 only and falls through to gif. An earlier `best("mp4", "webm")` silently
  handed the client a webm.
- **Cap rendition size** (`MAX_ANIMATION_BYTES` / `MAX_STILL_BYTES`). A page of
  30 results is 30 concurrent downloads into the client's media cache. The macOS
  client (`ru.keepcoder.Telegram`) has been observed stack-overflowing with ~1600
  levels of recursion on its `MediaBox-Data` queue under this churn. That is a
  client bug, but keeping payloads small reduces exposure.
- **Bot usernames must end in `bot`** and be 5–32 chars. `@fp` is impossible;
  `@fpbot` is the shortest legal form. Nothing hardcodes the handle — it comes
  from `getMe` — so keep it that way.
- **Prefer `mpeg4_gif` over `gif`** in results. Klipy returns both; the mp4 is
  dramatically smaller and Telegram renders it identically. Telegram itself
  stores "GIFs" as mp4.
- **Telegram stickers cannot be sent from a URL.** `InlineQueryResultCachedSticker`
  needs a `file_id` already uploaded to Telegram, so Klipy stickers ship as
  animations. They look right but are not addable to sticker packs. Fixing this
  properly means uploading and caching `file_id`s — a real feature, not a tweak.
- **Inline queries expire in ~10 seconds.** The webhook returns 200 immediately
  and answers on a detached task, so a slow Klipy call cannot cause Telegram to
  retry the update. Keep `REQUEST_TIMEOUT` well under the expiry.
- **`answerInlineQuery` needs `results` JSON-encoded as a string**, not as a
  nested array. This is a genuine Bot API quirk.
- **Telegram caps inline answers at 50 results** and result IDs at 64 bytes.
  Both are enforced in `config.py` / `inline.py`.
- **Video results require `thumbnail_url` and `title`.** Telegram rejects them
  silently-ish otherwise.

## Conventions

- Immutable data: `@dataclass(frozen=True)` for domain types; build new values
  rather than mutating.
- Small, focused modules. Keep files well under 400 lines.
- Handle errors explicitly at boundaries. A failed Klipy call answers with an
  empty result set rather than leaving a spinner in the user's chat.
- No secrets in code. Everything sensitive comes from env; see `.env.example`.

## Verifying changes

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -v          # pure logic, no network, no keys needed
ruff check src/ tests/ scripts/
KLIPY_API_KEY=... python scripts/probe.py --media gifs --query cat
```

The test suite covers routing, asset selection, Klipy normalisation, and result
building — all without network access. Any change to parsing or result shape
should come with a test. Anything touching live API behaviour needs `probe.py`
output as evidence, since the tests deliberately cannot catch a schema drift.

## Adding a media type

Klipy exposes families as sibling paths (`/gifs/`, `/stickers/`, `/memes/`,
`/clips/`), so this is intentionally cheap:

1. Add the variant to `MediaType` in `media.py` (value = API path segment).
2. Add its prefixes to `PREFIXES` in `routing.py`.
3. Add a builder to `_BUILDERS` in `inline.py` if the existing animation/photo/
   video builders do not fit.
4. Add coverage in `tests/test_parsing.py`.

## Deployment

Railway, webhook mode. `railway.json` sets the start command and `/health` check.
`RAILWAY_PUBLIC_DOMAIN` is injected once a domain is generated, and the app
registers its own webhook on startup — so generate the domain, then redeploy.
