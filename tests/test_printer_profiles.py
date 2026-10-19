import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import main
from printer_profiles import OVERRIDABLE_KEYS, PRINTER_PROFILES


class PrinterProfilesConfigTests(unittest.TestCase):
    def test_every_entry_is_valid(self):
        for slug, printer in PRINTER_PROFILES.items():
            self.assertIn(printer["base_print_method"], main.PROFILES, slug)
            self.assertLessEqual(set(printer["overrides"]), set(OVERRIDABLE_KEYS), slug)


class PrinterEndpointTests(unittest.TestCase):
    def setUp(self):
        main.limiter.reset()
        self.client = TestClient(main.app)

    def test_overrides_are_laid_over_base_profile(self):
        shop = {
            "name": "Test Shop", "logo_url": "https://example.com/l.png",
            "base_print_method": "offset",
            "overrides": {"bleed_mm": 1.5, "tac_limit_pct": 290},
            "contact_note": "hi",
        }
        with patch.dict(main.PRINTER_PROFILES, {"test-shop": shop}):
            resp = self.client.get("/printers/test-shop")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["name"], "Test Shop")
        self.assertEqual(body["base_print_method"], "offset")
        self.assertEqual(body["profile"], {**main.PROFILES["offset"], "bleed_mm": 1.5, "tac_limit_pct": 290})

    def test_no_overrides_returns_base_profile(self):
        shop = {"name": "Plain", "logo_url": None, "base_print_method": "digital",
                "overrides": {}, "contact_note": None}
        with patch.dict(main.PRINTER_PROFILES, {"plain": shop}):
            body = self.client.get("/printers/plain").json()
        self.assertEqual(body["profile"], main.PROFILES["digital"])
        self.assertIsNone(body["logo_url"])

    def test_unknown_slug_is_404_with_code(self):
        resp = self.client.get("/printers/nope")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"]["code"], "printer_not_found")

    def test_placeholder_entries_resolve(self):
        for slug in PRINTER_PROFILES:
            self.assertEqual(self.client.get(f"/printers/{slug}").status_code, 200)


if __name__ == "__main__":
    unittest.main()
