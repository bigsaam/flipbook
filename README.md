# flipbook

A self-hosted Telegram inline bot for GIFs, stickers, memes, and clips — usable
in **every** chat, group, and channel, with nothing for the other person to install.

```
@fpbot dancing cat        GIFs (default)
@fpbot s: happy           stickers
@fpbot m: distracted      memes
@fpbot c: star wars       clips
```

Leave the query blank for trending.

## Why

Google shut down the **Tenor API on 30 June 2026** (announced 13 January, new
signups closed the same day). Telegram's built-in `@gif` bot was Tenor-backed,
so it degraded along with GIF pickers in Discord, WhatsApp, X, and Bluesky.

flipbook restores that experience using [Klipy](https://klipy.com) — built by
ex-Tenor engineers as a drop-in replacement, and now the provider behind
WhatsApp, Discord, Bluesky, Canva, and Figma. Its API is deliberately
Tenor-shaped, and the free tier is generous enough that personal use never
approaches the limits.

## Setup

### 1. Create the bot

In Telegram, talk to [@BotFather](https://t.me/BotFather):

```
/newbot            -> pick a name and username, save the token
/setinline         -> pick the placeholder text, e.g. "search gifs…"
/setinlinefeedback -> Disabled (nothing here needs it)
```

Usernames must end in `bot` and be 5–32 characters, so `@fp` is not possible —
`@fpbot` is the shortest legal form. The display name has no such restriction.

### 2. Get a Klipy key

Sign up at [partner.klipy.com](https://partner.klipy.com) → **API Keys** →
**Add Platform**. Test keys allow 100 calls/hour, which is ample for personal
use; request production access in the panel for unlimited.

### 3. Configure

```bash
cp .env.example .env
openssl rand -hex 32          # use for TELEGRAM_WEBHOOK_SECRET
```

Fill in `TELEGRAM_BOT_TOKEN`, `KLIPY_API_KEY`, and `TELEGRAM_WEBHOOK_SECRET`.

### 4. Deploy to Railway

```bash
railway link                  # select the project
railway up
railway domain                # generate the public HTTPS domain
```

Set the three secrets in the Railway dashboard (or `railway variables --set`).
The app registers its own Telegram webhook on startup using
`RAILWAY_PUBLIC_DOMAIN`, so **generate the domain first, then redeploy** — on the
first boot without a domain it will log a warning and skip webhook registration.

Verify with `curl https://<your-domain>/health`.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

python -m pytest tests/ -v                    # no network or keys required
KLIPY_API_KEY=... python scripts/probe.py     # inspect real Klipy responses
```

Webhooks need a public HTTPS URL, so for local end-to-end testing expose the
port with a tunnel and set `PUBLIC_DOMAIN` to the tunnel hostname:

```bash
cloudflared tunnel --url http://localhost:8080
PUBLIC_DOMAIN=<tunnel-host> python -m src.app
```

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | — | From BotFather |
| `KLIPY_API_KEY` | yes | — | From partner.klipy.com |
| `TELEGRAM_WEBHOOK_SECRET` | yes | — | Rejects non-Telegram webhook calls |
| `PUBLIC_DOMAIN` | no | `RAILWAY_PUBLIC_DOMAIN` | Hostname, no scheme |
| `KLIPY_RATING` | no | `pg-13` | `g`, `pg`, `pg-13`, `r` |
| `KLIPY_LOCALE` | no | `en_US` | Localises trending |
| `FLIPBOOK_PER_PAGE` | no | `30` | Results per page (8–50) |
| `FLIPBOOK_CACHE_TIME` | no | `300` | Telegram-side cache seconds |
| `PORT` | no | `8080` | Set by Railway automatically |

## Known limitations

- **Stickers send as animations, not native Telegram stickers.** Telegram only
  accepts stickers by `file_id` (already uploaded), never by URL. They render
  correctly in chat but cannot be saved to a sticker pack.
- **You type `@fpbot query` rather than tapping the GIF button.** Telegram does
  not let third-party bots replace the native GIF picker. This is the unavoidable
  friction of the inline-bot approach.
- **Some groups disable inline bots** in their permission settings.
- Every query you type goes to your own server and then to Klipy.

## Licence

MIT
