from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a whole number") from exc
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    aliexpress_app_key: str
    aliexpress_app_secret: str
    aliexpress_tracking_id: str
    default_currency: str
    default_language: str
    products_count: int
    candidate_count: int
    cache_ttl_seconds: int
    request_cooldown_seconds: int
    port: int
    webhook_base_url: str
    webhook_secret: str
    force_polling: bool
    log_level: str

    @property
    def webhook_enabled(self) -> bool:
        return bool(self.webhook_base_url) and not self.force_polling

    @classmethod
    def from_env(cls) -> "Settings":
        required = {
            "TELEGRAM_BOT_TOKEN": os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            "ALIEXPRESS_APP_KEY": os.getenv("ALIEXPRESS_APP_KEY", "").strip(),
            "ALIEXPRESS_APP_SECRET": os.getenv("ALIEXPRESS_APP_SECRET", "").strip(),
            "ALIEXPRESS_TRACKING_ID": os.getenv("ALIEXPRESS_TRACKING_ID", "").strip(),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

        token = required["TELEGRAM_BOT_TOKEN"]
        external_url = (
            os.getenv("WEBHOOK_BASE_URL", "").strip()
            or os.getenv("RENDER_EXTERNAL_URL", "").strip()
        ).rstrip("/")

        secret = os.getenv("WEBHOOK_SECRET", "").strip()
        if not secret:
            secret = hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
        if not all(ch.isalnum() or ch in "_-" for ch in secret):
            raise RuntimeError("WEBHOOK_SECRET may contain only letters, numbers, '_' and '-'")

        return cls(
            telegram_bot_token=token,
            aliexpress_app_key=required["ALIEXPRESS_APP_KEY"],
            aliexpress_app_secret=required["ALIEXPRESS_APP_SECRET"],
            aliexpress_tracking_id=required["ALIEXPRESS_TRACKING_ID"],
            default_currency=os.getenv("DEFAULT_CURRENCY", "USD").strip().upper(),
            default_language=os.getenv("DEFAULT_LANGUAGE", "EN").strip().upper(),
            products_count=_env_int("PRODUCTS_COUNT", 3, 1, 5),
            candidate_count=_env_int("CANDIDATE_COUNT", 50, 10, 50),
            cache_ttl_seconds=_env_int("CACHE_TTL_SECONDS", 600, 60, 3600),
            request_cooldown_seconds=_env_int("REQUEST_COOLDOWN_SECONDS", 3, 0, 30),
            port=_env_int("PORT", 10000, 1, 65535),
            webhook_base_url=external_url,
            webhook_secret=secret,
            force_polling=_env_bool("FORCE_POLLING", False),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
        )
