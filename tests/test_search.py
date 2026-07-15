import unittest
from types import SimpleNamespace

from app.search import find_intent, score_product


def product(title: str):
    return SimpleNamespace(product_title=title)


class SearchScoringTests(unittest.TestCase):
    def test_power_bank_intent_rejects_solar_panel(self):
        intent = find_intent("מטען נייד")
        self.assertIsNotNone(intent)
        self.assertGreater(
            score_product(product("20000mAh Fast Power Bank USB C"), intent.api_query, intent),
            0,
        )
        self.assertLess(
            score_product(product("Solar Panel 100W Kit"), intent.api_query, intent),
            0,
        )

    def test_iphone_cable_requires_cable_and_iphone_terms(self):
        intent = find_intent("כבל לאייפון")
        self.assertIsNotNone(intent)
        self.assertGreater(
            score_product(product("Braided Lightning Cable for iPhone"), intent.api_query, intent),
            0,
        )
        self.assertLess(
            score_product(product("Wireless Charger Stand"), intent.api_query, intent),
            0,
        )


if __name__ == "__main__":
    unittest.main()
