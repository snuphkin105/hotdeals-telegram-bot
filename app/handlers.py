from __future__ import annotations

import html
import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .config import Settings
from .search import CATEGORY_QUERIES, SearchService
from .texts import (
    AFFILIATE_NOTE,
    COOLDOWN,
    HELP,
    NO_RESULTS,
    SEARCHING,
    SERVICE_UNAVAILABLE,
    WELCOME,
)

LOGGER = logging.getLogger(__name__)


def start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔋 Power banks", callback_data="cat:power_bank"),
                InlineKeyboardButton("🎧 Earbuds", callback_data="cat:earbuds"),
            ],
            [
                InlineKeyboardButton("🎮 Gaming", callback_data="cat:gaming"),
                InlineKeyboardButton("🚗 Car", callback_data="cat:car"),
            ],
            [
                InlineKeyboardButton("🏠 Home", callback_data="cat:home"),
                InlineKeyboardButton("📱 Phone", callback_data="cat:phone_accessories"),
            ],
            [
                InlineKeyboardButton(
                    "📸 CREDIT: @TALCOHEN105",
                    url="https://instagram.com/talcohen105",
                )
            ],
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            WELCOME,
            parse_mode=ParseMode.HTML,
            reply_markup=start_keyboard(),
            disable_web_page_preview=True,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(
            "✅ Telegram bot is online.\n"
            "Affiliate product availability depends on the AliExpress API/account status."
        )


def _on_cooldown(context: ContextTypes.DEFAULT_TYPE, settings: Settings) -> bool:
    if not settings.request_cooldown_seconds:
        return False
    now = time.monotonic()
    previous = float(context.user_data.get("last_search", 0.0))
    if now - previous < settings.request_cooldown_seconds:
        return True
    context.user_data["last_search"] = now
    return False


async def run_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    query: str,
    search_service: SearchService,
    settings: Settings,
) -> None:
    message = update.effective_message
    if not message:
        return
    query = " ".join(query.split())[:120]
    if len(query) < 2:
        await message.reply_text("Please enter a more specific product name.")
        return
    if _on_cooldown(context, settings):
        await message.reply_text(COOLDOWN)
        return

    waiting = await message.reply_text(SEARCHING)
    try:
        products = await search_service.search(query)
    except Exception:
        LOGGER.exception("Search request failed")
        await waiting.edit_text(SERVICE_UNAVAILABLE)
        return

    if not products:
        await waiting.edit_text(NO_RESULTS, parse_mode=ParseMode.HTML)
        return

    await waiting.edit_text(
        f"🔥 <b>Top {len(products)} relevant finds for:</b> {html.escape(query)}",
        parse_mode=ParseMode.HTML,
    )

    for index, product in enumerate(products, start=1):
        title = html.escape(product.title)
        price = html.escape(product.price)
        currency = html.escape(product.currency)
        caption = (
            f"<b>{index}. {title}</b>\n"
            f"💰 <b>{price} {currency}</b>\n"
            f"{AFFILIATE_NOTE}"
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🛒 Open product", url=product.affiliate_url)]]
        )
        try:
            await message.reply_photo(
                photo=product.image_url,
                caption=caption[:1024],
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        except Exception:
            LOGGER.warning("Photo send failed; sending text fallback", exc_info=True)
            await message.reply_text(
                caption,
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )


async def text_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    search_service: SearchService,
    settings: Settings,
) -> None:
    query = update.effective_message.text if update.effective_message else ""
    await run_search(update, context, query or "", search_service, settings)


async def category_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    search_service: SearchService,
    settings: Settings,
) -> None:
    callback = update.callback_query
    if not callback:
        return
    await callback.answer()
    key = callback.data.split(":", 1)[1] if ":" in callback.data else ""
    query = CATEGORY_QUERIES.get(key)
    if not query:
        await callback.answer("Unknown category", show_alert=True)
        return
    await run_search(update, context, query, search_service, settings)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if error is None:
        LOGGER.error("Unhandled Telegram update error")
    else:
        LOGGER.error(
            "Unhandled Telegram update error",
            exc_info=(type(error), error, error.__traceback__),
        )
