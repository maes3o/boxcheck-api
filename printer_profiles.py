"""Custom print-shop profiles for the public /p/<slug> pages (N3, MVP).

Hand-maintained config, same spirit as PROFILES in main.py: the backend stays
stateless (no DB), and a record is added by a human when a pilot print shop is
onboarded — there is no self-serve flow.

Entry shape:
    slug -> {
        "name": str,
        "logo_url": str | None,
        "base_print_method": a key of main.PROFILES,
        "overrides": {bleed_mm?, dpi_threshold?, hairline_mm?, tac_limit_pct?},
        "contact_note": str | None,
    }

The entries below are development placeholders, not real print shops.
"""

OVERRIDABLE_KEYS = ("bleed_mm", "dpi_threshold", "hairline_mm", "tac_limit_pct")

PRINTER_PROFILES: dict[str, dict] = {
    "demo-offset": {
        "name": "Demo Offset Print",
        "logo_url": None,
        "base_print_method": "offset",
        "overrides": {"bleed_mm": 3.0, "tac_limit_pct": 300},
        "contact_note": "Placeholder entry for development.",
    },
    "demo-digital": {
        "name": "Demo Digital Studio",
        "logo_url": None,
        "base_print_method": "digital",
        "overrides": {},
        "contact_note": None,
    },
    "demo-carton": {
        "name": "Demo Carton Factory",
        "logo_url": "https://boxcheck.org/og-image.png",
        "base_print_method": "carton",
        "overrides": {"bleed_mm": 4.0, "hairline_mm": 0.25},
        "contact_note": "Placeholder entry for development.",
    },
}
