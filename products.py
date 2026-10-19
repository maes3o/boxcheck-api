"""
BoxCheck — product catalog (Tier 1, per Perplexity market analysis, 09.09.2026).

Standalone module: no dependency on the rest of the app. Import PRODUCTS / TIERS
from here and wire into main.py (see README_INTEGRATION.md for the exact hook
points). Tier 2/3 entries are included as catalog data for future work but are
NOT yet wired into any check — only Tier 1 is "active" this round.

All dimensions are stored in millimetres. Conversion helpers for points<->mm
live in geometry.py.
"""

from __future__ import annotations
from typing import TypedDict, Literal, Optional


class ProductFormat(TypedDict):
    id: str
    label_ua: str
    label_en: str
    width_mm: float
    height_mm: float
    region: Literal["EU", "US", "INTL"]


class Product(TypedDict):
    id: str
    tier: int
    name_ua: str
    name_en: str
    formats: list[ProductFormat]
    tolerance_mm: float
    # bleed/safe_zone can differ by region (EU vs US spec gave different bleed
    # numbers for some products); a flat float applies to all regions.
    bleed_mm: dict[str, float] | float
    safe_zone_mm: float
    fold_types: Optional[list[str]]  # only for products where fold matters


IN_TO_MM = 25.4


def _in(w: float, h: float) -> tuple[float, float]:
    return round(w * IN_TO_MM, 2), round(h * IN_TO_MM, 2)


PRODUCTS: dict[str, Product] = {
    # ---------------------------------------------------------------- TIER 1
    "business_card": {
        "id": "business_card",
        "tier": 1,
        "name_ua": "Візитки",
        "name_en": "Business cards",
        "formats": [
            {
                "id": "eu_90x50",
                "label_ua": "90×50 мм (Європа)",
                "label_en": "90×50 mm (Europe)",
                "width_mm": 90.0,
                "height_mm": 50.0,
                "region": "EU",
            },
            {
                "id": "us_3.5x2",
                "label_ua": "3.5×2″ (США)",
                "label_en": "3.5×2″ (US)",
                "width_mm": _in(3.5, 2)[0],
                "height_mm": _in(3.5, 2)[1],
                "region": "US",
            },
            # Round 12 phase F item 20 — 85×55mm is the single most-missing
            # format per the source doc's own priority call-out. 89×51mm
            # and 3.75×2.25″ deliberately SKIPPED (89×51mm is a near-exact
            # duplicate of 3.5×2″ = 88.9×50.8mm already above — adding it
            # would just create two catalog entries competing for the same
            # real-world card; 3.75×2.25″ needs separate demand
            # confirmation before adding). "Folded business card" is a
            # fold-structure, not a size — not a formats[] entry, same
            # reasoning as brochure's own fold_types field.
            {
                "id": "eu_85x55",
                "label_ua": "85×55 мм (ISO/Європа)",
                "label_en": "85×55 mm (ISO/Europe)",
                "width_mm": 85.0,
                "height_mm": 55.0,
                "region": "EU",
            },
            {
                "id": "square_55x55",
                "label_ua": "55×55 мм (квадрат)",
                "label_en": "55×55 mm (square)",
                "width_mm": 55.0,
                "height_mm": 55.0,
                "region": "INTL",
            },
        ],
        "tolerance_mm": 0.5,
        "bleed_mm": {"EU": 2.0, "US": round(0.125 * IN_TO_MM, 3)},
        "safe_zone_mm": 3.0,
        "fold_types": None,
    },
    "flyer": {
        "id": "flyer",
        "tier": 1,
        "name_ua": "Флаєри/листівки",
        "name_en": "Flyers / postcards",
        "formats": [
            {"id": "a6", "label_ua": "A6 (105×148 мм)", "label_en": "A6 (105×148 mm)",
             "width_mm": 105.0, "height_mm": 148.0, "region": "EU"},
            {"id": "a5", "label_ua": "A5 (148×210 мм)", "label_en": "A5 (148×210 mm)",
             "width_mm": 148.0, "height_mm": 210.0, "region": "EU"},
            {"id": "a4", "label_ua": "A4 (210×297 мм)", "label_en": "A4 (210×297 mm)",
             "width_mm": 210.0, "height_mm": 297.0, "region": "EU"},
            {"id": "100x150", "label_ua": "100×150 мм", "label_en": "100×150 mm",
             "width_mm": 100.0, "height_mm": 150.0, "region": "EU"},
            {"id": "us_4x6", "label_ua": "4×6″ (США)", "label_en": "4×6″ (US)",
             "width_mm": _in(4, 6)[0], "height_mm": _in(4, 6)[1], "region": "US"},
            {"id": "us_5x7", "label_ua": "5×7″ (США)", "label_en": "5×7″ (US)",
             "width_mm": _in(5, 7)[0], "height_mm": _in(5, 7)[1], "region": "US"},
            {"id": "us_letter", "label_ua": "8.5×11″ (США, Letter)", "label_en": "8.5×11″ (US Letter)",
             "width_mm": _in(8.5, 11)[0], "height_mm": _in(8.5, 11)[1], "region": "US"},
            {"id": "dl", "label_ua": "DL (99×210 мм)", "label_en": "DL (99×210 mm)",
             "width_mm": 99.0, "height_mm": 210.0, "region": "EU"},
        ],
        "tolerance_mm": 1.0,
        "bleed_mm": {"EU": 3.0, "US": round(0.125 * IN_TO_MM, 3)},
        "safe_zone_mm": 5.0,
        "fold_types": None,
    },
    "brochure": {
        "id": "brochure",
        "tier": 1,
        "name_ua": "Буклети/брошури",
        "name_en": "Booklets / brochures",
        "formats": [
            {"id": "a4", "label_ua": "A4 (210×297 мм)", "label_en": "A4 (210×297 mm)",
             "width_mm": 210.0, "height_mm": 297.0, "region": "EU"},
            {"id": "a5", "label_ua": "A5 (148×210 мм)", "label_en": "A5 (148×210 mm)",
             "width_mm": 148.0, "height_mm": 210.0, "region": "EU"},
            {"id": "a6", "label_ua": "A6 (105×148 мм)", "label_en": "A6 (105×148 mm)",
             "width_mm": 105.0, "height_mm": 148.0, "region": "EU"},
            {"id": "dl", "label_ua": "DL (99×210 мм)", "label_en": "DL (99×210 mm)",
             "width_mm": 99.0, "height_mm": 210.0, "region": "EU"},
            {"id": "us_letter", "label_ua": "8.5×11″ (США, Letter)", "label_en": "8.5×11″ (US Letter)",
             "width_mm": _in(8.5, 11)[0], "height_mm": _in(8.5, 11)[1], "region": "US"},
            # Round 12 phase F item 24: only the two genuinely NEW sizes
            # from the booklet list (section 3.3) — Half Letter and Square
            # 210×210mm don't already exist for this product. The
            # tri-fold/half-fold/booklet-labeled variants of A4/A5/DL/US
            # Letter were deliberately NOT added as separate catalog
            # entries: they're dimensionally identical to the plain a4/
            # a5/dl/us_letter entries already above (a tri-fold brochure's
            # FLAT trim size is the same A4/DL/Letter sheet, fold type
            # doesn't change it) — adding "duplicate" entries at the same
            # dimensions was explicitly the thing to avoid ("не створюй
            # дублікати"). UploadZone.tsx's brochure productType picker
            # reuses these same shared entries for both branches instead.
            {"id": "half_letter", "label_ua": "Half Letter (США, 8.5×5.5″)", "label_en": "Half Letter (US, 8.5×5.5″)",
             "width_mm": _in(8.5, 5.5)[0], "height_mm": _in(8.5, 5.5)[1], "region": "US"},
            {"id": "square_210", "label_ua": "210×210 мм (квадрат)", "label_en": "210×210 mm (square)",
             "width_mm": 210.0, "height_mm": 210.0, "region": "EU"},
        ],
        "tolerance_mm": 1.0,
        "bleed_mm": {"EU": 3.0, "US": round(0.125 * IN_TO_MM, 3)},
        "safe_zone_mm": 5.0,
        "fold_types": ["eurofold", "z-fold", "half-fold"],
    },
    "poster": {
        "id": "poster",
        "tier": 1,
        "name_ua": "Постери/плакати",
        "name_en": "Posters",
        "formats": [
            {"id": "a3", "label_ua": "A3 (297×420 мм)", "label_en": "A3 (297×420 mm)",
             "width_mm": 297.0, "height_mm": 420.0, "region": "EU"},
            {"id": "a2", "label_ua": "A2 (420×594 мм)", "label_en": "A2 (420×594 mm)",
             "width_mm": 420.0, "height_mm": 594.0, "region": "EU"},
            {"id": "a1", "label_ua": "A1 (594×841 мм)", "label_en": "A1 (594×841 mm)",
             "width_mm": 594.0, "height_mm": 841.0, "region": "EU"},
            {"id": "50x70cm", "label_ua": "50×70 см", "label_en": "50×70 cm",
             "width_mm": 500.0, "height_mm": 700.0, "region": "EU"},
            # Round 12 phase F item 21 — added per the user's explicit,
            # de-duplicated list (A3/A2/A1/50×70cm/18×24″ were already
            # present, confirmed before adding anything). Large-format
            # DPI/profile logic deliberately NOT touched — no approved
            # backend numbers exist for it, same principle Phase D applied
            # to Offset/Large-format/POD; see PROGRESS.md's Phase F TODO
            # for the future large-format-profile phase.
            {"id": "a0", "label_ua": "A0 (841×1189 мм)", "label_en": "A0 (841×1189 mm)",
             "width_mm": 841.0, "height_mm": 1189.0, "region": "EU"},
            {"id": "70x100cm", "label_ua": "70×100 см", "label_en": "70×100 cm",
             "width_mm": 700.0, "height_mm": 1000.0, "region": "EU"},
            {"id": "us_18x24", "label_ua": "18×24″ (США)", "label_en": "18×24″ (US)",
             "width_mm": _in(18, 24)[0], "height_mm": _in(18, 24)[1], "region": "US"},
            {"id": "us_11x17", "label_ua": "11×17″ (США, Tabloid)", "label_en": "11×17″ (US Tabloid)",
             "width_mm": _in(11, 17)[0], "height_mm": _in(11, 17)[1], "region": "US"},
            {"id": "us_24x36", "label_ua": "24×36″ (США)", "label_en": "24×36″ (US)",
             "width_mm": _in(24, 36)[0], "height_mm": _in(24, 36)[1], "region": "US"},
        ],
        "tolerance_mm": 2.0,
        "bleed_mm": 5.0,
        "safe_zone_mm": 10.0,
        "fold_types": None,
    },
    # ------------------------------------------------------- TIER 2 (catalog only, not yet wired)
    "label_sticker": {
        "id": "label_sticker", "tier": 2,
        "name_ua": "Етикетки/стікери", "name_en": "Labels / stickers",
        # Round 12 phase F item 22: common starting sizes per section 3.4's
        # exact list (Rectangular + Round) — most real labels are still
        # custom die-cut (the UI says so explicitly, see UploadZone.tsx's
        # LabelsAdaptiveSteps), these are just a faster starting point.
        # Round sizes have no separate "diameter" field in ProductFormat —
        # represented as width_mm == height_mm (the circle's own bounding
        # square), the honest low-risk option since a round label's real
        # PDF TrimBox genuinely IS that bounding square; label text/region
        # names it "N mm round"/"N in round" so the shape isn't lost.
        "formats": [
            {"id": "50x30", "label_ua": "50×30 мм", "label_en": "50×30 mm", "width_mm": 50.0, "height_mm": 30.0, "region": "INTL"},
            {"id": "60x40", "label_ua": "60×40 мм", "label_en": "60×40 mm", "width_mm": 60.0, "height_mm": 40.0, "region": "INTL"},
            {"id": "70x50", "label_ua": "70×50 мм", "label_en": "70×50 mm", "width_mm": 70.0, "height_mm": 50.0, "region": "INTL"},
            {"id": "80x50", "label_ua": "80×50 мм", "label_en": "80×50 mm", "width_mm": 80.0, "height_mm": 50.0, "region": "INTL"},
            {"id": "100x50", "label_ua": "100×50 мм", "label_en": "100×50 mm", "width_mm": 100.0, "height_mm": 50.0, "region": "INTL"},
            {"id": "100x150", "label_ua": "100×150 мм", "label_en": "100×150 mm", "width_mm": 100.0, "height_mm": 150.0, "region": "INTL"},
            {"id": "us_3x2", "label_ua": "3×2″", "label_en": "3×2″", "width_mm": _in(3, 2)[0], "height_mm": _in(3, 2)[1], "region": "US"},
            {"id": "us_3x4", "label_ua": "3×4″", "label_en": "3×4″", "width_mm": _in(3, 4)[0], "height_mm": _in(3, 4)[1], "region": "US"},
            {"id": "us_4x6", "label_ua": "4×6″", "label_en": "4×6″", "width_mm": _in(4, 6)[0], "height_mm": _in(4, 6)[1], "region": "US"},
            {"id": "round_25mm", "label_ua": "Кругла, 25 мм", "label_en": "Round, 25 mm", "width_mm": 25.0, "height_mm": 25.0, "region": "INTL"},
            {"id": "round_50mm", "label_ua": "Кругла, 50 мм", "label_en": "Round, 50 mm", "width_mm": 50.0, "height_mm": 50.0, "region": "INTL"},
            {"id": "round_2in", "label_ua": "Кругла, 2″", "label_en": "Round, 2″", "width_mm": _in(2, 2)[0], "height_mm": _in(2, 2)[1], "region": "US"},
        ],
        "tolerance_mm": 0.5, "bleed_mm": 2.0, "safe_zone_mm": 2.0, "fold_types": None,
    },
    "packaging_box": {
        "id": "packaging_box", "tier": 2,
        "name_ua": "Упаковка (коробки, пакети)", "name_en": "Packaging (boxes, bags)",
        "formats": [], "tolerance_mm": 1.0, "bleed_mm": 3.0, "safe_zone_mm": 5.0,
        "fold_types": None,
    },
    "badge_certificate": {
        "id": "badge_certificate", "tier": 2,
        "name_ua": "Бейджі/сертифікати/грамоти", "name_en": "Badges / certificates",
        "formats": [
            {"id": "a6", "label_ua": "A6", "label_en": "A6", "width_mm": 105.0, "height_mm": 148.0, "region": "EU"},
            {"id": "a5", "label_ua": "A5", "label_en": "A5", "width_mm": 148.0, "height_mm": 210.0, "region": "EU"},
            {"id": "100x150", "label_ua": "100×150 мм", "label_en": "100×150 mm", "width_mm": 100.0, "height_mm": 150.0, "region": "EU"},
            {"id": "us_4x6", "label_ua": "4×6″", "label_en": "4×6″", "width_mm": _in(4, 6)[0], "height_mm": _in(4, 6)[1], "region": "US"},
        ],
        "tolerance_mm": 1.0, "bleed_mm": 3.0, "safe_zone_mm": 5.0, "fold_types": None,
    },
    "menu_pricelist": {
        "id": "menu_pricelist", "tier": 2,
        "name_ua": "Меню/прайси", "name_en": "Menus / price lists",
        "formats": [
            {"id": "a4", "label_ua": "A4", "label_en": "A4", "width_mm": 210.0, "height_mm": 297.0, "region": "EU"},
            {"id": "a5", "label_ua": "A5", "label_en": "A5", "width_mm": 148.0, "height_mm": 210.0, "region": "EU"},
            {"id": "210x210", "label_ua": "210×210 мм", "label_en": "210×210 mm", "width_mm": 210.0, "height_mm": 210.0, "region": "EU"},
            {"id": "us_letter", "label_ua": "8.5×11″", "label_en": "8.5×11″", "width_mm": _in(8.5, 11)[0], "height_mm": _in(8.5, 11)[1], "region": "US"},
        ],
        "tolerance_mm": 1.0, "bleed_mm": 3.0, "safe_zone_mm": 5.0, "fold_types": None,
    },
    # ------------------------------------------------------- TIER 3 (catalog only, not yet wired)
    "rollup_banner": {
        "id": "rollup_banner", "tier": 3,
        "name_ua": "Roll-up/банери", "name_en": "Roll-up banners",
        "formats": [
            {"id": "85x200cm", "label_ua": "85×200 см", "label_en": "85×200 cm", "width_mm": 850.0, "height_mm": 2000.0, "region": "EU"},
            {"id": "100x200cm", "label_ua": "100×200 см", "label_en": "100×200 cm", "width_mm": 1000.0, "height_mm": 2000.0, "region": "EU"},
            {"id": "us_33x79", "label_ua": "33×79″", "label_en": "33×79″", "width_mm": _in(33, 79)[0], "height_mm": _in(33, 79)[1], "region": "US"},
        ],
        "tolerance_mm": 5.0, "bleed_mm": 5.0, "safe_zone_mm": 20.0, "fold_types": None,
    },
    "catalog_magazine": {
        "id": "catalog_magazine", "tier": 3,
        "name_ua": "Каталоги/журнали", "name_en": "Catalogs / magazines",
        "formats": [
            {"id": "a4", "label_ua": "A4", "label_en": "A4", "width_mm": 210.0, "height_mm": 297.0, "region": "EU"},
            {"id": "210x210", "label_ua": "210×210 мм", "label_en": "210×210 mm", "width_mm": 210.0, "height_mm": 210.0, "region": "EU"},
            {"id": "us_letter", "label_ua": "8.5×11″", "label_en": "8.5×11″", "width_mm": _in(8.5, 11)[0], "height_mm": _in(8.5, 11)[1], "region": "US"},
        ],
        "tolerance_mm": 1.0, "bleed_mm": 3.0, "safe_zone_mm": 5.0,
        "fold_types": ["half-fold", "saddle-stitch"],
    },
    "photobook_album": {
        "id": "photobook_album", "tier": 3,
        "name_ua": "Фотокниги/альбоми", "name_en": "Photo books / albums",
        "formats": [
            {"id": "20x20cm", "label_ua": "20×20 см", "label_en": "20×20 cm", "width_mm": 200.0, "height_mm": 200.0, "region": "EU"},
            {"id": "30x30cm", "label_ua": "30×30 см", "label_en": "30×30 cm", "width_mm": 300.0, "height_mm": 300.0, "region": "EU"},
            {"id": "us_8x8", "label_ua": "8×8″", "label_en": "8×8″", "width_mm": _in(8, 8)[0], "height_mm": _in(8, 8)[1], "region": "US"},
            {"id": "us_12x12", "label_ua": "12×12″", "label_en": "12×12″", "width_mm": _in(12, 12)[0], "height_mm": _in(12, 12)[1], "region": "US"},
        ],
        "tolerance_mm": 2.0, "bleed_mm": 5.0, "safe_zone_mm": 10.0, "fold_types": None,
    },
    "branded_bag": {
        "id": "branded_bag", "tier": 3,
        "name_ua": "Брендовані пакети/торби", "name_en": "Branded bags",
        "formats": [], "tolerance_mm": 1.0, "bleed_mm": 3.0, "safe_zone_mm": 5.0, "fold_types": None,
    },
}

TIER1_PRODUCT_IDS = [p["id"] for p in PRODUCTS.values() if p["tier"] == 1]


def get_product(product_id: str) -> Optional[Product]:
    return PRODUCTS.get(product_id)


def get_format(product_id: str, format_id: str) -> Optional[ProductFormat]:
    product = PRODUCTS.get(product_id)
    if not product:
        return None
    for fmt in product["formats"]:
        if fmt["id"] == format_id:
            return fmt
    return None


class ClosestFormatMatch(TypedDict):
    product_id: str
    format_id: str
    deviation_mm: float
    trim_width_mm: float
    trim_height_mm: float


def find_closest_format(trimbox_pt: tuple[float, float, float, float]) -> Optional[ClosestFormatMatch]:
    """Round 11 phase B: search EVERY product's formats (not just one
    selected product) for the closest match to a given TrimBox — used when
    no product was selected, to auto-suggest one instead of skipping the
    format/safe-zone checks outright.

    A candidate only counts if it's within that SPECIFIC product's own
    tolerance_mm (the same number used when a user explicitly picks that
    product) — reusing each product's already-established tolerance rather
    than inventing one global auto-suggest threshold. Among every product
    that clears its own tolerance, the smallest deviation wins.
    """
    from geometry import match_product_size  # deferred: geometry.py has no reason to import products.py back

    best: Optional[ClosestFormatMatch] = None
    for product_id, product in PRODUCTS.items():
        if not product["formats"]:
            continue
        result = match_product_size(trimbox_pt, product["formats"], product["tolerance_mm"])
        if not result.matched or result.format_id is None:
            continue
        if best is None or result.deviation_mm < best["deviation_mm"]:
            best = {
                "product_id": product_id,
                "format_id": result.format_id,
                "deviation_mm": result.deviation_mm,
                "trim_width_mm": result.trim_width_mm,
                "trim_height_mm": result.trim_height_mm,
            }
    return best


def products_catalog_response() -> dict:
    """Shape returned by a future GET /products endpoint (mirrors the existing
    GET /profiles pattern so the frontend has no hardcoded duplicate)."""
    return {
        pid: {
            "tier": p["tier"],
            "name_ua": p["name_ua"],
            "name_en": p["name_en"],
            "formats": p["formats"],
            "tolerance_mm": p["tolerance_mm"],
            "bleed_mm": p["bleed_mm"],
            "safe_zone_mm": p["safe_zone_mm"],
            "fold_types": p["fold_types"],
        }
        for pid, p in PRODUCTS.items()
    }
