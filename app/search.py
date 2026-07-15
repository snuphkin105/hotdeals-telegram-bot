from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from functools import partial
from typing import Any, Sequence

from aliexpress_api import AliexpressApi, models
from deep_translator import GoogleTranslator

from .config import Settings

LOGGER = logging.getLogger(__name__)

STOPWORDS = {
    "a", "an", "and", "for", "from", "in", "of", "on", "the", "to", "with",
    "best", "new", "hot", "sale", "deal", "deals", "original", "product", "item",
}


@dataclass(frozen=True)
class Intent:
    key: str
    triggers: tuple[str, ...]
    api_queries: tuple[str, ...]
    required_groups: tuple[tuple[str, ...], ...] = ()
    excluded_phrases: tuple[str, ...] = ()


INTENTS: tuple[Intent, ...] = (
    Intent(
        key="power_bank",
        triggers=("מטען נייד", "סוללה ניידת", "power bank", "powerbank", "portable charger", "battery pack"),
        api_queries=("power bank 20000mah", "portable charger", "external battery power bank"),
        required_groups=(("power bank", "powerbank", "portable charger", "external battery", "battery pack", "mobile power"),),
        excluded_phrases=("solar panel", "solar kit", "power station", "phone holder", "case only"),
    ),
    Intent(
        key="iphone_cable",
        triggers=("כבל לאייפון", "כבל אייפון", "iphone cable", "lightning cable", "iphone charging cable"),
        api_queries=("iphone lightning charging cable", "lightning usb cable iphone", "iphone data cable"),
        required_groups=(("cable", "cord", "wire"), ("iphone", "lightning", "ios")),
        excluded_phrases=("case", "holder", "stand", "wireless charger", "screen protector"),
    ),
    Intent(
        key="usb_cable",
        triggers=("usb cable", "כבל usb", "כבל יו אס בי", "charging cable", "data cable"),
        api_queries=("usb charging cable", "usb data cable", "fast charging cable"),
        required_groups=(("cable", "cord", "wire"), ("usb", "type c", "type-c", "micro usb", "lightning")),
        excluded_phrases=("wireless charger", "adapter only", "case only", "holder"),
    ),
    Intent(
        key="bluetooth_earbuds",
        triggers=("אוזניות בלוטוס", "אוזניות אלחוטיות", "bluetooth earbuds", "wireless earbuds", "tws earphones"),
        api_queries=("bluetooth wireless earbuds", "tws earphones", "wireless bluetooth headphones"),
        required_groups=(("earbuds", "earphones", "headphones", "headset"), ("bluetooth", "wireless", "tws")),
        excluded_phrases=("case only", "ear pads", "replacement cable"),
    ),
    Intent(
        key="gaming_mouse",
        triggers=("עכבר גיימינג", "gaming mouse"),
        api_queries=("gaming mouse", "rgb gaming mouse"),
        required_groups=(("mouse",), ("gaming", "gamer", "rgb")),
        excluded_phrases=("mouse pad", "keyboard", "wrist rest"),
    ),
    Intent(
        key="gaming_keyboard",
        triggers=("מקלדת גיימינג", "gaming keyboard"),
        api_queries=("gaming keyboard", "mechanical gaming keyboard"),
        required_groups=(("keyboard",), ("gaming", "gamer", "mechanical")),
        excluded_phrases=("keycap only", "mouse pad", "wrist rest"),
    ),
    Intent(
        key="smartwatch",
        triggers=("שעון חכם", "smart watch", "smartwatch"),
        api_queries=("smart watch", "smartwatch fitness tracker"),
        required_groups=(("smartwatch", "smart watch", "fitness watch"),),
        excluded_phrases=("strap only", "band only", "case only", "screen protector"),
    ),
    Intent(
        key="security_camera",
        triggers=("מצלמת אבטחה", "security camera", "surveillance camera", "wifi camera"),
        api_queries=("wifi security camera", "home surveillance camera", "cctv wifi camera"),
        required_groups=(("camera",), ("security", "surveillance", "cctv", "wifi")),
        excluded_phrases=("dummy camera", "mount only", "cable only"),
    ),
    Intent(
        key="car_charger",
        triggers=("מטען לרכב", "car charger", "vehicle charger"),
        api_queries=("usb car charger", "fast car phone charger"),
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
    text = str(text or "").lower().replace("&", " and ")
    text = re.sub(r"(?<=\d)[,.](?=\d)", "", text)
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
    return _attr(
        product,
        (
            "product_detail_url", "product_url", "target_url", "product_detail_url_original",
            "shop_url", "url",
        ),
    )


def _promotion_url(product: Any) -> str:
    return _attr(
        product,
        (
            "promotion_link", "affiliate_url", "promotion_url", "tracking_url",
            "product_affiliate_url", "click_url",
        ),
    )


def _contains_term(title: str, term: str) -> bool:
    normalized_term = normalize(term)
    return bool(normalized_term) and normalized_term in title


def score_product(product: Any, query: str, intent: Intent | None) -> float:
    title = normalize(_attr(product, ("product_title", "title", "subject")))
    if not title:
        return -1000.0

    if intent:
        if any(_contains_term(title, phrase) for phrase in intent.excluded_phrases):
            return -1000.0
        missing_groups = sum(
            1 for group in intent.required_groups
            if not any(_contains_term(title, term) for term in group)
        )
        if missing_groups == len(intent.required_groups):
            return -1000.0
    else:
        missing_groups = 0

    query_tokens = _tokens(query)
    title_tokens = set(_tokens(title))
    if not query_tokens:
        return 1.0

    exact_matches = sum(1 for token in query_tokens if token in title_tokens)
    partial_matches = sum(1 for token in query_tokens if token not in title_tokens and token in title)
    coverage = (exact_matches + partial_matches * 0.65) / len(query_tokens)

    if not intent and coverage < 0.25:
        return -1000.0

    score = coverage * 100
    normalized_query = normalize(query)
    if normalized_query and normalized_query in title:
        score += 30
    if intent:
        if any(normalize(api_query) in title for api_query in intent.api_queries):
            score += 20
        score -= missing_groups * 18

    orders = _attr(product, ("lastest_volume", "volume", "orders", "sales", "evaluate_rate"))
    try:
        score += min(float(re.sub(r"[^0-9.]", "", orders) or 0), 10000) / 1200
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
    is_affiliate: bool = True


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

    async def prepare_queries(self, original_query: str) -> tuple[list[str], Intent | None]:
        original_query = original_query.strip()[:120]
        intent = find_intent(original_query)
        if intent:
            return list(intent.api_queries), intent

        translated = original_query
        if has_hebrew(original_query):
            try:
                translated = str(
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            GoogleTranslator(source="auto", target="en").translate,
                            original_query,
                        ),
                        timeout=8,
                    )
                    or original_query
                )
            except Exception as exc:
                LOGGER.warning("Translation failed: %s", exc)

        queries = [translated]
        normalized_original = normalize(original_query)
        if normalize(translated) != normalized_original:
            queries.append(original_query)
        tokens = _tokens(translated)
        if len(tokens) > 2:
            queries.append(" ".join(tokens[:3]))
        return _dedupe_strings(queries), None

    async def _search_candidates(self, api: AliexpressApi, queries: list[str]) -> list[Any]:
        candidates: list[Any] = []
        seen: set[str] = set()
        last_error: Exception | None = None

        for query in queries[:3]:
            try:
                call = partial(
                    api.get_products,
                    keywords=query,
                    page_no=1,
                    page_size=self.settings.candidate_count,
                )
                response = await asyncio.wait_for(asyncio.to_thread(call), timeout=25)
            except Exception as exc:
                last_error = exc
                LOGGER.exception("AliExpress product search failed for query=%r", query)
                continue

            products = getattr(response, "products", None) or []
            LOGGER.info("AliExpress query=%r returned %d products", query, len(products))
            for product in products:
                key = product_id(product)
                if key and key not in seen:
                    seen.add(key)
                    candidates.append(product)

        if not candidates and last_error:
            raise last_error
        return candidates

    async def _convert_affiliate_url(self, api: AliexpressApi, raw_url: str) -> str:
        if not raw_url:
            return ""

        attempts: tuple[Any, ...] = (raw_url, [raw_url])
        for value in attempts:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(api.get_affiliate_links, value),
                    timeout=18,
                )
                url = _extract_url_from_response(response)
                if url:
                    return url
            except Exception as exc:
                LOGGER.warning(
                    "Affiliate-link conversion failed for argument type=%s: %s",
                    type(value).__name__,
                    exc,
                )
        return ""

    async def search(self, original_query: str) -> list[ProductResult]:
        cache_key = normalize(original_query)
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < self.settings.cache_ttl_seconds:
            return cached[1]

        queries, intent = await self.prepare_queries(original_query)
        api = self._api()
        candidates = await self._search_candidates(api, queries)
        scoring_query = queries[0] if queries else original_query

        ranked = sorted(
            ((score_product(product, scoring_query, intent), product) for product in candidates),
            key=lambda item: item[0],
            reverse=True,
        )

        results: list[ProductResult] = []
        for score, product in ranked:
            if score < 0:
                continue

            title = _attr(product, ("product_title", "title", "subject"))
            price = _attr(
                product,
                ("target_sale_price", "sale_price", "app_sale_price", "target_original_price", "original_price"),
            )
            currency = _attr(
                product,
                ("target_sale_price_currency", "sale_price_currency", "currency"),
                self.settings.default_currency,
            )
            image_url = _attr(
                product,
                ("product_main_image_url", "image_url", "product_small_image_urls", "main_image_url"),
            )
            raw_url = _product_url(product)
            affiliate_url = _promotion_url(product)
            is_affiliate = bool(affiliate_url)

            if not affiliate_url and raw_url:
                affiliate_url = await self._convert_affiliate_url(api, raw_url)
                is_affiliate = bool(affiliate_url)

            if not affiliate_url and raw_url and self.settings.allow_direct_link_fallback:
                affiliate_url = raw_url
                is_affiliate = False

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
                    is_affiliate=is_affiliate,
                )
            )
            if len(results) >= self.settings.products_count:
                break

        LOGGER.info(
            "Search query=%r candidates=%d ranked_valid=%d returned=%d affiliate=%d direct=%d",
            original_query,
            len(candidates),
            sum(1 for score, _ in ranked if score >= 0),
            len(results),
            sum(1 for item in results if item.is_affiliate),
            sum(1 for item in results if not item.is_affiliate),
        )

        self._cache[cache_key] = (time.monotonic(), results)
        if len(self._cache) > 200:
            oldest = min(self._cache, key=lambda key: self._cache[key][0])
            self._cache.pop(oldest, None)
        return results


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = " ".join(str(value or "").split())
        key = normalize(cleaned)
        if cleaned and key not in seen:
            seen.add(key)
            output.append(cleaned)
    return output


def _extract_url_from_response(response: Any) -> str:
    if response in (None, ""):
        return ""
    if isinstance(response, str):
        return response if response.startswith(("http://", "https://")) else ""
    if isinstance(response, dict):
        for key in ("promotion_link", "affiliate_url", "promotion_url", "tracking_url", "url"):
            value = response.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return value
        for value in response.values():
            url = _extract_url_from_response(value)
            if url:
                return url
        return ""
    if isinstance(response, (list, tuple, set)):
        for item in response:
            url = _extract_url_from_response(item)
            if url:
                return url
        return ""

    for name in (
        "promotion_link", "affiliate_url", "promotion_url", "tracking_url", "url",
        "links", "result", "results", "data",
    ):
        value = getattr(response, name, None)
        if value not in (None, ""):
            url = _extract_url_from_response(value)
            if url:
                return url
    return ""
