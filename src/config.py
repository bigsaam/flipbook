"""Environment-backed configuration, validated at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass

# Telegram caps inline answers at 50 results.
MAX_RESULTS = 50
# Klipy rejects per_page outside this range.
MIN_PER_PAGE = 8


class ConfigError(RuntimeError):
    """Raised when the process is not configured well enough to start."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"Missing required environment variable: {name}. "
            f"See .env.example for what each variable does."
        )
    return value


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Config:
    telegram_token: str
    klipy_api_key: str
    webhook_secret: str
    public_domain: str
    port: int
    rating: str
    locale: str
    per_page: int
    cache_time: int

    @classmethod
    def from_env(cls) -> "Config":
        # Deliberately small. Telegram fires a fresh inline query on every
        # keystroke, and each result is a media download into the client's
        # cache, so a large page multiplies client-side work per character
        # typed. Telegram requests page 2 via next_offset when the user
        # scrolls, so a small page costs nothing in reachable results.
        per_page = _int("FLIPBOOK_PER_PAGE", 10)
        if not MIN_PER_PAGE <= per_page <= MAX_RESULTS:
            raise ConfigError(
                f"FLIPBOOK_PER_PAGE must be between {MIN_PER_PAGE} and {MAX_RESULTS}"
            )

        return cls(
            telegram_token=_required("TELEGRAM_BOT_TOKEN"),
            klipy_api_key=_required("KLIPY_API_KEY"),
            webhook_secret=_required("TELEGRAM_WEBHOOK_SECRET"),
            # Railway injects RAILWAY_PUBLIC_DOMAIN once a domain is generated.
            public_domain=os.environ.get(
                "PUBLIC_DOMAIN", os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
            ).strip(),
            port=_int("PORT", 8080),
            rating=os.environ.get("KLIPY_RATING", "pg-13").strip(),
            locale=os.environ.get("KLIPY_LOCALE", "en_US").strip(),
            per_page=per_page,
            cache_time=_int("FLIPBOOK_CACHE_TIME", 300),
        )

    @property
    def webhook_url(self) -> str:
        if not self.public_domain:
            return ""
        return f"https://{self.public_domain}/webhook"
