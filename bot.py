from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.config import Settings
from app.handlers import (
    category_search,
    error_handler,
    help_command,
    start,
    status_command,
    text_search,
)
from app.search import SearchService


def configure_logging(level: str) -> None:
    logging.basicConfig(
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        level=getattr(logging, level, logging.INFO),
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def build_application(settings: Settings) -> Application:
    search_service = SearchService(settings)
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .concurrent_updates(4)
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    async def handle_category(update, context):
        await category_search(update, context, search_service, settings)

    async def handle_text(update, context):
        await text_search(update, context, search_service, settings)

    application.add_handler(
        CallbackQueryHandler(handle_category, pattern=r"^cat:")
    )
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text)
    )
    application.add_error_handler(error_handler)
    return application


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    logger = logging.getLogger(__name__)
    application = build_application(settings)

    if settings.webhook_enabled:
        path = f"telegram/{settings.webhook_secret}"
        webhook_url = f"{settings.webhook_base_url}/{path}"
        logger.info("Starting webhook mode on port %s", settings.port)
        application.run_webhook(
            listen="0.0.0.0",
            port=settings.port,
            url_path=path,
            webhook_url=webhook_url,
            secret_token=settings.webhook_secret,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
            bootstrap_retries=-1,
        )
    else:
        logger.info("Starting polling mode")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=False,
            bootstrap_retries=-1,
        )


if __name__ == "__main__":
    main()
