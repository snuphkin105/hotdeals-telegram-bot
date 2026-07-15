from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from functools import partial
from typing import Any, Iterable, Sequence

from aliexpress_api import AliexpressApi, models
from deep_translator import GoogleTranslator

from .config import Settings

LOGGER = logging.getLogger(__name__)

STOPWORDS = {
    "a", "an", "and", "for", "from", "in", "of", "on", "the", "to", "with",
    "best", "new", "hot", "sale", "deal", "deals", "original",
}


@dataclass(frozen=True)
class Intent:
    key: str
    triggers: tuple[str, ...]
    api_query: str
    required_groups: tuple[tuple[str, ...], ...] = ()
    excluded_phrases: tuple[str, ...] = ()


INTENTS: tuple[Intent, ...] = (
    Intent(
        key="power_bank",
        triggers=("מטען נייד", "סוללה ניידת", "power bank", "portable charger", "battery pack"),
        api_query="power bank",
        required_groups=(("power bank", "portable charger", "external battery", "mobile power"),),
        excluded_phrases=("solar panel", "solar kit", "power station", "phone holder", "case only"),
    ),
    Intent(
        key="iphone_cable",
        triggers=("כבל לאייפון", "כבל אייפון", "iphone cable", "lightning cable", "iphone charging cable"),
        api_query="iphone lightning charging cable",
        required_groups=(("cable", "cord"), ("iphone", "lightning", "ios")),
        excluded_phrases=("case", "holder", "stand", "wireless charger", "screen protector"),
    ),
    Intent(
        key="bluetooth_earbuds",
        triggers=("אוזניות בלוטוס", "אוזניות אלחוטיות", "bluetooth earbuds", "wireless earbuds", "tws earphones"),
        api_query="bluetooth wireless earbuds",
        required_groups=(("earbuds", "earphones", "headphones", "headset"), ("bluetooth", "wireless", "tws")),
        excluded_phrases=("case only", "ear pads", "replacement cable"),
    ),
    Intent(
        key="gaming_mouse",
        triggers=("עכבר גיימינג", "gaming mouse"),
        api_query="gaming mouse",
        required_groups=(("mouse",), ("gaming", "gamer")),
        excluded_phrases=("mouse pad", "keyboard", "wrist rest"),
    ),
    Intent(
        key="gaming_keyboard",
        triggers=("מקלדת גיימינג", "gaming keyboard"),
        api_query="gaming keyboard",
        required_groups=(("keyboard",), ("gaming", "gamer", "mechanical")),
        excluded_phrases=("keycap only", "mouse pad", "wrist rest"),
    ),
    Intent(
        key="smartwatch",
        triggers=("שעון חכם", "smart watch", "smartwatch"),
        api_query="smart watch",
        required_groups=(("smartwatch", "smart watch"),),
        excluded_phrases=("strap only", "band only", "case only", "screen protector"),
    ),
    Intent(
        key="security_camera",
        triggers=("מצלמת אבטחה", "security camera", "surveillance camera", "wifi camera"),
        api_query="wifi security camera",
        required_groups=(("camera",), ("security", "surveillance", "cctv", "wifi")),
        excluded_phrases=("dummy camera", "mount only", "cable only"),
    ),
    Intent(
        key="car_charger",
        triggers=("מטען לרכב", "car charger", "vehicle charger"),
        api_query="usb car charger",
        required_groups=(("charger",), ("car", "vehicle", "cigarette lighter")),
        excluded_phrases=("phone holder", "mount only", "cable only"),
    ),
)

CATEGORY_QUERIES = {
    "power_bank": "power bank 20000mah",
    "phone_accessories": "fast phone charging accessories",
    "gaming": "gaming accessories",
    "car": "car accessories",
    "home": "smart home gadgets",
    "earbuds": "bluetooth wireless earbuds",
}


def normalize(text: str) -> str:
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9\u0590-\u05ff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def has_hebrew(text: str) -> bool:
    return any("\u0590" <= ch <= "\u05ff" for ch in text)


def find_intent(query: str) -> Intent | None:
    normalized = normalize(query)
    for intent in INTENTS:
        if any(normalize(trigger) in normalized for trigger in intent.triggers):
            return intent
    return None


def _tokens(text: str) -> list[str]:
    return [token for token in normalize(text).split() if len(token) > 1 and token not in STOPWORDS]


def _attr(product: Any, names: Sequence[str], default: str = "") -> str:
    for name in names:
        value = getattr(product, name, None)
        if value not in (None, ""):
            return str(value)
    return default


def product_id(product: Any) -> str:
    return _attr(product, ("product_id", "item_id", "id"), _product_url(product))


def _product_url(product: Any) -> str:
    return _attr(product, ("product_detail_url", "product_url", "target_url"))


def _promotion_url(product: Any) -> str:
    return _attr(product, ("promotion_link", "affiliate_url"))


def score_product(product: Any, query: str, intent: Intent | None) -> float:
    title = normalize(_attr(product, ("product_title", "title")))
    if not title:
        return -1000.0

    if intent:
        if any(normalize(phrase) in title for phrase in intent.excluded_phrases):
            return -1000.0
        for group in intent.required_groups:
            if not any(normalize(term) in title for term in group):
                return -1000.0

    query_tokens = _tokens(query)
    title_tokens = set(_tokens(title))
    if not query_tokens:
        return 0.0

    matches = sum(1 for token in query_tokens if token in title_tokens or token in title)
    coverage = matches / len(query_tokens)

    # Generic queries must still have meaningful title overlap.
    if not intent and coverage < 0.5:
        return -1000.0

    score = coverage * 100
    normalized_query = normalize(query)
    if normalized_query and normalized_query in title:
        score += 35
    if intent and normalize(intent.api_query) in title:
        score += 25

    orders = _attr(product, ("lastest_volume", "volume", "orders", "sales"))
    try:
        score += min(float(re.sub(r"[^0-9.]", "", orders) or 0), 10000) / 1000
    except ValueError:
        pass
    return score


@dataclass(frozen=True)
class ProductResult:
    title: str
    price: str
    currency: str
    image_url: str
    affiliate_url: str
    score: float


class SearchService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._cache: dict[str, tuple[float, list[ProductResult]]] = {}

    def _api(self) -> AliexpressApi:
        currency = getattr(models.Currency, self.settings.default_currency, models.Currency.USD)
        language = getattr(models.Language, self.settings.default_language, models.Language.EN)
        return AliexpressApi(
            self.settings.aliexpress_app_key,
            self.settings.aliexpress_app_secret,
            language,
            currency,
            self.settings.aliexpress_tracking_id,
        )

    async def prepare_query(self, original_query: str) -> tuple[str, Intent | None]:
        original_query = original_query.strip()[:120]
        intent = find_intent(original_query)
        if intent:
            return intent.api_query, intent
        if has_hebrew(original_query):
            try:
                translated = await asyncio.wait_for(
                    asyncio.to_thread(
                        GoogleTranslator(source="auto", target="en").translate,
                        original_query,
                    ),
                    timeout=8,
                )
                return str(translated or original_query), None
            except Exception as exc:
                LOGGER.warning("Translation failed: %s", exc)
        return original_query, None

    async def search(self, original_query: str) -> list[ProductResult]:
        cache_key = normalize(original_query)
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < self.settings.cache_ttl_seconds:
            return cached[1]

        api_query, intent = await self.prepare_query(original_query)
        api = self._api()
        queries = [api_query]
        if intent and normalize(original_query) != normalize(api_query):
            queries.append(original_query)

        candidates: list[Any] = []
        seen: set[str] = set()
        for query in queries[:2]:
            try:
                call = partial(
                    api.get_products,
                    keywords=query,
                    page_no=1,
                    page_size=self.settings.candidate_count,
                )
                response = await asyncio.wait_for(asyncio.to_thread(call), timeout=20)
            except Exception:
                LOGGER.exception("AliExpress product search failed for query=%r", query)
                raise
            for product in getattr(response, "products", []) or []:
                key = product_id(product)
                if key and key not in seen:
                    seen.add(key)
                    candidates.append(product)

        ranked = sorted(
            ((score_product(product, api_query, intent), product) for product in candidates),
            key=lambda item: item[0],
            reverse=True,
        )

        results: list[ProductResult] = []
        for score, product in ranked:
            if score < 0:
                continue
            title = _attr(product, ("product_title", "title"))
            price = _attr(product, ("target_sale_price", "sale_price", "app_sale_price"))
            currency = _attr(
                product,
                ("target_sale_price_currency", "sale_price_currency", "currency"),
                self.settings.default_currency,
            )
            image_url = _attr(product, ("product_main_image_url", "image_url"))
            raw_url = _product_url(product)
            affiliate_url = _promotion_url(product)

            if not affiliate_url and raw_url:
                try:
                    links = await asyncio.wait_for(
                        asyncio.to_thread(api.get_affiliate_links, raw_url),
                        timeout=15,
                    )
                    if links:
                        affiliate_url = _attr(links[0], ("promotion_link", "affiliate_url", "url"))
                except Exception:
                    LOGGER.exception("Affiliate-link conversion failed")
                    continue

            if not all((title, price, image_url, affiliate_url)):
                continue

            results.append(
                ProductResult(
                    title=title,
                    price=price,
                    currency=currency,
                    image_url=image_url,
                    affiliate_url=affiliate_url,
                    score=score,
                )
            )
            if len(results) >= self.settings.products_count:
                break

        self._cache[cache_key] = (time.monotonic(), results)
        if len(self._cache) > 200:
            oldest = min(self._cache, key=lambda key: self._cache[key][0])
            self._cache.pop(oldest, None)
        return results
