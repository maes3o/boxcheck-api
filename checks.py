"""
BoxCheck — Tier 1 product-aware checks: composes products.py + geometry.py +
pdf_extract.py into severity-tagged check results.

INTEGRATION NOTE (see README_INTEGRATION.md for the full walkthrough):
The result dicts below use generic keys (check/severity/message_ua/message_en
/details) chosen to be easy to read and easy to rename. They are NOT
guaranteed to match main.py's actual field names byte-for-byte (this session
could not read the live source) — Claude Code on the server should adjust
field names to match the existing per-check result shape (whatever
`checks["bleed"]` etc. currently look like) before merging into the response,
and severity.js's aggregation should treat these the same as any other check
for the summary counts to stay correct.

Severity choices deliberately follow the project's established pattern
(per project notes): missing/uncertain info is a soft signal (info/warning),
only *confirmed* defects are critical. So:
  - product_format_match: "ok" if within tolerance, "warning" if it doesn't
    match any known standard format (common/normal for custom sizes — not
    necessarily a mistake), "info" if no product/format was selected at all
    (check skipped, not run).
  - safe_zone: "warning" if any text sits closer than the required margin,
    "critical" only if text actually crosses the trim line (will be
    physically cut off — a confirmed, unrecoverable defect, matching how the
    existing bleed check treats a *confirmed* insufficient-bleed case as
    critical), "ok" if nothing found, "info" if skipped (no product selected
    or page has no extractable text).
"""

from __future__ import annotations
from typing import Optional

from products import PRODUCTS, get_product, find_closest_format
from geometry import match_product_size, check_safe_zone_text
from image_analysis import ImageRegion, get_image_regions
from pdf_extract import get_trimbox_pt, get_text_items_pt


def check_product_format_match(
    trimbox_pt: tuple[float, float, float, float],
    product_id: Optional[str],
    format_id: Optional[str] = None,
    note_ua: str = "",
    note_en: str = "",
) -> dict:
    if not product_id or product_id not in PRODUCTS:
        return {
            "check": "product_format_match",
            "severity": "info",
            "message_ua": "Продукт не обрано — перевірка розміру під стандартний формат пропущена.",
            "message_en": "No product selected — standard-format size check skipped.",
            "details": None,
        }

    product = get_product(product_id)
    if not product["formats"]:
        # e.g. label/packaging — arbitrary/die-cut sizes, no fixed catalog
        return {
            "check": "product_format_match",
            "severity": "info",
            "message_ua": f"«{product['name_ua']}» не має фіксованих стандартних розмірів — перевірка розміру пропущена.",
            "message_en": f"“{product['name_en']}” has no fixed standard sizes — size check skipped.",
            "details": None,
        }

    result = match_product_size(
        trimbox_pt=trimbox_pt,
        formats=product["formats"],
        tolerance_mm=product["tolerance_mm"],
        format_id=format_id,
    )

    trim_dims = f"{result.trim_width_mm}×{result.trim_height_mm} мм"
    trim_dims_en = f"{result.trim_width_mm}×{result.trim_height_mm} mm"

    if result.matched:
        return {
            "check": "product_format_match",
            "severity": "ok",
            "message_ua": f"{note_ua}Розмір макета ({trim_dims}) відповідає формату «{result.format_label_ua}».",
            "message_en": f"{note_en}Layout size ({trim_dims_en}) matches “{result.format_label_en}”.",
            "details": {
                "trim_width_mm": result.trim_width_mm,
                "trim_height_mm": result.trim_height_mm,
                "matched_format_id": result.format_id,
                "deviation_mm": result.deviation_mm,
                "rotated": result.rotated,
            },
        }

    # Round 12 phase G: consequence sentence — one concrete, non-generic
    # closing sentence naming the actual production risk, appended to the
    # warning message (never to the "ok" branch above). Text is verbatim
    # per the user's own spec for this phase ("Page size / format").
    format_consequence_ua = "Виріб можуть обрізати до неправильного розміру або неправильно позиціонувати під час виробництва."
    format_consequence_en = "The finished piece may be cut to the wrong size or positioned incorrectly during production."

    if format_id:
        # user explicitly picked a format and the file doesn't match it
        return {
            "check": "product_format_match",
            "severity": "warning",
            "message_ua": (
                f"Обрано формат «{result.format_label_ua}», але розмір макета — {trim_dims} "
                f"(відхилення {result.deviation_mm} мм, допуск {product['tolerance_mm']} мм). "
                f"{format_consequence_ua}"
            ),
            "message_en": (
                f"“{result.format_label_en}” was selected, but the layout size is {trim_dims_en} "
                f"(off by {result.deviation_mm} mm, tolerance {product['tolerance_mm']} mm). "
                f"{format_consequence_en}"
            ),
            "details": {
                "trim_width_mm": result.trim_width_mm,
                "trim_height_mm": result.trim_height_mm,
                "expected_format_id": format_id,
                "deviation_mm": result.deviation_mm,
            },
        }

    # no format selected — nearest standard size didn't match within tolerance
    return {
        "check": "product_format_match",
        "severity": "warning",
        "message_ua": (
            f"Розмір макета — {trim_dims}. Найближчий стандартний формат «{result.format_label_ua}», "
            f"але відхилення {result.deviation_mm} мм перевищує допуск {product['tolerance_mm']} мм. "
            f"Можливо, це нестандартний розмір — перевірте із замовником/друкарнею. {format_consequence_ua}"
        ),
        "message_en": (
            f"Layout size is {trim_dims_en}. Closest standard format is “{result.format_label_en}”, "
            f"but it's off by {result.deviation_mm} mm (tolerance {product['tolerance_mm']} mm). "
            f"This may be a custom size — confirm with the client/printer. {format_consequence_en}"
        ),
        "details": {
            "trim_width_mm": result.trim_width_mm,
            "trim_height_mm": result.trim_height_mm,
            "closest_format_id": result.format_id,
            "deviation_mm": result.deviation_mm,
        },
    }


def _build_safe_zone_result(
    trimbox_pt: tuple[float, float, float, float],
    text_items: list[tuple[str, tuple[float, float, float, float]]],
    safe_zone_mm: float,
    note_ua: str = "",
    note_en: str = "",
) -> dict:
    """Shared core of check_safe_zone/check_safe_zone_generic (round 11
    phase B): given a resolved safe_zone_mm (from a product's catalog entry
    OR a generic fallback), run the actual violation check and build the
    result dict. `note_ua`/`note_en`, when given, are prepended to the
    message — used to flag that the margin came from auto-detection or a
    generic estimate rather than an explicit product selection, without
    duplicating the whole pass/warning/critical message-building logic for
    each of those cases separately.
    """
    violations = check_safe_zone_text(trimbox_pt, text_items, safe_zone_mm)

    if not violations:
        # Round 6 phase B item 3: the old wording ("Текст не заходить у зону
        # safe zone") reads like a violation even though this is the PASS
        # case (severity "ok") — "safe zone" here names the safe interior
        # area text should stay INSIDE, so "does not enter" is ambiguous at
        # best. Made unambiguous in both directions; the pass/fail
        # determination itself (severity logic above) was already correct.
        return {
            "check": "safe_zone",
            "severity": "ok",
            "message_ua": f"{note_ua}Увесь текст розташований у межах безпечної зони (мінімум {safe_zone_mm} мм від лінії різу).",
            "message_en": f"{note_en}All text stays within the safe zone (minimum {safe_zone_mm} mm from the trim line).",
            "details": None,
        }

    crossing = [v for v in violations if v.crosses_trim]
    severity = "critical" if crossing else "warning"
    count = len(violations)

    examples_ua = "; ".join(
        f"«{v.text}» ({v.min_margin_mm} мм від {_side_ua(v.side)})" for v in violations[:3]
    )
    examples_en = "; ".join(
        f"“{v.text}” ({v.min_margin_mm} mm from {v.side} edge)" for v in violations[:3]
    )
    more_ua = f" І ще {count - 3}." if count > 3 else ""
    more_en = f" And {count - 3} more." if count > 3 else ""

    # Round 12 phase G: consequence sentence, verbatim per the user's spec
    # ("Safe zone") — appended to both branches (crossing/not-crossing);
    # the crossing branch already names "will be cut off" inline for THIS
    # specific violation, this closing sentence states the general risk.
    safe_zone_consequence_ua = "Текст, логотипи або інші важливі елементи можуть бути обрізані або опинитися надто близько до краю після різання."
    safe_zone_consequence_en = "Text, logos or other important elements may be cut or placed too close to the edge after trimming."

    if crossing:
        message_ua = (
            f"{note_ua}{count} об'єкт(и) виходять за межі безпечної зони і перетинають лінію різу — буде обрізано "
            f"(потрібно ≥{safe_zone_mm} мм від лінії різу): {examples_ua}.{more_ua} {safe_zone_consequence_ua}"
        )
        message_en = (
            f"{note_en}{count} object(s) fall outside the safe zone and cross the trim line — will be cut off "
            f"(need ≥{safe_zone_mm} mm from the trim line): {examples_en}.{more_en} {safe_zone_consequence_en}"
        )
    else:
        message_ua = (
            f"{note_ua}{count} об'єкт(и) виходять за межі безпечної зони (потрібно ≥{safe_zone_mm} мм від лінії різу): "
            f"{examples_ua}.{more_ua} {safe_zone_consequence_ua}"
        )
        message_en = (
            f"{note_en}{count} object(s) fall outside the safe zone (need ≥{safe_zone_mm} mm from the trim line): "
            f"{examples_en}.{more_en} {safe_zone_consequence_en}"
        )

    return {
        "check": "safe_zone",
        "severity": severity,
        "message_ua": message_ua,
        "message_en": message_en,
        "details": {
            "required_safe_zone_mm": safe_zone_mm,
            "violation_count": len(violations),
            "violations": [v._asdict() for v in violations],
        },
    }


# Round 11 phase B: fallback margin used only when NO product was selected,
# an entered custom size didn't match anything in the catalog, and no
# generic tolerance had a home — a deliberately mid-range, defensible
# number (equal to flyer/brochure/packaging_box's own safe_zone_mm, not
# invented from scratch), explicitly labeled "estimated" in the message so
# it never reads as an authoritative per-product requirement.
GENERIC_SAFE_ZONE_MM = 5.0


def check_safe_zone_generic(
    trimbox_pt: tuple[float, float, float, float],
    text_items: list[tuple[str, tuple[float, float, float, float]]],
    note_ua: str,
    note_en: str,
    safe_zone_mm: float = GENERIC_SAFE_ZONE_MM,
) -> dict:
    return _build_safe_zone_result(trimbox_pt, text_items, safe_zone_mm, note_ua, note_en)


def check_safe_zone(
    trimbox_pt: tuple[float, float, float, float],
    text_items: list[tuple[str, tuple[float, float, float, float]]],
    product_id: Optional[str],
    note_ua: str = "",
    note_en: str = "",
) -> dict:
    if not product_id or product_id not in PRODUCTS:
        return {
            "check": "safe_zone",
            "severity": "info",
            "message_ua": "Продукт не обрано — перевірка safe zone (відступів тексту від лінії різу) пропущена.",
            "message_en": "No product selected — safe-zone (text-to-trim margin) check skipped.",
            "details": None,
        }

    product = get_product(product_id)
    safe_zone_mm = product["safe_zone_mm"]
    return _build_safe_zone_result(trimbox_pt, text_items, safe_zone_mm, note_ua, note_en)


def _side_ua(side: str) -> str:
    return {"left": "лівого краю", "right": "правого краю", "top": "верхнього краю", "bottom": "нижнього краю"}[side]


def check_safe_zone_multi(
    pages_data: list[tuple[tuple[float, float, float, float], list[tuple[str, tuple[float, float, float, float]]]]],
    product_id: Optional[str],
    note_ua: str = "",
    note_en: str = "",
) -> dict:
    """Runs check_safe_zone per page and combines into one document-wide
    result (Phase D: real multi-page checking) — a text box crossing the
    trim line on page 3 of a multi-page proof must not go unreported just
    because only page 1 has a rendered canvas preview. `details["violations"]`
    stays scoped to page 1 only — canvas pins only make sense placed against
    page 1's rendered preview, a page-3 bbox would land in the wrong spot on
    page 1's canvas.

    Every page shares the same `product_id`, so check_safe_zone's per-page
    result is either "info" (no product selected — skipped) for every page
    uniformly, or one of ok/warning/critical for every page; there's never a
    mix of "info" with a real result, so severity aggregation only needs to
    consider that second case.
    """
    per_page = [check_safe_zone(trim, items, product_id, note_ua, note_en) for trim, items in pages_data]
    if len(per_page) == 1 or not product_id or product_id not in PRODUCTS:
        return per_page[0]

    total = 0
    per_page_counts: list[tuple[int, int]] = []
    crosses_any = False
    for i, page_result in enumerate(per_page, start=1):
        details = page_result.get("details")
        if not details:
            continue
        total += details["violation_count"]
        per_page_counts.append((i, details["violation_count"]))
        if any(v["crosses_trim"] for v in details["violations"]):
            crosses_any = True

    if total == 0:
        return {
            "check": "safe_zone",
            "severity": "ok",
            "message_ua": f"{note_ua}Увесь текст на всіх {len(per_page)} сторінках розташований у межах безпечної зони.",
            "message_en": f"{note_en}All text on every one of the {len(per_page)} pages stays within the safe zone.",
            "details": None,
        }

    safe_zone_mm = get_product(product_id)["safe_zone_mm"]
    # Round 12 phase A item 3: the aggregate message used to be just
    # "page N — count", discarding the per-page example text/side/margin
    # that check_safe_zone already computes for each page — confirmed via a
    # live 2-page test (page 1 clean, page 2 with a real violation) that
    # this made the sidebar message tell the reader THAT page 2 has a
    # problem but not WHAT it is, and — since details["violations"] is
    # deliberately scoped to page 1 only (no canvas to pin a non-page-1
    # bbox against) — page 2's violation produced no pin either, so this
    # was the reader's ONLY source of detail for it. Pulling the first
    # violation's own text/side/margin from each page's own `details`
    # fixes that without touching the page-1-only pin scoping.
    parts_ua = []
    parts_en = []
    for i, n in per_page_counts:
        v = per_page[i - 1]["details"]["violations"][0]
        example_ua = f"«{v['text']}», {v['min_margin_mm']} мм від {_side_ua(v['side'])}"
        example_en = f"“{v['text']}”, {v['min_margin_mm']} mm from {v['side']} edge"
        extra_ua = f"; ще {n - 1}" if n > 1 else ""
        extra_en = f"; +{n - 1} more" if n > 1 else ""
        parts_ua.append(f"стор. {i} — {n} ({example_ua}{extra_ua})")
        parts_en.append(f"p.{i} — {n} ({example_en}{extra_en})")
    parts_ua = "; ".join(parts_ua)
    parts_en = "; ".join(parts_en)
    severity = "critical" if crosses_any else "warning"

    # Round 12 phase G: same verbatim consequence sentence as the
    # single-page safe_zone result (_build_safe_zone_result) — this
    # aggregate branch builds its own message text from scratch rather
    # than reusing that function, so it needs its own copy appended too.
    safe_zone_consequence_ua = "Текст, логотипи або інші важливі елементи можуть бути обрізані або опинитися надто близько до краю після різання."
    safe_zone_consequence_en = "Text, logos or other important elements may be cut or placed too close to the edge after trimming."

    return {
        "check": "safe_zone",
        "severity": severity,
        "message_ua": (
            f"{note_ua}Загалом {total} об'єкт(и) на {len(per_page_counts)} з {len(per_page)} сторінок "
            f"виходять за межі безпечної зони (потрібно ≥{safe_zone_mm} мм від лінії різу): {parts_ua}. {safe_zone_consequence_ua}"
        ),
        "message_en": (
            f"{note_en}Overall {total} object(s) across {len(per_page_counts)} of {len(per_page)} pages "
            f"fall outside the safe zone (need ≥{safe_zone_mm} mm from the trim line): {parts_en}. {safe_zone_consequence_en}"
        ),
        "details": {
            "required_safe_zone_mm": safe_zone_mm,
            "violation_count": total,
            "pages_with_violations": [i for i, _ in per_page_counts],
            "violations": per_page[0]["details"]["violations"] if per_page[0].get("details") else [],
        },
    }


def check_image_quality(page, dpi_threshold: float = 300.0) -> dict:
    """Location-aware image check: flags non-CMYK (RGB/Lab/etc.) images and
    images placed below dpi_threshold effective resolution. Unlike the two
    checks above, this one takes the live pymupdf.Page directly (not
    pre-extracted trimbox/text) because get_image_regions needs
    page.get_image_info() — merge its `regions` into whatever the project's
    EXISTING colorspace/DPI check already produces rather than replacing it;
    this is meant to add per-image location data (bbox_pt) that check likely
    doesn't have yet, per project notes.

    Severity follows the same soft-signal convention as the other Tier 1
    checks: "warning", not "critical" — an RGB or low-DPI image is very
    commonly still printable (RIP/prepress will convert or the printer may
    accept it), so it's flagged for review rather than treated as a
    confirmed, unrecoverable defect.

    `page` may also be a list of pages (Phase D: real multi-page checking) —
    counts/messaging then aggregate across every page (a low-DPI image on
    page 3 must not go unreported just because only page 1 has a rendered
    canvas preview), but `details["regions"]` — consumed by
    build_annotations() for canvas pins — stays scoped to the FIRST page
    only, since only page 1 has a rendered preview to pin a bbox against.
    """
    page_list = list(page) if isinstance(page, (list, tuple)) else [page]
    per_page_regions = [get_image_regions(p, dpi_threshold=dpi_threshold) for p in page_list]
    regions = [r for page_regions in per_page_regions for r in page_regions]
    page1_regions = per_page_regions[0]
    # Round 12 phase C: which pages actually have a flagged image, mirroring
    # check_safe_zone_multi's own pages_with_violations — lets the sidebar
    # tag "стор. N" on this check the same way it already can for safe_zone,
    # and lets the page-switcher know which pages to flag without a
    # separate live call.
    pages_with_issues = [
        i for i, page_regions in enumerate(per_page_regions, start=1)
        if any(r["is_rgb"] or r["low_dpi"] for r in page_regions)
    ]

    if not regions:
        return {
            "check": "image_quality",
            "severity": "info",
            "message_ua": "У документі немає растрових зображень — перевірка кольору/DPI зображень пропущена.",
            "message_en": "No raster images in the document — image colorspace/DPI check skipped.",
            "details": None,
        }

    # `regions` is per PLACEMENT (the same embedded image can be drawn more
    # than once, e.g. a repeated logo) — that's what canvas pins need, one
    # per physical spot on the page. But "N images have issue X" should
    # count distinct image RESOURCES, not placements, or a single repeated
    # logo inflates the count and reads as if N different files need fixing.
    # Colorspace is a property of the resource, so it's identical across
    # every placement sharing an xref; DPI is not (the same resource can be
    # placed at different sizes), so a resource counts as low-DPI if its
    # worst (smallest) placement falls below the threshold.
    by_xref: dict[int, list] = {}
    for r in regions:
        by_xref.setdefault(r["xref"], []).append(r)
    unique_count = len(by_xref)
    rgb_count = sum(1 for rs in by_xref.values() if rs[0]["is_rgb"])
    low_dpi_count = sum(1 for rs in by_xref.values() if any(r["low_dpi"] for r in rs))

    if rgb_count == 0 and low_dpi_count == 0:
        return {
            "check": "image_quality",
            "severity": "ok",
            "message_ua": f"Усі зображення ({unique_count}) у CMYK/Grayscale і мають достатню роздільну здатність (≥{dpi_threshold:g} DPI).",
            "message_en": f"All images ({unique_count}) are CMYK/Grayscale and have sufficient resolution (≥{dpi_threshold:g} DPI).",
            "details": {"image_count": unique_count, "rgb_count": 0, "low_dpi_count": 0, "regions": page1_regions},
        }

    parts_ua, parts_en = [], []
    if rgb_count:
        parts_ua.append(f"{rgb_count} у RGB (потребують конвертації в CMYK)")
        parts_en.append(f"{rgb_count} in RGB (need CMYK conversion)")
    if low_dpi_count:
        parts_ua.append(f"{low_dpi_count} з роздільною здатністю нижче {dpi_threshold:g} DPI")
        parts_en.append(f"{low_dpi_count} below {dpi_threshold:g} DPI")

    # Round 12 phase G: consequence sentences, verbatim per the user's spec
    # ("RGB image"/"Low DPI / image resolution") — this check combines both
    # kinds of problem into one result, so both sentences are included when
    # both apply (not one crowding out the other).
    consequence_parts_ua = []
    consequence_parts_en = []
    if rgb_count:
        consequence_parts_ua.append("Кольори зображення можуть змінитися під час конвертації файла в CMYK для друку.")
        consequence_parts_en.append("The image colors may change when the file is converted to CMYK for printing.")
    if low_dpi_count:
        consequence_parts_ua.append("Зображення може виглядати нечітким, розмитим або піксельним у вибраному розмірі друку.")
        consequence_parts_en.append("The image may look soft, blurry or pixelated at the selected print size.")
    consequence_ua = " ".join(consequence_parts_ua)
    consequence_en = " ".join(consequence_parts_en)

    return {
        "check": "image_quality",
        "severity": "warning",
        "message_ua": f"З {unique_count} зображень: " + "; ".join(parts_ua) + f". {consequence_ua}",
        "message_en": f"Of {unique_count} images: " + "; ".join(parts_en) + f". {consequence_en}",
        "details": {
            "image_count": unique_count,
            "rgb_count": rgb_count,
            "low_dpi_count": low_dpi_count,
            "regions": page1_regions,
            "pages_with_issues": pages_with_issues,
        },
    }


def build_annotations(safe_zone_check: dict, image_quality_check: dict) -> list[dict]:
    """Unifies every check result that carries a page-location (bbox_pt) into
    one flat list the frontend can render as canvas pins / highlight rects,
    per Gemini's Checker spec: numbered annotation pins tied to specific
    checks, and RGB-region/low-DPI highlighting in the canvas's dedicated
    visualization modes. Each item: {id, kind, bbox_pt, label_ua, label_en,
    severity, count, instances}. Call this once per page after running the
    checks above and attach the result as e.g. page["annotations"] in the
    response.

    Round 6 phase E: rgb_image/low_dpi_image annotations are grouped by the
    underlying image xref (same reasoning as phase C's image_count dedup) —
    one pin per distinct problem RESOURCE, not one per placement. A tiled
    background used 84 times used to produce 84 numbered pins stacked on top
    of each other for what is really one recurring issue; `count` carries how
    many placements share it and `instances` carries every placement's
    bbox_pt (the pin itself sits at the first placement) so the frontend can
    show "×84" and, if it wants to later, let the user page through
    locations. safe_zone_violation annotations are NOT grouped — each is
    already a distinct text object, not a repeated resource.
    """
    annotations: list[dict] = []

    sz_details = safe_zone_check.get("details")
    if sz_details:
        for i, v in enumerate(sz_details.get("violations", [])):
            crosses = v.get("crosses_trim", False)
            annotations.append(
                {
                    "id": f"safe-zone-{i}",
                    "kind": "safe_zone_violation",
                    "bbox_pt": v["bbox_pt"],
                    "label_ua": f"«{v['text']}» — {'перетинає лінію різу' if crosses else 'близько до краю'}",
                    "label_en": f"“{v['text']}” — {'crosses the trim line' if crosses else 'close to the edge'}",
                    "severity": "critical" if crosses else "warning",
                }
            )

    iq_details = image_quality_check.get("details")
    if iq_details:
        rgb_by_xref: dict[int, list] = {}
        low_dpi_by_xref: dict[int, list] = {}
        for region in iq_details.get("regions", []):
            if region["is_rgb"]:
                rgb_by_xref.setdefault(region["xref"], []).append(region)
            if region["low_dpi"]:
                low_dpi_by_xref.setdefault(region["xref"], []).append(region)

        for xref, group in rgb_by_xref.items():
            count = len(group)
            suffix_ua = f" (×{count})" if count > 1 else ""
            suffix_en = f" (×{count})" if count > 1 else ""
            annotations.append(
                {
                    "id": f"rgb-image-{xref}",
                    "kind": "rgb_image",
                    "bbox_pt": group[0]["bbox_pt"],
                    "label_ua": f"Зображення в RGB{suffix_ua}",
                    "label_en": f"RGB image{suffix_en}",
                    "severity": "warning",
                    "count": count,
                    "instances": [g["bbox_pt"] for g in group],
                }
            )

        for xref, group in low_dpi_by_xref.items():
            count = len(group)
            worst_dpi = min(g["effective_dpi"] for g in group)
            suffix_ua = f" ×{count}" if count > 1 else ""
            suffix_en = f" ×{count}" if count > 1 else ""
            annotations.append(
                {
                    "id": f"low-dpi-image-{xref}",
                    "kind": "low_dpi_image",
                    "bbox_pt": group[0]["bbox_pt"],
                    "label_ua": f"Низька роздільна здатність ({worst_dpi:g} DPI){suffix_ua}",
                    "label_en": f"Low resolution ({worst_dpi:g} DPI){suffix_en}",
                    "severity": "warning",
                    "count": count,
                    "instances": [g["bbox_pt"] for g in group],
                }
            )

    return annotations


def run_tier1_product_checks(
    trimbox_pt: tuple[float, float, float, float],
    text_items: list[tuple[str, tuple[float, float, float, float]]],
    product_id: Optional[str],
    format_id: Optional[str] = None,
    page=None,
    has_real_trimbox: bool = True,
    declared_width_mm: Optional[float] = None,
    declared_height_mm: Optional[float] = None,
) -> tuple[list[dict], str]:
    """Convenience entry point: call this from main.py's /check handler after
    extracting trimbox_pt (pdf_extract.get_trimbox_pt) and text_items
    (pdf_extract.get_text_items_pt) for PAGE 1, pass through whatever
    product_id/format_id the frontend's new product-selector step sends.
    Pass the live `page` object too (optional, backward-compatible) to also
    run the image_quality check. Returns (results, tier1_status,
    effective_product_id, effective_format_id) — results is a list of two
    or three check-result dicts to merge into the existing checks
    collection (use build_annotations() on the safe_zone + image_quality
    results for the unified pin/highlight list); tier1_status is one of
    "explicit" / "auto_trimbox" / "auto_declared" / "declared_no_match" /
    "none", for the frontend's "was this a complete check or a partial
    one" banner (round 11 phase B item 2); effective_product_id/
    effective_format_id are what was ACTUALLY checked against — equal to
    the input product_id/format_id when given explicitly, or the
    auto-matched ids when not (round 12 phase E item 2: main.py's response
    uses these, not the raw input params, so the frontend can see what was
    auto-detected).

    `page` may also be a list of every page in the document (Phase D: real
    multi-page checking) — safe_zone and image_quality then aggregate across
    every page instead of only page 1 (product_format_match stays a page-1-
    only check regardless: it validates the document's overall order size,
    not per-page content, and check_page_size_consistency already flags
    pages that differ in size from page 1). trimbox_pt/text_items are always
    page 1's own — extraction for any additional pages happens here.

    Round 11 phase B: when no product_id was given, this no longer just
    skips format/safe-zone checks outright. It tries, in order:
      1. An entered custom size (declared_width_mm/height_mm) matched
         against the WHOLE catalog (products.find_closest_format) — lets a
         user who knows the intended size get a real check even if the
         file's own TrimBox is missing/unreliable.
      2. The file's own TrimBox matched against the whole catalog — but
         only when has_real_trimbox is True (TrimBox actually set apart
         from MediaBox); matching an arbitrary full-page MediaBox against
         the catalog would be a false-confidence guess, not a real signal.
      3. If a declared size was given but matched nothing in the catalog:
         a generic, clearly-labeled-as-estimated safe-zone margin
         (GENERIC_SAFE_ZONE_MM) rather than skipping outright — no
         format-match check is meaningful here (there's no category to
         compare the declared size against), so product_format_match still
         reports "skipped" in this one case specifically.
      4. Otherwise: unchanged — both checks report "skipped", tier1_status
         "none".
    """
    effective_product_id = product_id
    effective_format_id = format_id
    tier1_status = "explicit"
    generic_note_ua = ""
    generic_note_en = ""
    pages = list(page) if isinstance(page, (list, tuple)) else ([page] if page is not None else None)

    if not product_id:
        match = None
        if declared_width_mm and declared_height_mm:
            declared_trimbox_pt = (0.0, 0.0, declared_width_mm * 72.0 / 25.4, declared_height_mm * 72.0 / 25.4)
            match = find_closest_format(declared_trimbox_pt)
            tier1_status = "auto_declared" if match else "declared_no_match"
        elif has_real_trimbox:
            match = find_closest_format(trimbox_pt)
            tier1_status = "auto_trimbox" if match else "none"
        else:
            tier1_status = "none"

        if match:
            effective_product_id = match["product_id"]
            effective_format_id = match["format_id"]
            product = get_product(effective_product_id)
            source_ua = "введеному розміру" if tier1_status == "auto_declared" else "розміру TrimBox у файлі"
            source_en = "the entered size" if tier1_status == "auto_declared" else "the file's own TrimBox"
            generic_note_ua = (
                f"Продукт не обрано вручну — автоматично визначено «{product['name_ua']}» за {source_ua}. "
            )
            generic_note_en = (
                f"No product was manually selected — auto-detected as “{product['name_en']}” from {source_en}. "
            )

    if tier1_status == "declared_no_match":
        format_result = check_product_format_match(trimbox_pt, None, None)  # stays "skipped" — nothing to compare against
        w_mm = round(declared_width_mm, 1)
        h_mm = round(declared_height_mm, 1)
        note_ua = (
            f"Вказаний розмір ({w_mm}×{h_mm} мм) не відповідає жодному стандартному формату в каталозі — "
            f"застосовано орієнтовний відступ безпечної зони {GENERIC_SAFE_ZONE_MM} мм (не точна вимога для вашого типу продукції). "
        )
        note_en = (
            f"The entered size ({w_mm}×{h_mm} mm) doesn't match any standard catalog format — "
            f"applying an estimated safe-zone margin of {GENERIC_SAFE_ZONE_MM} mm (not an exact requirement for your product type). "
        )
        safe_zone_result = check_safe_zone_generic(trimbox_pt, text_items, note_ua, note_en)
    else:
        format_result = check_product_format_match(trimbox_pt, effective_product_id, effective_format_id, generic_note_ua, generic_note_en)

        if pages and len(pages) > 1:
            pages_trim_text = [(trimbox_pt, text_items)] + [
                (get_trimbox_pt(p), get_text_items_pt(p)) for p in pages[1:]
            ]
            safe_zone_result = check_safe_zone_multi(pages_trim_text, effective_product_id, generic_note_ua, generic_note_en)
        else:
            safe_zone_result = check_safe_zone(trimbox_pt, text_items, effective_product_id, generic_note_ua, generic_note_en)

    results = [format_result, safe_zone_result]

    if pages:
        results.append(check_image_quality(pages))
    # Round 12 phase E item 2: also return the EFFECTIVE ids (what was
    # actually checked against — auto-matched when the caller passed none)
    # rather than making main.py fall back to echoing the raw, possibly-
    # unset query params. Needed for the frontend's auto-detect
    # confirmation banner (report.product_id was previously None even when
    # tier1_status was "auto_trimbox"/"auto_declared", since main.py only
    # ever echoed back the literal input product_id/format_id).
    return results, tier1_status, effective_product_id, effective_format_id
