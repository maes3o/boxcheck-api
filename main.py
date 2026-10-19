import asyncio
import gzip
import json
import logging
import os
import struct
import time
import base64
import io
import subprocess
import tempfile
import zlib
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from typing import Literal, Optional
import httpx
import pymupdf
from PIL import Image
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from checks import run_tier1_product_checks, build_annotations, check_safe_zone, check_image_quality
from pdf_extract import get_trimbox_pt, get_text_items_pt
from fix_bleed import fix_bleed_pdf, NoDeclaredTrimBoxError
from render_preview import (
    render_page_preview,
    render_ink_heatmap,
    render_cmyk_data_bitmap,
    _cmyk_pixmap_array,
    DEFAULT_MAX_DIMENSION_PX,
)
from products import products_catalog_response
from printer_profiles import PRINTER_PROFILES
from spot_separations import render_spot_separations
from gs_composite_preview import render_gs_composite_preview
from cmyk_lut import get_lut_bytes, GRID_N as LUT_GRID_N
from ink_coverage import InkError
from ink_runner import InkBusy, InkTimeout, InkWorkerCrash, run_ink_analysis, sweep_stale_tempdirs

MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024
PROCESSING_TIMEOUT_SECONDS = 30

# The verified pdfcer Ink Manager wrapper (see
# vendor/pdfcer/crates/pdfcer-render/examples/boxcheck_ink_manager.rs): a
# fixed-configuration CLI — 100 DPI, 512 MiB colorant-buffer ceiling — that
# takes a PDF PATH plus an output PNG path and `--exclude-spot NAME` per
# colorant to leave out of the final collapse. Absolute on purpose: the
# service's WorkingDirectory is this project root, so a relative path would
# work today and break the moment the unit file changes.
INK_MANAGER_BIN = "/home/ubuntu/projects/boxcheck/vendor/pdfcer/target/release/examples/boxcheck_ink_manager"
# Same value/convention as spot_separations.py's and gs_composite_preview.py's
# own GS_TIMEOUT_SECONDS (25s) — this is the same kind of synchronous
# rasterizer subprocess, deliberately kept at the same budget rather than
# inventing a new number. Kept strictly BELOW PROCESSING_TIMEOUT_SECONDS so a
# slow wrapper degrades to the existing all-on preview instead of timing the
# whole request out at the endpoint's own 30s.
INK_MANAGER_TIMEOUT_SECONDS = 25

# The BCPLANE2 plane exporter (see
# vendor/pdfcer/crates/pdfcer-render/examples/boxcheck_planes.rs): same fixed
# configuration as the Ink Manager wrapper (100 DPI, 512 MiB colorant ceiling)
# but it retains the authoritative N-channel CmykBuffer BEFORE the sRGB
# collapse and writes the BCPLANE2 container (u8 planes, per-plane directory,
# CRC32) instead of a PNG. Same absolute-path reasoning as INK_MANAGER_BIN.
PLANES_BIN = "/home/ubuntu/projects/boxcheck/vendor/pdfcer/target/release/examples/boxcheck_planes"
# Same rasterizer-subprocess budget as the Ink Manager wrapper: this is the
# SAME render (identical options) with a different final step, so it costs the
# same and gets the same 25s ceiling below the endpoint's own 30s.
PLANES_TIMEOUT_SECONDS = 25
# Decompressed-container sanity ceiling. 9 planes × 2831×2242 = ~54.5 MB for
# the real QA page; 256 MB comfortably covers any page this 100-DPI wrapper
# can legally produce at MAX_PIXMAP_EDGE while refusing absurd/alien payloads
# before we hold them in memory.
PLANES_MAX_DECOMPRESSED_BYTES = 256 * 1024 * 1024

logger = logging.getLogger("boxcheck")

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    # X-Lut-Grid-N (see /lut/cmyk-to-srgb) isn't in the browser's default
    # CORS-safelisted response headers, so without this the frontend's
    # `res.headers.get("X-Lut-Grid-N")` silently returns null cross-origin —
    # caught via live Playwright testing (curl doesn't enforce CORS, so it
    # looked fine there) even though the frontend's "9" fallback happened to
    # be correct anyway. Explicit allowlist rather than "*" here since
    # exposed *response* headers (unlike allowed request headers above) are
    # read by page JS, not just sent by the browser.
    expose_headers=["X-Lut-Grid-N"],
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": {"code": "rate_limited", "message": f"Rate limit exceeded: {exc.detail}"}},
    )


# --- Telegram notifications (feedback + unhandled-error alerts) ---
# Token/chat id come from the environment (systemd EnvironmentFile) so
# they never end up hardcoded in source or committed anywhere.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
GOOGLE_SHEETS_WEBHOOK_URL = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL")
ERROR_NOTIFY_THROTTLE_SECONDS = 600

_error_notify_last_sent: dict[str, float] = {}


def send_telegram_message(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured; skipping notification")
        return False
    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text},
            timeout=5.0,
        )
        return resp.status_code == 200
    except httpx.HTTPError:
        logger.exception("Failed to send Telegram notification")
        return False


def send_to_google_sheets(message: str, email: str) -> None:
    # Best-effort duplicate of feedback into a Sheets log, independent of
    # Telegram: script.google.com can be slow or flaky, so a failure here
    # must never block the Telegram send or the response to the user.
    if not GOOGLE_SHEETS_WEBHOOK_URL:
        logger.warning("Google Sheets webhook not configured; skipping")
        return
    try:
        httpx.post(
            GOOGLE_SHEETS_WEBHOOK_URL,
            json={"feedback": message, "email": email},
            timeout=5.0,
        )
    except Exception:
        # Deliberately broad: this is a fire-and-forget side channel, so
        # nothing it does may ever propagate to the caller and break the
        # Telegram send or the response to the user.
        logger.exception("Failed to log feedback to Google Sheets")


def notify_server_error(exc: Exception, path: str) -> None:
    # Throttle per exception type so a burst of identical failures (e.g. a
    # bad deploy hitting every request) sends one alert per 10 minutes
    # instead of spamming the chat.
    key = type(exc).__name__
    now = time.monotonic()
    last = _error_notify_last_sent.get(key)
    if last is not None and now - last < ERROR_NOTIFY_THROTTLE_SECONDS:
        return
    _error_notify_last_sent[key] = now
    send_telegram_message(f"BoxCheck server error\n{key}: {exc}\nPath: {path}")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception")
    notify_server_error(exc, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": "internal_error", "message": "Internal server error."}},
    )


# Damaged / truncated PDFs surface from MuPDF as syntax/format errors raised
# deep inside the check (not as FileDataError at open time). Registered as
# class-specific handlers so they run INSIDE the CORS middleware — unlike the
# catch-all handler above, whose 500 carries no CORS headers and made the
# browser report "Failed to fetch" (frontend: "server unreachable"). Same JSON
# contract as the existing 422 invalid_pdf; no exception text is exposed.
def _invalid_pdf_response(request: Request, exc: Exception):
    logger.warning("Rejected unreadable PDF on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=422,
        content={"detail": {"code": "invalid_pdf", "message": "File is not a valid or readable PDF."}},
    )


app.add_exception_handler(pymupdf.mupdf.FzErrorSyntax, _invalid_pdf_response)
app.add_exception_handler(pymupdf.mupdf.FzErrorFormat, _invalid_pdf_response)


class EncryptedPDFError(Exception):
    pass


MM_TO_PT = 2.8346
# PDF boxes are stored as float32 points, so an exact 3 mm bleed can read back
# as 2.9999999 mm. Only the bleed pass/fail comparison gets this slack (same
# 0.05 mm the frontend geometry card already uses); no other geometry check.
BLEED_TOLERANCE_MM = 0.05
UNIT_TO_PT = {"mm": 2.8346, "pt": 1.0, "inch": 72.0}

PROFILES = {
    # tac_limit_pct: round 6 phase G — max total-area-coverage (sum of C+M+Y+K)
    # a substrate/press combo can safely hold before ink stops drying properly
    # or the sheet cracks/offsets. "unknown" gets the LOWEST limit of any
    # profile (not the highest, unlike bleed_mm) — for a maximum-allowed
    # value, "conservative when we don't know the press" means the tightest
    # cap, not the loosest, so it still catches real problems rather than
    # waving through whatever a specific known profile would have flagged.
    # NOTE (04.10.2026): every tac_limit_pct below (carton 300 included) is a BoxCheck
    # working DEFAULT per profile, not an industry/universal limit — real TAC depends on
    # the printer, process, substrate, inks and colour workflow. The frontend words it
    # as "Default TAC". Values intentionally unchanged.
    "carton":   {"bleed_mm": 3.0, "dpi_threshold": 300, "hairline_mm": 0.30, "tac_limit_pct": 300},
    "label":    {"bleed_mm": 2.0, "dpi_threshold": 300, "hairline_mm": 0.15, "tac_limit_pct": 280},
    "flexible": {"bleed_mm": 4.0, "dpi_threshold": 300, "hairline_mm": 0.15, "tac_limit_pct": 280},
    "digital":  {"bleed_mm": 2.0, "dpi_threshold": 300, "hairline_mm": 0.10, "tac_limit_pct": 240},
    "unknown":  {"bleed_mm": 5.0, "dpi_threshold": 300, "hairline_mm": 0.30, "tac_limit_pct": 240},
    # STEP 3 (v1 defaults): offset lithographic print. ISO 12647-2:2013 is
    # the reference standard for offset PROCESS CONTROL (tone value
    # increase, colorimetric aims per substrate type) — it does NOT define
    # any of the 4 preflight numbers below; none of them should be read as
    # an ISO 12647-2 requirement. Each is a separate, explicitly-sourced
    # convention, confirmed with the user before adding this key:
    #   - bleed_mm: 3.0 — common commercial-print/prepress default, not an
    #     ISO number. Matches this project's own existing "carton" bleed
    #     and the flyer/brochure catalog's own EU bleed (products.py) —
    #     reused for internal consistency, not newly invented.
    #   - dpi_threshold: 300 — common offset prepress target; also already
    #     the one value shared by every other profile above (no profile in
    #     this dict uses a different DPI threshold).
    #   - hairline_mm: 0.20 — conservative/common printer-spec line
    #     threshold. Deliberately between "digital"'s 0.10 (finest, toner/
    #     inkjet) and "carton"/"unknown"'s 0.30 (heaviest substrates) —
    #     no single authoritative source was found for an offset-specific
    #     number, so this is a conservative estimate, not a verified
    #     standard figure.
    #   - tac_limit_pct: 300 — common offset printer default. Surfaced in
    #     thresholds_used/reports, same as every other profile's
    #     tac_limit_pct. Update (A6, 28.09.2026): this field IS enforced —
    #     just not by this backend. render_preview.py already computes the
    #     real max_coverage_pct for the ink heatmap; it's the frontend's
    #     adaptReport.ts that compares that number against this limit
    #     (round 6 phase G item 2) and pushes a real warning/ok "ink_limit"
    #     check into the report. This backend itself never reads
    #     tac_limit_pct back to compare against anything — enforcement
    #     lives entirely client-side.
    "offset":   {"bleed_mm": 3.0, "dpi_threshold": 300, "hairline_mm": 0.20, "tac_limit_pct": 300},
}

# Round 11 phase E: the flat 5.0mm "unknown" default is the correct
# worst-case when we don't even know the PRODUCT (could be packaging/die-cut,
# which genuinely needs that much). But when a flat, sheet-fed tier-1 product
# IS selected (business_card/flyer/brochure/poster) and only the print
# METHOD is "unknown", 5mm is needlessly strict — confirmed empirically with
# a synthetic 3mm-bleed flyer fixture (a normal real-world bleed value) that
# the flat 5mm threshold flagged as a false "critical". Packaging/die-cut
# tier-1 products are deliberately absent from this table so they keep
# falling through to the conservative 5.0mm default above.
UNKNOWN_METHOD_BLEED_MM_BY_PRODUCT = {
    "business_card": 2.5,
    "flyer": 2.5,
    "brochure": 2.5,
    "poster": 2.5,
}

TOKEN_RE = re.compile(
    r"\((?:\\.|[^\\()])*\)"    # literal string (...) - opaque, never an operator
    r"|<[0-9A-Fa-f\s]*>"       # hex string <...> - opaque, never an operator
    r"|/[A-Za-z0-9\#\+\-\_\.]+"
    r"|-?\d*\.?\d+"
    r"|[A-Za-z\*]+"
    r"|['\"]"
)
FILL_OPS_ONLY = {"f", "F", "f*"}
STROKE_OPS_ONLY = {"S", "s"}
FILL_AND_STROKE_OPS = {"B", "B*", "b", "b*"}
TEXT_PAINT_OPS = {"Tj", "TJ", "'", '"'}
FILL_TEXT_RENDER_MODES = {0, 2, 4, 6}


def classify_fill_color(op, nums):
    op = op.lower()
    if op == "g" and len(nums) >= 1:
        v = nums[0]
        if v >= 0.98:
            return "white"
        if v <= 0.02:
            return "black"
    if op == "rg" and len(nums) >= 3:
        r, gg, b = nums[0], nums[1], nums[2]
        if r >= 0.98 and gg >= 0.98 and b >= 0.98:
            return "white"
        if r <= 0.02 and gg <= 0.02 and b <= 0.02:
            return "black"
    if op == "k" and len(nums) >= 4:
        c, m, y, k = nums[0], nums[1], nums[2], nums[3]
        if c <= 0.02 and m <= 0.02 and y <= 0.02 and k <= 0.02:
            return "white"
        if k >= 0.98:
            return "black"
    return "other"


def _classify_separation_tint(colorant_names):
    """White/black/other classification for a fill/stroke currently set
    through a Separation/DeviceN colorspace (`colorant_names` — see
    _get_colorspace_map). Deliberately identity-based, not tint-based: a
    Separation/DeviceN tint has the OPPOSITE polarity of DeviceGray (1.0 =
    full ink laid down, not white paper), so classify_fill_color's numeric
    thresholds must never see this value — see the overprint audit for the
    concrete failure this caused (a 100%-tint /PANTONE Black C fill was
    being read as "white" because 1.0 >= the DeviceGray white threshold).
    Same substring heuristic already used for a named Pattern colorant just
    below, extended symmetrically to "black" so a solid spot/process ink at
    full tint lands in the SAME "normal rich-black practice" bucket the
    existing frontend copy already has words for, instead of "white"."""
    joined = " ".join(colorant_names).lower()
    if "white" in joined:
        return "white"
    if "black" in joined:
        return "black"
    return "other"


MAX_FORM_XOBJECT_DEPTH = 10


def _get_resource_map(doc, container_xref, path, value_fn):
    """Resolve a Resources sub-dict (e.g. 'Resources/ExtGState') on any object
    (page or Form XObject) into {name: value_fn(xref_num)}. Returns {} if the
    sub-dict is absent, direct or indirect."""
    ref = doc.xref_get_key(container_xref, path)
    dict_str = None
    if ref[0] == "dict":
        dict_str = ref[1]
    elif ref[0] == "xref":
        target = int(ref[1].split()[0])
        dict_str = doc.xref_object(target)

    result = {}
    if dict_str:
        for name, xref_num in re.findall(r"/([A-Za-z0-9_]+)\s+(\d+)\s+\d+\s+R", dict_str):
            result[name] = value_fn(int(xref_num))
    return result


def _get_ext_gstate_map(doc, container_xref):
    def parse_gs(xref_num):
        gs_obj = doc.xref_object(xref_num)
        m_op = re.search(r"/op\b\s+(true|false)", gs_obj)
        m_OP = re.search(r"/OP\b\s+(true|false)", gs_obj)
        return {
            "op": (m_op.group(1) == "true") if m_op else None,
            "OP": (m_OP.group(1) == "true") if m_OP else None,
        }
    return _get_resource_map(doc, container_xref, "Resources/ExtGState", parse_gs)


def _get_xobject_map(doc, container_xref):
    return _get_resource_map(doc, container_xref, "Resources/XObject", lambda xref_num: xref_num)


def _parse_separation_or_devicen_names(obj_text):
    """`[/Separation <name> ...]` or `[/DeviceN [<names>] ...]` -> decoded
    colorant name list, or None if `obj_text` isn't one of those two array
    colorspaces. Shared by collect_spot_colors and _get_colorspace_map so
    there is exactly one place that knows this array shape."""
    stripped = obj_text.strip()
    m = re.match(r"^\[\s*/(Separation|DeviceN)\s+(.*)\]\s*$", stripped, re.S)
    if not m:
        return None
    kind, rest = m.group(1), m.group(2)
    if kind == "Separation":
        m2 = re.match(r"^/([^\s/\[\]]+)", rest)
        raw_names = [m2.group(1)] if m2 else []
    else:
        m2 = re.match(r"^\[\s*((?:/[^\s/\[\]]+\s*)+)\]", rest)
        raw_names = re.findall(r"/([^\s/\[\]]+)", m2.group(1)) if m2 else []
    return [_decode_pdf_name(n) for n in raw_names]


def _get_colorspace_map(doc, container_xref):
    """Resources/ColorSpace resolved to {name: colorant_names | None} —
    `colorant_names` is the decoded Separation/DeviceN name list for a
    special colorspace, `None` for anything else (DeviceGray/RGB/CMYK,
    ICCBased, Indexed, ...). Used by _scan_content_stream to know what a
    `cs`/`CS` operator actually selected, so a subsequent `scn`'s numeric
    tint is never misread as a DeviceGray/RGB/CMYK value (see the overprint
    white/black classification below)."""
    return _get_resource_map(
        doc, container_xref, "Resources/ColorSpace",
        lambda xref_num: _parse_separation_or_devicen_names(doc.xref_object(xref_num)),
    )


def _scan_content_stream(doc, container_xref, content_bytes, start_state, findings, visited,
                          parent_gs_map, parent_xobj_map, parent_cs_map=None):
    # A Form XObject inherits the page's/parent's Resources wholesale when it
    # doesn't define its own - resolved per sub-dict (gs/xobject) so a form that
    # only defines e.g. /XObject can still find /GS names from its parent.
    own_gs_map = _get_ext_gstate_map(doc, container_xref)
    gs_map = own_gs_map if own_gs_map else parent_gs_map
    own_xobj_map = _get_xobject_map(doc, container_xref)
    xobj_map = own_xobj_map if own_xobj_map else parent_xobj_map
    own_cs_map = _get_colorspace_map(doc, container_xref)
    cs_map = own_cs_map if own_cs_map else (parent_cs_map or {})

    contents = content_bytes.decode("latin-1", errors="ignore")
    tokens = TOKEN_RE.findall(contents)
    nums_buffer = []
    pending_name = None

    # Graphics state that q/Q push/pop as a unit. fill_color/stroke_color are
    # classifications of the *current* fill/stroke color (set by g/rg/k/sc/scn),
    # not the raw color values - that's enough to answer "is this white/black/other".
    # A Form XObject executes from the point of invocation (Do on a form is
    # effectively an implicit q/concat/execute/Q), so it starts from a *copy*
    # of the caller's state, not a blank one.
    state = dict(start_state)
    stack = []

    for t in tokens:
        if t.startswith("/"):
            pending_name = t[1:]
            continue
        if re.match(r"^-?\d*\.?\d+$", t):
            try:
                nums_buffer.append(float(t))
            except ValueError:
                pass
            continue

        if t == "q":
            stack.append(dict(state))
            nums_buffer, pending_name = [], None
            continue
        if t == "Q":
            if stack:
                state = stack.pop()
            nums_buffer, pending_name = [], None
            continue

        if t == "gs" and pending_name:
            flags = gs_map.get(pending_name)
            if flags:
                if flags["op"] is not None:
                    state["op_fill"] = flags["op"]
                if flags["OP"] is not None:
                    state["op_stroke"] = flags["OP"]
            nums_buffer, pending_name = [], None
            continue

        if t == "Tr":
            if nums_buffer:
                state["text_render_mode"] = int(nums_buffer[-1])
            nums_buffer, pending_name = [], None
            continue

        # `cs`/`CS` select the colorspace a FOLLOWING `scn`/`SC`'s numeric
        # operands are expressed in. Tracked so `scn`/`SC` below can tell a
        # Separation/DeviceN tint (1.0 = full ink) apart from a genuine
        # DeviceGray/RGB/CMYK value (1.0 = white) — previously not tracked
        # at all, which is what let a 100%-tint spot/process-named
        # colorant read as "white" (see _classify_separation_tint).
        if t == "cs" and pending_name:
            state["fill_cs_names"] = cs_map.get(pending_name)
            nums_buffer, pending_name = [], None
            continue
        if t == "CS" and pending_name:
            state["stroke_cs_names"] = cs_map.get(pending_name)
            nums_buffer, pending_name = [], None
            continue

        if t in ("g", "rg", "k"):
            state["fill_color"] = classify_fill_color(t, nums_buffer)
            # g/rg/k also implicitly select a DEVICE colorspace, overriding
            # whatever `cs` selected earlier in this q/Q scope.
            state["fill_cs_names"] = None
            nums_buffer, pending_name = [], None
            continue
        if t in ("G", "RG", "K"):
            state["stroke_color"] = classify_fill_color(t, nums_buffer)
            state["stroke_cs_names"] = None
            nums_buffer, pending_name = [], None
            continue
        if t in ("sc", "scn"):
            if pending_name:
                state["fill_color"] = "white" if "white" in pending_name.lower() else "other"
            elif state.get("fill_cs_names"):
                state["fill_color"] = _classify_separation_tint(state["fill_cs_names"])
            elif len(nums_buffer) == 4:
                state["fill_color"] = classify_fill_color("k", nums_buffer)
            elif len(nums_buffer) == 3:
                state["fill_color"] = classify_fill_color("rg", nums_buffer)
            elif len(nums_buffer) == 1:
                state["fill_color"] = classify_fill_color("g", nums_buffer)
            else:
                state["fill_color"] = "other"
            nums_buffer, pending_name = [], None
            continue
        if t in ("SC", "SCN"):
            if pending_name:
                state["stroke_color"] = "white" if "white" in pending_name.lower() else "other"
            elif state.get("stroke_cs_names"):
                state["stroke_color"] = _classify_separation_tint(state["stroke_cs_names"])
            elif len(nums_buffer) == 4:
                state["stroke_color"] = classify_fill_color("k", nums_buffer)
            elif len(nums_buffer) == 3:
                state["stroke_color"] = classify_fill_color("rg", nums_buffer)
            elif len(nums_buffer) == 1:
                state["stroke_color"] = classify_fill_color("g", nums_buffer)
            else:
                state["stroke_color"] = "other"
            nums_buffer, pending_name = [], None
            continue

        if t in FILL_OPS_ONLY:
            if state["op_fill"]:
                findings[state["fill_color"]] += 1
            nums_buffer, pending_name = [], None
            continue
        if t in STROKE_OPS_ONLY:
            if state["op_stroke"]:
                findings[state["stroke_color"]] += 1
            nums_buffer, pending_name = [], None
            continue
        if t in FILL_AND_STROKE_OPS:
            if state["op_fill"]:
                findings[state["fill_color"]] += 1
            if state["op_stroke"]:
                findings[state["stroke_color"]] += 1
            nums_buffer, pending_name = [], None
            continue

        if t in TEXT_PAINT_OPS:
            if state["text_render_mode"] in FILL_TEXT_RENDER_MODES and state["op_fill"]:
                findings[state["fill_color"]] += 1
            nums_buffer, pending_name = [], None
            continue

        if t == "Do" and pending_name:
            xobj_xref = xobj_map.get(pending_name)
            if xobj_xref is not None and len(visited) < MAX_FORM_XOBJECT_DEPTH and pending_name not in visited:
                subtype = doc.xref_get_key(xobj_xref, "Subtype")
                if subtype[1] == "/Form":
                    form_content = doc.xref_stream(xobj_xref) or b""
                    _scan_content_stream(
                        doc, xobj_xref, form_content, state, findings,
                        visited | {pending_name}, gs_map, xobj_map, cs_map,
                    )
                # /Image XObjects are handled separately (image checks), not here.
            nums_buffer, pending_name = [], None
            continue

        nums_buffer, pending_name = [], None


TRIM_MARK_MAX_LEN_PT = 20
TRIM_MARK_CORNER_RADIUS_PT = 40


def detect_trim_marks(page, trimbox):
    """Heuristic: a trim/crop mark is a short stroked tick sitting near one of
    the TrimBox's 4 corners, outside the trim area itself. There's no formal
    PDF object type for 'this is a crop mark' - this is a geometry guess, same
    spirit as the hairline-width heuristic above."""
    corners = [
        (trimbox.x0, trimbox.y0), (trimbox.x1, trimbox.y0),
        (trimbox.x0, trimbox.y1), (trimbox.x1, trimbox.y1),
    ]
    corners_with_marks = set()
    for drawing in page.get_drawings():
        if drawing.get("type") != "s":
            continue
        rect = drawing.get("rect")
        if rect is None:
            continue
        length = max(rect.width, rect.height)
        if length < 0.5 or length > TRIM_MARK_MAX_LEN_PT:
            continue
        if trimbox.contains(rect):
            continue  # inside the trim area - part of the artwork, not a crop mark
        cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
        for i, (cxp, cyp) in enumerate(corners):
            if abs(cx - cxp) <= TRIM_MARK_CORNER_RADIUS_PT and abs(cy - cyp) <= TRIM_MARK_CORNER_RADIUS_PT:
                corners_with_marks.add(i)
    return len(corners_with_marks) >= 2


def check_page_size_consistency(doc):
    first_mediabox = list(doc[0].mediabox)
    first_trimbox = list(doc[0].trimbox)
    inconsistent = []
    for i in range(1, len(doc)):
        p = doc[i]
        if list(p.mediabox) != first_mediabox or list(p.trimbox) != first_trimbox:
            inconsistent.append(i + 1)
    return inconsistent


def _decode_pdf_name(raw):
    return re.sub(r"#([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), raw)


def _normalize_cs_signature(text):
    text = re.sub(r"\d+\s+0\s+R", "REF", text)  # ignore which xref a tint function happens to be
    return re.sub(r"\s+", " ", text).strip()


# Standard process-ink names, same reserved-name treatment as "none"/"all"
# just below: some export tools re-expose each CMYK plate as its own named
# /Separation colorant (a "preseparated" PDF) so the very same 4 process
# inks appear TWICE — once as ordinary DeviceCMYK paint, once as a named
# plate a RIP can toggle. Reporting those 4 names in a "Spot Colors" list
# alongside genuine special inks (a real Pantone, a white, a varnish) reads
# as "N extra plates" to a non-expert user, when they're the same 4 process
# plates the job already needs. Real spot colors are unaffected: this only
# excludes an EXACT (case-insensitive) match on one of these four words.
PROCESS_COLOR_NAMES = {"cyan", "magenta", "yellow", "black"}


def collect_spot_colors(doc, page):
    cs_map = _get_resource_map(
        doc, page.xref, "Resources/ColorSpace",
        lambda xref_num: (xref_num, doc.xref_object(xref_num)),
    )
    entries = {}
    for xref_num, obj_text in cs_map.values():
        stripped = obj_text.strip()
        m = re.match(r"^\[\s*/(Separation|DeviceN)\s+(.*)\]\s*$", stripped, re.S)
        if not m:
            continue
        kind, rest = m.group(1), m.group(2)
        if kind == "Separation":
            m2 = re.match(r"^/([^\s/\[\]]+)", rest)
            names = [m2.group(1)] if m2 else []
        else:
            m2 = re.match(r"^\[\s*((?:/[^\s/\[\]]+\s*)+)\]", rest)
            names = re.findall(r"/([^\s/\[\]]+)", m2.group(1)) if m2 else []
        signature = _normalize_cs_signature(stripped)
        for raw_name in names:
            decoded = _decode_pdf_name(raw_name)
            if decoded.lower() in ("none", "all"):
                continue  # reserved PDF colorant names, not real spot colors
            if decoded.lower() in PROCESS_COLOR_NAMES:
                continue  # a process ink re-exposed as its own named plate, not a spot color
            entry = entries.setdefault(decoded, {"xrefs": set(), "signatures": set()})
            entry["xrefs"].add(xref_num)
            # Only a standalone /Separation carries its OWN tint definition
            # for this exact name — that is the one kind of occurrence that
            # can actually diagnose "same name, different color". A
            # /DeviceN's tint function is shared across EVERY name in its
            # member list (a common "preseparated" export bundles ALL
            # plates — process AND spot — into one combined DeviceN
            # alongside each plate's own standalone Separation), so
            # comparing that shared text as if it were this name's own
            # definition would flag every real spot in such a file as
            # conflicting against itself. Excluding DeviceN-sourced
            # signatures here keeps the genuine case working: two
            # DIFFERENT standalone /Separation objects for the same name
            # with different tint functions still disagree and still flag.
            if kind == "Separation":
                entry["signatures"].add(signature)

    return [
        {
            "name": name,
            "count": len(data["xrefs"]),
            "duplicate_conflict": len(data["signatures"]) > 1,
        }
        for name, data in entries.items()
    ]


DIELINE_KEYWORDS = {
    "cut": ["cut", "виріз", "різ"],
    "crease": ["crease", "score", "fold", "біговк", "біг", "згин", "фальц"],
    "glue": ["glue", "клей"],
    "die": ["die", "штанц"],
    "perforation": ["perf", "перфор"],
}


def detect_dieline_hints(doc, spot_colors):
    """Best-effort, informational only: real-world dieline files use no
    consistent naming convention for cut/crease/glue lines, so this just
    looks for common English/Ukrainian keywords in spot color and OCG layer
    names. A miss here says nothing about whether the file is correct."""
    candidates = [(sc["name"], "spot_color") for sc in spot_colors]
    for info in doc.get_ocgs().values():
        name = info.get("name")
        if name:
            candidates.append((name, "layer"))

    hints = {}
    for name, source in candidates:
        lower = name.lower()
        for category, keywords in DIELINE_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                bucket = hints.setdefault(category, set())
                bucket.add(name)
                break  # first matching category wins, avoid double-counting one name

    return [
        {"category": category, "names": sorted(names), "count": len(names)}
        for category, names in hints.items()
    ]


def check_pdfx_compliance(doc):
    pdfx_version = None
    info_ref = doc.xref_get_key(-1, "Info")
    if info_ref[0] == "xref":
        info_obj = doc.xref_object(int(info_ref[1].split()[0]))
        m = re.search(r"/GTS_PDFXVersion\s*\(([^)]*)\)", info_obj)
        if m:
            pdfx_version = m.group(1)

    has_output_intent = False
    has_icc_profile = False
    oi_ref = doc.xref_get_key(doc.pdf_catalog(), "OutputIntents")
    oi_array_text = None
    if oi_ref[0] == "array":
        oi_array_text = oi_ref[1]
    elif oi_ref[0] == "xref":
        oi_array_text = doc.xref_object(int(oi_ref[1].split()[0]))
    if oi_array_text:
        for xref_num in re.findall(r"(\d+)\s+0\s+R", oi_array_text):
            oi_obj = doc.xref_object(int(xref_num))
            if re.search(r"/S\s*/GTS_PDFX\b", oi_obj):
                has_output_intent = True
                if re.search(r"/DestOutputProfile\s+\d+\s+0\s+R", oi_obj):
                    has_icc_profile = True

    return {
        "is_pdfx": pdfx_version is not None,
        "version": pdfx_version,
        "has_output_intent": has_output_intent,
        "has_icc_profile": has_icc_profile,
    }


def analyze_overprint(doc, page):
    findings = {"white": 0, "black": 0, "other": 0}
    initial_state = {
        "fill_color": "other",
        "stroke_color": "other",
        "op_fill": False,
        "op_stroke": False,
        "text_render_mode": 0,
        "fill_cs_names": None,
        "stroke_cs_names": None,
    }
    _scan_content_stream(
        doc, page.xref, page.read_contents(), initial_state, findings,
        set(), {}, {}, {},
    )
    return findings


def _check_pdf_sync(
    pdf_bytes: bytes,
    filename: Optional[str],
    print_method: str,
    hairline_threshold: Optional[float],
    unit: str,
    bleed_threshold: Optional[float] = None,
    dpi_threshold: Optional[int] = None,
    product_id: Optional[str] = None,
    format_id: Optional[str] = None,
    include_canvas: bool = False,
    declared_width_mm: Optional[float] = None,
    declared_height_mm: Optional[float] = None,
):
    profile = PROFILES[print_method]
    if bleed_threshold is not None:
        effective_bleed_mm = bleed_threshold
    elif print_method == "unknown" and product_id in UNKNOWN_METHOD_BLEED_MM_BY_PRODUCT:
        effective_bleed_mm = UNKNOWN_METHOD_BLEED_MM_BY_PRODUCT[product_id]
    else:
        effective_bleed_mm = profile["bleed_mm"]
    effective_dpi_threshold = dpi_threshold if dpi_threshold is not None else profile["dpi_threshold"]

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if doc.needs_pass:
        raise EncryptedPDFError("PDF is password-protected")
    page = doc[0]
    mediabox = page.mediabox
    cropbox = page.cropbox
    trimbox = page.trimbox
    # Round 12 phase B item 8: pymupdf's page.trimbox/page.bleedbox properties
    # are convenience accessors that SILENTLY fall back to CropBox/MediaBox
    # when a PDF doesn't declare its own TrimBox/BleedBox — so `trimbox`
    # above is never actually able to tell the frontend "this PDF has no
    # real TrimBox". Reading the raw page dict key directly (xref_get_key)
    # is the only way to see whether the box was genuinely declared in the
    # PDF, needed for the honest "no declared BleedBox/TrimBox" Document
    # Geometry messaging — page 1 only, same scope as every other canvas-
    # adjacent field (no page-switcher to view another page's geometry).
    page1_has_declared_trimbox = doc.xref_get_key(page.xref, "TrimBox")[0] != "null"
    page1_has_declared_bleedbox = doc.xref_get_key(page.xref, "BleedBox")[0] != "null"

    if hairline_threshold is not None:
        hairline_threshold_pt = hairline_threshold * UNIT_TO_PT.get(unit, 2.8346)
        effective_hairline_mm = hairline_threshold_pt * (25.4 / 72)
    else:
        hairline_threshold_pt = profile["hairline_mm"] * MM_TO_PT
        effective_hairline_mm = profile["hairline_mm"]

    # --- Real per-page checks, aggregated across the whole document ---
    # Previously every check below only ever looked at doc[0] — a critical
    # problem (an RGB image, a missing bleed, unembedded fonts) on page 2+ of
    # a multi-page proof was silently never reported. Canvas rendering
    # (preview/heatmap/CMYK/spot separations) and pin-geometry annotations
    # stay page-1-only below (no page-switcher UI exists to view another
    # page's render), but every text/geometry check here now genuinely
    # inspects every page: worst-case severity, summed counts, or a union of
    # unique items, not just whatever page 1 happened to contain.
    fonts_by_name: dict[str, bool] = {}  # name -> embedded (False wins if unembedded on any page)
    image_rects_by_xref: dict[int, list] = {}
    image_base_by_xref: dict[int, dict] = {}
    thin_lines = 0
    # Additive alongside thin_lines_count (unchanged, kept for backward
    # compatibility): per-hairline page/rect/width, so a future UI can
    # locate/highlight them instead of only knowing a bare count exists.
    hairline_locations: list[dict] = []
    overprint_findings = {"white": 0, "black": 0, "other": 0}
    trim_marks_on_every_page = True
    spot_color_entries: dict[str, dict] = {}
    bleed_mm = None

    for p in doc:
        for font in p.get_fonts(full=True):
            name = font[3]
            embedded = font[1] not in ("", "n/a")
            fonts_by_name[name] = fonts_by_name.get(name, True) and embedded

        for img in p.get_images(full=True):
            xref = img[0]
            if xref not in image_base_by_xref:
                image_base_by_xref[xref] = doc.extract_image(xref)
            image_rects_by_xref.setdefault(xref, []).extend(p.get_image_rects(xref))

        for drawing in p.get_drawings():
            w = drawing.get("width")
            if w is not None and 0 < w < hairline_threshold_pt:
                thin_lines += 1
                rect = drawing.get("rect")
                hairline_locations.append({
                    "page": p.number + 1,  # 1-indexed, same convention as inconsistent_pages below
                    "rect": [rect.x0, rect.y0, rect.x1, rect.y1] if rect is not None else None,
                    "width_pt": w,
                })

        p_overprint = analyze_overprint(doc, p)
        for k in overprint_findings:
            overprint_findings[k] += p_overprint[k]

        if not detect_trim_marks(p, p.trimbox):
            trim_marks_on_every_page = False

        for sc in collect_spot_colors(doc, p):
            entry = spot_color_entries.setdefault(sc["name"], {"count": 0, "duplicate_conflict": False})
            entry["count"] += sc["count"]
            entry["duplicate_conflict"] = entry["duplicate_conflict"] or sc["duplicate_conflict"]

        p_mediabox, p_trimbox = p.mediabox, p.trimbox
        p_bleed_mm = (
            min(
                p_trimbox.x0 - p_mediabox.x0,
                p_mediabox.x1 - p_trimbox.x1,
                p_trimbox.y0 - p_mediabox.y0,
                p_mediabox.y1 - p_trimbox.y1,
            ) * (25.4 / 72)
            if list(p_mediabox) != list(p_trimbox) else 0.0
        )
        bleed_mm = p_bleed_mm if bleed_mm is None else min(bleed_mm, p_bleed_mm)

    fonts_info = [{"name": name, "embedded": embedded} for name, embedded in fonts_by_name.items()]

    images_info = []
    for xref, rects in image_rects_by_xref.items():
        base_image = image_base_by_xref[xref]
        colorspace = base_image.get("cs-name", "unknown")
        colorspace_n = base_image.get("colorspace")
        px_w = base_image.get("width", 0)
        px_h = base_image.get("height", 0)
        # The same image resource can be placed more than once, on the same
        # page or across different pages, at different sizes (e.g. a logo
        # used small in a corner and large elsewhere) — take the worst
        # (lowest) effective DPI across every placement, not just the
        # first one, so a bigger placement can't hide behind an earlier,
        # smaller one of the same image.
        dpi = None
        for rect in rects:
            width_in = rect.width / 72
            height_in = rect.height / 72
            if width_in > 0 and height_in > 0:
                placement_dpi = round(min(px_w / width_in, px_h / height_in))
                if dpi is None or placement_dpi < dpi:
                    dpi = placement_dpi
        images_info.append({
            "colorspace": colorspace,
            "rgb_warning": colorspace_n == 3,
            "width": base_image.get("width"),
            "height": base_image.get("height"),
            "dpi": dpi,
            "low_res_warning": dpi is not None and dpi < effective_dpi_threshold,
        })

    trim_marks_present = trim_marks_on_every_page
    inconsistent_pages = check_page_size_consistency(doc)
    spot_colors = [
        {"name": name, "count": data["count"], "duplicate_conflict": data["duplicate_conflict"]}
        for name, data in spot_color_entries.items()
    ]
    # Ghostscript spot-separation rendering below only ever rasterizes page
    # 1 — a spot color that exists only on page 2+ has nothing to show on
    # that render, so gate the (real, non-trivial) GS call on page 1's own
    # spot colors specifically, not the document-wide list above.
    page1_spot_colors = collect_spot_colors(doc, page)
    pdfx_compliance = check_pdfx_compliance(doc)
    dieline_hints = detect_dieline_hints(doc, spot_colors)

    # --- Tier 1 product/format + safe-zone + image-quality checks ---
    # Additive: none of the existing fields above are touched. product_id/
    # format_id are optional query params (unset -> checks return "info",
    # skipped) so old callers that never pass them are unaffected.
    tier1_trimbox_pt = get_trimbox_pt(page)
    tier1_text_items = get_text_items_pt(page)
    tier1_checks, tier1_status, effective_product_id, effective_format_id = run_tier1_product_checks(
        tier1_trimbox_pt, tier1_text_items, product_id, format_id, page=list(doc),
        has_real_trimbox=list(mediabox) != list(trimbox),
        declared_width_mm=declared_width_mm, declared_height_mm=declared_height_mm,
    )
    tier1_safe_zone = next(c for c in tier1_checks if c["check"] == "safe_zone")
    tier1_image_quality = next(c for c in tier1_checks if c["check"] == "image_quality")
    tier1_annotations = build_annotations(tier1_safe_zone, tier1_image_quality)

    # Canvas image renders (preview/heatmap/CMYK data) are the expensive part
    # (two full-page pixmap renders + PNG encoding). Only the new Next.js
    # frontend needs them, and it always sets include_canvas=true regardless
    # of whether a product is selected (Quick Check needs the canvas too);
    # the existing static frontend never sends it, so it never pays this cost.
    canvas_preview = None
    canvas_ink_heatmap = None
    canvas_cmyk_data = None
    canvas_spot_separations = None
    if include_canvas:
        canvas_preview = render_page_preview(page)
        canvas_cmyk_arr, _ = _cmyk_pixmap_array(page, DEFAULT_MAX_DIMENSION_PX)
        canvas_ink_heatmap = render_ink_heatmap(page, cmyk_arr=canvas_cmyk_arr)
        canvas_cmyk_data = render_cmyk_data_bitmap(page, cmyk_arr=canvas_cmyk_arr)
        # Ghostscript is real work — only run it when page 1 actually has a
        # named spot color to separate out.
        if page1_spot_colors:
            # Separation swatch fix (Audit #3 Finding #2, approved minimal
            # fix #1): the GS composite preview MVP already computes a
            # real, overprint-aware Ghostscript composite for spot-color
            # pages — compute it ONCE, here, before render_spot_separations,
            # and reuse its URL for BOTH the swatch-color sampling below AND
            # the base visual preview. Previously render_spot_separations
            # sampled the naive pymupdf preview (confirmed broken/flat for
            # real spot-heavy files — Audit #2/#3), which is why every spot
            # swatch came out nearly the same wrong color. This is a single
            # GS invocation, same as before this fix — just reordered so
            # its result is reused instead of recomputed. On any GS failure,
            # render_gs_composite_preview returns canvas_preview UNCHANGED
            # (the pymupdf url), so render_spot_separations below then gets
            # exactly the same input it always did in that fallback case —
            # no behavior change on failure, only on success.
            canvas_preview = render_gs_composite_preview(pdf_bytes, 0, canvas_preview)
            # Round 12 phase C: page_index=0 explicit (was implicit via the
            # old default-less signature) — also now genuinely restricts GS
            # to just this page instead of silently rendering every page's
            # separations and discarding all but page 1's.
            canvas_spot_separations = render_spot_separations(
                pdf_bytes, page, [sc["name"] for sc in page1_spot_colors], canvas_preview["url"], page_index=0,
            )

    result = {
        "filename": filename,
        "print_method": print_method,
        "page_count": len(doc),
        "mediabox": list(mediabox),
        "cropbox": list(cropbox),
        "trimbox": list(trimbox),
        "has_bleed": list(mediabox) != list(trimbox),
        "page1_has_declared_trimbox": page1_has_declared_trimbox,
        "page1_has_declared_bleedbox": page1_has_declared_bleedbox,
        "bleed_mm": round(bleed_mm, 2),
        "bleed_warning": bleed_mm < effective_bleed_mm - BLEED_TOLERANCE_MM,
        "fonts": fonts_info,
        "images": images_info,
        "unembedded_fonts_warning": any(not f["embedded"] for f in fonts_info),
        "thin_lines_count": thin_lines,
        "hairline_warning": thin_lines > 0,
        # Additive — does not replace thin_lines_count above. One entry per
        # detected hairline: {page (1-indexed), rect [x0,y0,x1,y1] in PDF
        # points, width_pt}. No clustering/deduplication yet (next step).
        "hairline_locations": hairline_locations,
        "thresholds_used": {
            "bleed_mm": effective_bleed_mm,
            "dpi_threshold": effective_dpi_threshold,
            "hairline_mm": round(effective_hairline_mm, 3),
            "hairline_unit": unit,
            "tac_limit_pct": profile["tac_limit_pct"],
        },
        "overprint_white_warning": overprint_findings["white"] > 0,
        "overprint_other_count": overprint_findings["other"],
        "overprint_black_count": overprint_findings["black"],
        "trim_marks_warning": not trim_marks_present,
        "page_size_consistency_warning": len(inconsistent_pages) > 0,
        "inconsistent_page_count": len(inconsistent_pages),
        "inconsistent_pages": inconsistent_pages[:20],
        "spot_colors": spot_colors,
        "spot_colors_conflict_warning": any(sc["duplicate_conflict"] for sc in spot_colors),
        "pdfx_compliance": pdfx_compliance,
        "dieline_hints": dieline_hints,
        # Round 12 phase E item 2: the EFFECTIVE ids (what was actually
        # checked against) — equal to the raw query params when given
        # explicitly, but the auto-matched ones when not, so the frontend's
        # auto-detect confirmation banner has something real to show
        # instead of echoing back None even when tier1_status is
        # "auto_trimbox"/"auto_declared".
        "product_id": effective_product_id,
        "format_id": effective_format_id,
        "tier1_checks": tier1_checks,
        "tier1_status": tier1_status,
        "annotations": tier1_annotations,
    }
    if include_canvas:
        result["preview"] = canvas_preview
        if canvas_ink_heatmap is not None:  # omitted entirely for a blank/near-blank page
            result["ink_heatmap"] = canvas_ink_heatmap
        result["cmyk_data"] = canvas_cmyk_data
        if canvas_spot_separations:  # omitted when there are no spot colors (or gs found nothing)
            result["spot_separations"] = canvas_spot_separations
    doc.close()
    return result


@app.get("/profiles")
async def get_profiles():
    return PROFILES


def _effective_printer_profile(printer: dict) -> dict:
    """Base PROFILES entry for the shop's print method with its overrides laid on top."""
    return {**PROFILES[printer["base_print_method"]], **printer["overrides"]}


@app.get("/printers/{slug}")
async def get_printer(slug: str):
    printer = PRINTER_PROFILES.get(slug)
    if printer is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "printer_not_found", "message": "Unknown print shop."},
        )
    return {
        "slug": slug,
        "name": printer["name"],
        "logo_url": printer["logo_url"],
        "base_print_method": printer["base_print_method"],
        "contact_note": printer["contact_note"],
        "profile": _effective_printer_profile(printer),
    }


@app.get("/products")
async def get_products():
    return products_catalog_response()


@app.get("/lut/cmyk-to-srgb")
async def get_cmyk_to_srgb_lut():
    """Round 6 phase G: the color-managed CMYK->sRGB LUT (see cmyk_lut.py)
    that replaced the canvas's naive channel-recompose formula. Identical
    for every file checked (it depends only on the FOGRA39 profile + grid
    size, never on the request), so this is a standalone, long-cacheable
    endpoint the frontend fetches once per session — not a field embedded
    in every /check response, which would repeat the same ~20KB for no
    reason on every single check.
    """
    data = get_lut_bytes()
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "public, max-age=31536000, immutable",
            "X-Lut-Grid-N": str(LUT_GRID_N),
        },
    )


class FeedbackPayload(BaseModel):
    message: str
    email: Optional[str] = None


@app.post("/api/feedback")
@limiter.limit("5/minute")
async def submit_feedback(request: Request, payload: FeedbackPayload):
    message = payload.message.strip()[:3500]
    if not message:
        raise HTTPException(
            status_code=400,
            detail={"code": "empty_message", "message": "Message is required."},
        )
    lines = ["BoxCheck Feedback", "", message]
    email = (payload.email or "").strip()
    if email:
        lines += ["", f"Reply to: {email}"]
    telegram_ok = send_telegram_message("\n".join(lines))
    send_to_google_sheets(message, email)
    if not telegram_ok:
        raise HTTPException(
            status_code=502,
            detail={"code": "telegram_failed", "message": "Failed to deliver feedback."},
        )
    return {"status": "ok"}


# --- "Виправте за мене" (fix-request) ---------------------------------------
# A visitor who sees critical issues in a report can leave a contact so we
# fix the layout for them. Same Telegram transport as /api/feedback (one bot,
# one chat), distinguished by a message prefix. Only session METADATA that the
# report already shows is accepted — never the PDF or any text extracted
# from it (the frontend sends check names, not their messages).
FIX_REQUEST_LIMIT = "5/hour"
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ID_LIKE = re.compile(r"^[A-Za-z0-9_.-]{1,60}$")


def _clean_text(value: Optional[str], max_len: int) -> str:
    return _CONTROL_CHARS.sub("", (value or "")).strip()[:max_len]


class FixRequestContext(BaseModel):
    product: Optional[str] = Field(default=None, max_length=60)
    printMethod: Optional[str] = Field(default=None, max_length=60)
    critical: int = Field(default=0, ge=0, le=9999)
    warning: int = Field(default=0, ge=0, le=9999)
    info: int = Field(default=0, ge=0, le=9999)
    # Names of the top critical checks (e.g. "Виліт (Bleed)"), NOT their
    # messages — those can quote text from the customer's file.
    findings: list[str] = Field(default_factory=list, max_length=3)


class FixRequestPayload(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    contact: str = Field(max_length=200)
    note: Optional[str] = Field(default=None, max_length=2000)
    # Honeypot: hidden in the form, so only bots fill it in.
    website: Optional[str] = Field(default=None, max_length=500)
    context: FixRequestContext = Field(default_factory=FixRequestContext)


def _format_fix_request(payload: FixRequestPayload) -> str:
    ctx = payload.context
    name = _clean_text(payload.name, 100)
    note = _clean_text(payload.note, 500)
    product = ctx.product if ctx.product and _ID_LIKE.match(ctx.product) else None
    method = ctx.printMethod if ctx.printMethod and _ID_LIKE.match(ctx.printMethod) else None
    findings = [f for f in (_clean_text(f, 80) for f in ctx.findings) if f]
    lines = [
        "🔧 ЗАЯВКА: Виправте за мене",
        "",
        f"Ім'я: {name or '—'}",
        f"Контакт: {_clean_text(payload.contact, 120)}",
        f"Продукт: {product or '—'} · Метод друку: {method or '—'}",
        f"Знайдено: критичних {ctx.critical} · попереджень {ctx.warning} · info {ctx.info}",
    ]
    if findings:
        lines.append("Критичні проблеми:")
        lines += [f"  {i}. {f}" for i, f in enumerate(findings, 1)]
    if note:
        lines += ["", f"Нотатка: {note}"]
    lines += ["", f"Час: {datetime.now(ZoneInfo('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M')} (Київ)"]
    return "\n".join(lines)


@app.post("/fix-request")
@limiter.limit(FIX_REQUEST_LIMIT)
async def submit_fix_request(request: Request, payload: FixRequestPayload):
    if (payload.website or "").strip():
        # Honeypot tripped: pretend success so the bot learns nothing, and
        # deliver nothing. Nothing from the payload is logged.
        logger.info("fix-request honeypot triggered; dropped silently")
        return {"status": "ok"}
    if len(_clean_text(payload.contact, 120)) < 3:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_contact", "message": "A contact (Telegram username or phone) is required."},
        )
    if not send_telegram_message(_format_fix_request(payload)):
        raise HTTPException(
            status_code=502,
            detail={"code": "telegram_failed", "message": "Failed to deliver the request."},
        )
    logger.info("fix-request delivered")
    return {"status": "ok"}


@app.get("/fix-request/config")
async def get_fix_request_config():
    """Payment details shown on /fix after a request is submitted. Read from
    the environment on every call (systemd EnvironmentFile) — never
    hardcoded, never sent by the frontend. Not a secret: it's what the
    customer is asked to pay to."""
    return Response(
        content=json.dumps(
            {
                "cardNumber": os.environ.get("FIX_SERVICE_CARD_NUMBER", "").strip(),
                "cardName": os.environ.get("FIX_SERVICE_CARD_NAME", "").strip(),
            },
            ensure_ascii=False,
        ),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


def _fix_bleed_sync(
    pdf_bytes: bytes,
    print_method: str,
    bleed_threshold: Optional[float],
    product_id: Optional[str],
) -> dict:
    # Same effective-threshold logic /check uses (profile default, "unknown"
    # product-category override, explicit bleed_threshold override) — the
    # fix must target the exact same number the check flagged, or a "fixed"
    # file could still fail the same check.
    profile = PROFILES[print_method]
    if bleed_threshold is not None:
        target_bleed_mm = bleed_threshold
    elif print_method == "unknown" and product_id in UNKNOWN_METHOD_BLEED_MM_BY_PRODUCT:
        target_bleed_mm = UNKNOWN_METHOD_BLEED_MM_BY_PRODUCT[product_id]
    else:
        target_bleed_mm = profile["bleed_mm"]

    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if doc.needs_pass:
        raise EncryptedPDFError("PDF is password-protected")

    result = fix_bleed_pdf(doc, 0, target_bleed_mm)
    doc.close()
    return {
        "pdf_base64": base64.b64encode(result["pdf_bytes"]).decode("ascii"),
        "preview": result["preview"],
        "edges_mm": result["edges_mm"],
        "target_bleed_mm": target_bleed_mm,
    }


@app.post("/fix/bleed")
@limiter.limit("10/minute")
async def fix_bleed(
    request: Request,
    file: UploadFile = File(...),
    print_method: Literal["carton", "label", "flexible", "digital", "offset", "unknown"] = "unknown",
    bleed_threshold: Optional[float] = None,
    product_id: Optional[str] = None,
):
    """N16: opt-in bleed auto-fix. Explicit click only — never runs as part
    of /check. Returns the fixed PDF bytes (base64) and an edge preview in
    one response (deterministic geometry, computed once); the frontend's
    "Download" button just saves the bytes already returned here, no
    second request."""
    pdf_bytes = await file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(pdf_bytes) > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail={"code": "file_too_large", "message": f"File too large, max {max_mb}MB.", "max_mb": max_mb},
        )

    try:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None, _fix_bleed_sync, pdf_bytes, print_method, bleed_threshold, product_id,
            ),
            timeout=PROCESSING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "timeout",
                "message": f"Bleed fix timed out after {PROCESSING_TIMEOUT_SECONDS}s.",
                "timeout_s": PROCESSING_TIMEOUT_SECONDS,
            },
        )
    except pymupdf.FileDataError:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pdf", "message": "File is not a valid or readable PDF."},
        )
    except EncryptedPDFError:
        raise HTTPException(
            status_code=422,
            detail={"code": "encrypted_pdf", "message": "PDF is password-protected."},
        )
    except NoDeclaredTrimBoxError:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_trimbox",
                "message": "PDF has no declared TrimBox — cannot compute how much bleed to add.",
            },
        )


def _render_page_sync(
    pdf_bytes: bytes,
    page_index: int,
    print_method: str,
    product_id: Optional[str],
    format_id: Optional[str],
    dpi_threshold: Optional[int],
) -> dict:
    """Round 12 phase C: lazy per-page render for the page switcher.

    Deliberately NOT a full re-run of every check — fonts/hairlines/
    overprint/bleed-across-all-pages/etc. were already computed once by the
    initial /check call across the WHOLE document and don't change
    depending on which page is currently being viewed, so re-running them
    here on every Next/Previous click would be pure waste. Only recomputes
    what's genuinely page-specific:
    - the canvas image renders themselves (preview/heatmap/cmyk/spot
      separations) — these are the whole reason this endpoint exists, since
      main.py used to only ever render page 1 (see this phase's own
      "Крок 1" investigation, recorded in PROGRESS.md);
    - safe_zone and image_quality, the only two Tier 1 checks with real
      per-page location data (everything else aggregates to one
      document-wide value with no natural single-page severity) — needed
      both for this page's own canvas pins and for a per-page
      critical/warning/ok summary. product_format_match is NOT re-run here:
      it's a whole-document "does the file match a catalog size" check,
      not something that varies by which page is on screen.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if doc.needs_pass:
        raise EncryptedPDFError("PDF is password-protected")
    if page_index < 0 or page_index >= len(doc):
        raise IndexError(f"page_index {page_index} is out of range for a {len(doc)}-page document")
    page = doc[page_index]

    profile = PROFILES[print_method]
    effective_dpi_threshold = dpi_threshold if dpi_threshold is not None else profile["dpi_threshold"]

    mediabox = page.mediabox
    trimbox_pt = get_trimbox_pt(page)
    page_has_declared_trimbox = doc.xref_get_key(page.xref, "TrimBox")[0] != "null"
    page_has_declared_bleedbox = doc.xref_get_key(page.xref, "BleedBox")[0] != "null"
    text_items = get_text_items_pt(page)
    safe_zone_result = check_safe_zone(trimbox_pt, text_items, product_id)
    image_quality_result = check_image_quality(page, dpi_threshold=effective_dpi_threshold)
    annotations = build_annotations(safe_zone_result, image_quality_result)

    severities = {safe_zone_result["severity"], image_quality_result["severity"]}
    if "critical" in severities:
        page_severity = "critical"
    elif "warning" in severities:
        page_severity = "warning"
    else:
        page_severity = "ok"

    canvas_preview = render_page_preview(page)
    cmyk_arr, _ = _cmyk_pixmap_array(page, DEFAULT_MAX_DIMENSION_PX)
    ink_heatmap = render_ink_heatmap(page, cmyk_arr=cmyk_arr)
    cmyk_data = render_cmyk_data_bitmap(page, cmyk_arr=cmyk_arr)

    page_spot_colors = collect_spot_colors(doc, page)
    spot_separations = []
    if page_spot_colors:
        # Separation swatch fix — same reasoning/ordering as
        # _check_pdf_sync's own integration point (see there for the full
        # comment): compute the GS composite ONCE here, reuse its URL for
        # both the swatch-color sampling below and the base visual preview.
        canvas_preview = render_gs_composite_preview(pdf_bytes, page_index, canvas_preview)
        spot_separations = render_spot_separations(
            pdf_bytes, page, [sc["name"] for sc in page_spot_colors], canvas_preview["url"], page_index=page_index,
        )

    safe_zone_details = safe_zone_result.get("details") or {}
    page_geometry = {
        "media_box_pt": list(mediabox),
        "trim_box_pt": list(trimbox_pt),
        "bleed_box_pt": list(mediabox) if list(mediabox) != list(trimbox_pt) else None,
        "safe_zone_margin_mm": safe_zone_details.get("required_safe_zone_mm"),
        "safe_zone_violations": safe_zone_details.get("violations", []),
        "has_declared_trimbox": page_has_declared_trimbox,
        "has_declared_bleedbox": page_has_declared_bleedbox,
    }

    result = {
        "page_index": page_index,
        "page_count": len(doc),
        "page_severity": page_severity,
        "preview": canvas_preview,
        "cmyk_data": cmyk_data,
        "annotations": annotations,
        "page_geometry": page_geometry,
    }
    if ink_heatmap is not None:
        result["ink_heatmap"] = ink_heatmap
    if spot_separations:
        result["spot_separations"] = spot_separations
    return result


def _render_ink_preview_sync(
    pdf_bytes: bytes,
    page_index: int,
    excluded_spots: Optional[list[str]],
    excluded_processes: Optional[list[str]] = None,
    probe_x: Optional[int] = None,
    probe_y: Optional[int] = None,
) -> dict:
    """Ink Manager preview for one page: the pdfcer wrapper's render with the
    requested named spot colorants and process channels left out, normalized
    to the existing preview grid.

    Returns the SAME shape as render_page_preview()'s own output
    ({url, width_px, height_px, scale}) so it drops straight into the caller's
    `preview` slot: the image is the wrapper's PNG resized to exactly
    preview.width_px/height_px, and `scale` is passed through unchanged because
    that resize preserves the px-per-PDF-point grid that every overlay rect,
    pin and hover readout is already placed with.

    Deliberately NOT folded into _render_page_sync: that is the per-page
    NAVIGATION path (one call per page switch, re-running every canvas layer),
    while this is a per-TOGGLE re-render producing one image. Merging them
    would make every page switch pay for a wrapper invocation it does not need.

    NEVER raises past this boundary for a wrapper-side problem: non-zero exit,
    missing/empty/unreadable output, timeout, even a missing binary — all log
    and return the page's existing all-on preview UNCHANGED, the same
    resilience contract gs_composite_preview.render_gs_composite_preview
    already established for the sibling GS composite, so a caller always gets a
    renderable page rather than a broken canvas. Only PDF-level faults
    (encrypted, bad index, unreadable file) propagate, so the endpoint can
    answer those with the same 4xx codes /check/page uses.

    The wrapper is invoked ONLY when at least one spot or process channel is
    actually excluded: with nothing excluded its output would be the all-on
    image the caller already holds, at the cost of a full page rasterization.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if doc.needs_pass:
        raise EncryptedPDFError("PDF is password-protected")
    if page_index < 0 or page_index >= len(doc):
        raise IndexError(f"page_index {page_index} is out of range for a {len(doc)}-page document")
    page = doc[page_index]
    # The authority on the grid: cmyk_data, ink_heatmap and spot_separations
    # all share this exact dimension/scale pair, which is what makes the
    # resize below a normalization rather than a change of geometry.
    preview = render_page_preview(page)
    doc.close()

    spot_names = [name for name in (excluded_spots or []) if name and name.strip()]
    process_channels = [ch for ch in (excluded_processes or []) if ch]
    probe_requested = probe_x is not None or probe_y is not None
    if not spot_names and not process_channels and not probe_requested:
        return preview

    probe_json: Optional[dict] = None

    def _parse_ink_probe_stdout(stdout_text: str) -> Optional[dict]:
        # The wrapper prints EXACTLY one JSON probe line on stdout when
        # --probe-ink is supplied. Parse only a line that looks like that
        # probe object; never expose arbitrary stdout.
        for line in stdout_text.splitlines():
            line = line.strip()
            if not line.startswith("{") or '"ink_probe"' in line:
                continue
            if '"x"' not in line or '"y"' not in line or '"source"' not in line:
                continue
            try:
                candidate = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(candidate, dict):
                continue
            if not isinstance(candidate.get("x"), int):
                continue
            if not isinstance(candidate.get("y"), int):
                continue
            if not isinstance(candidate.get("source"), str):
                continue
            return candidate
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="boxcheck-ink-manager-") as tmpdir:
            tmp = Path(tmpdir)
            # The wrapper takes a PATH and this project persists nothing, so
            # the upload goes into a tempdir file that dies with the block —
            # the same pattern spot_separations.py and gs_composite_preview.py
            # already use for their own GS invocations.
            input_pdf = tmp / "input.pdf"
            output_file = tmp / "preview.png"
            input_pdf.write_bytes(pdf_bytes)

            cmd = [INK_MANAGER_BIN, str(input_pdf), str(output_file), "--page", str(page_index)]
            for name in spot_names:
                cmd += ["--exclude-spot", name]
            for channel in process_channels:
                cmd += ["--exclude-process", channel]
            if probe_requested:
                cmd += ["--probe-ink", f"{probe_x},{probe_y}"]

            proc = subprocess.run(cmd, capture_output=True, timeout=INK_MANAGER_TIMEOUT_SECONDS)
            if proc.returncode != 0:
                logger.warning(
                    "ink manager: non-zero exit (rc=%s) for page_index=%d: %s",
                    proc.returncode, page_index, proc.stderr.decode("utf-8", "ignore")[:500],
                )
                return preview

            if not output_file.exists() or output_file.stat().st_size == 0:
                logger.warning(
                    "ink manager: no/empty output file for page_index=%d. stderr: %s",
                    page_index, proc.stderr.decode("utf-8", "ignore")[:500],
                )
                return preview

            try:
                with Image.open(output_file) as im:
                    if im.width <= 0 or im.height <= 0:
                        logger.warning(
                            "ink manager: unexpected dimensions %sx%s for page_index=%d",
                            im.width, im.height, page_index,
                        )
                        return preview
                    rgb = im.convert("RGB")
            except Exception:
                logger.warning(
                    "ink manager: output for page_index=%d is not a readable image",
                    page_index, exc_info=True,
                )
                return preview

            # ★ The wrapper renders at ITS fixed 100 DPI — 2831x2242 for a
            # 2038pt-long page — while this project's canvas grid is bounded by
            # DEFAULT_MAX_DIMENSION_PX (1400x1109 for that same page). Resizing
            # here, exactly as render_gs_composite_preview does for the GS
            # composite, is what keeps pins, rects and the hover readout
            # aligned; returning the raw 100 DPI image would silently misplace
            # every overlay drawn on top of it.
            target_size = (preview["width_px"], preview["height_px"])
            if rgb.size != target_size:
                rgb = rgb.resize(target_size, Image.LANCZOS)
            buf = io.BytesIO()
            rgb.save(buf, format="PNG", optimize=True)
            data_uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")

            result = {
                "url": data_uri,
                "width_px": preview["width_px"],
                "height_px": preview["height_px"],
                "scale": preview["scale"],
            }
            if probe_requested:
                # Same render's ink probe, parsed from the wrapper's one JSON
                # line. Malformed/missing probe output never breaks the
                # preview: the field is simply omitted (fallback preserved).
                probe_json = _parse_ink_probe_stdout(proc.stdout.decode("utf-8", "ignore"))
                if probe_json is not None:
                    result["ink_probe"] = probe_json
            return result
    except subprocess.TimeoutExpired:
        logger.warning(
            "ink manager: timed out after %ss for page_index=%d",
            INK_MANAGER_TIMEOUT_SECONDS, page_index,
        )
        return preview
    except Exception:
        logger.exception("ink manager: unexpected failure for page_index=%d", page_index)
        return preview


@app.post("/check/page")
@limiter.limit("20/minute")
async def check_page(
    request: Request,
    file: UploadFile = File(...),
    page_index: int = 0,
    print_method: Literal["carton", "label", "flexible", "digital", "offset", "unknown"] = "unknown",
    product_id: Optional[str] = None,
    format_id: Optional[str] = None,
    dpi_threshold: Optional[int] = None,
):
    pdf_bytes = await file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(pdf_bytes) > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail={"code": "file_too_large", "message": f"File too large, max {max_mb}MB.", "max_mb": max_mb},
        )

    try:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None, _render_page_sync, pdf_bytes, page_index, print_method, product_id, format_id, dpi_threshold,
            ),
            timeout=PROCESSING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "timeout",
                "message": f"Page render timed out after {PROCESSING_TIMEOUT_SECONDS}s.",
                "timeout_s": PROCESSING_TIMEOUT_SECONDS,
            },
        )
    except pymupdf.FileDataError:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pdf", "message": "File is not a valid or readable PDF."},
        )
    except EncryptedPDFError:
        raise HTTPException(
            status_code=422,
            detail={"code": "encrypted_pdf", "message": "PDF is password-protected."},
        )
    except IndexError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_page_index", "message": str(e)},
        )


@app.post("/check/ink-preview")
@limiter.limit("20/minute")
async def check_ink_preview(
    request: Request,
    file: UploadFile = File(...),
    page_index: int = 0,
    exclude_spot: list[str] = Query(default=[]),
    exclude_process: list[str] = Query(default=[]),
    probe_x: Optional[int] = Query(default=None),
    probe_y: Optional[int] = Query(default=None),
):
    """Ink Manager preview: this page rasterized by the pdfcer wrapper with the
    requested spot colorants and process channels switched off.

    A separate endpoint from /check/page on purpose. /check/page is the
    per-page NAVIGATION path — one call per page switch, re-running every
    canvas layer (preview, cmyk_data, ink_heatmap, spot_separations) plus
    safe_zone/image_quality — whereas this is a per-TOGGLE re-render that
    produces exactly one image and nothing else. Folding it into /check/page
    would make every page switch pay for a wrapper invocation it does not need,
    and would put a toggled render inside the response the rest of the canvas
    already depends on (which must stay untouched).

    `exclude_spot` is a REPEATABLE query parameter, e.g.
    `?page_index=0&exclude_spot=White-1&exclude_spot=PANTONE%203262%20C`,
    matched by the wrapper against the PDF's own colorant-name bytes — the
    exact names `spot_separations`/`collect_spot_colors` already report.

    `exclude_process` is likewise REPEATABLE (`?exclude_process=K`) and
    accepts only the process channels C, M, Y, K; anything else is rejected
    with 422 before the upload is even read.

    `probe_x`/`probe_y` are an OPTIONAL device-pixel coordinate (origin
    top-left, same space the wrapper's `--probe-ink X,Y` takes). Either both
    or neither must be supplied — one without the other is 422 — and when
    both are present the SAME wrapper render also yields `ink_probe` in the
    response, additively. When absent the response shape is unchanged.

    With NO exclusions requested, or on any wrapper-side failure/timeout, the
    response is the page's existing all-on preview (see
    _render_ink_preview_sync), so the caller always receives a renderable
    image: this endpoint can never leave the canvas without a base layer.
    """
    if (probe_x is None) != (probe_y is None):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "incomplete_probe_coordinate",
                "message": "probe_x and probe_y must be supplied together; got only one.",
            },
        )
    if probe_x is not None and probe_x < 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_probe_coordinate",
                "message": "probe_x must be a non-negative device-pixel coordinate.",
            },
        )
    if probe_y is not None and probe_y < 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_probe_coordinate",
                "message": "probe_y must be a non-negative device-pixel coordinate.",
            },
        )
    invalid_processes = [ch for ch in exclude_process if ch not in ("C", "M", "Y", "K")]
    if invalid_processes:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_process_channel",
                "message": "exclude_process accepts only C, M, Y, K; got: "
                + ", ".join(sorted(set(invalid_processes))),
            },
        )

    pdf_bytes = await file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(pdf_bytes) > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail={"code": "file_too_large", "message": f"File too large, max {max_mb}MB.", "max_mb": max_mb},
        )

    try:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None, _render_ink_preview_sync, pdf_bytes, page_index, exclude_spot, exclude_process,
                probe_x, probe_y,
            ),
            timeout=PROCESSING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "timeout",
                "message": f"Ink preview timed out after {PROCESSING_TIMEOUT_SECONDS}s.",
                "timeout_s": PROCESSING_TIMEOUT_SECONDS,
            },
        )
    except pymupdf.FileDataError:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pdf", "message": "File is not a valid or readable PDF."},
        )
    except EncryptedPDFError:
        raise HTTPException(
            status_code=422,
            detail={"code": "encrypted_pdf", "message": "PDF is password-protected."},
        )
    except IndexError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_page_index", "message": str(e)},
        )
    except IndexError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_page_index", "message": str(e)},
        )


# --- Ink Coverage Analyzer (v1) -------------------------------------------
# On-demand, separate from /check: the whole analysis runs in an isolated
# worker process (ink_runner.py / ink_worker.py); this handler only validates
# the request and maps failures to the existing {detail:{code,message}} shape.
_INK_PAGES_RE = re.compile(r"^\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*$")


def _parse_ink_pages(spec: Optional[str]) -> Optional[list[int]]:
    if spec is None or not spec.strip():
        return None
    if len(spec) > 200 or not _INK_PAGES_RE.match(spec):
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_pages", "message": "pages must look like 1,3-5."},
        )
    out: list[int] = []
    for part in spec.split(","):
        a, _, b = part.partition("-")
        lo = int(a)
        hi = int(b) if b.strip() else lo
        if hi < lo or hi - lo > 10_000:
            raise HTTPException(
                status_code=400,
                detail={"code": "invalid_pages", "message": "pages must look like 1,3-5."},
            )
        out.extend(range(lo, hi + 1))
        if len(out) > 10_000:
            break
    return out[:10_000]


# boxcheck-ink-* dirs left behind by a SIGKILLed or restarted API (service
# start = import time; only dirs older than an hour are touched)
try:
    sweep_stale_tempdirs()
except Exception:
    logger.exception("ink temp-dir sweep failed")


@app.post("/check/ink-coverage")
@limiter.limit("6/minute")
async def check_ink_coverage(
    request: Request,
    file: UploadFile = File(...),
    pages: Optional[str] = Form(None),
):
    pdf_bytes = await file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(pdf_bytes) > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail={"code": "file_too_large", "message": f"File too large, max {max_mb}MB.", "max_mb": max_mb},
        )
    if b"%PDF" not in pdf_bytes[:1024]:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pdf", "message": "File is not a valid or readable PDF."},
        )
    page_list = _parse_ink_pages(pages)

    try:
        return await run_ink_analysis(pdf_bytes, page_list)
    except InkBusy as e:
        raise HTTPException(
            status_code=503,
            detail={"code": "busy", "message": "Ink coverage analysis is busy, try again shortly."},
            headers={"Retry-After": str(e.retry_after)},
        )
    except InkTimeout:
        raise HTTPException(
            status_code=504,
            detail={"code": "timeout", "message": "Ink coverage analysis timed out."},
        )
    except InkWorkerCrash:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pdf", "message": "File is not a valid or readable PDF."},
        )
    except InkError as e:
        status = 413 if e.code == "file_too_large" else (400 if e.code == "invalid_pages" else 422)
        raise HTTPException(status_code=status, detail={"code": e.code, "message": e.message})


_BCPLANE_MAGIC = b"BCPLANE2"
_BCPLANE_HEADER = struct.Struct("<8s10I")
# BCPLANE2 flags, mirroring the exporter: bit0 gzipped container (never set
# here — the endpoint gzips the transport, the container stays raw), bit1
# dtype (0 = u8 tints), bit2 polarity (0 = subtractive: 0 = no ink, 255 =
# full ink), bit3 spot-LUT region present (additive extension, opt-in at
# the exporter via `--with-spot-luts`; /check/page-planes does not pass
# that flag today, so production containers still carry flags == 0).
_BCPLANE_FLAG_SPOT_LUTS = 1 << 3
_BCPLANE_FLAGS_ACCEPTED = frozenset({0, _BCPLANE_FLAG_SPOT_LUTS})
# Plane kinds from the container's own directory spec.
_BCPLANE_KIND_SPOT = 4
_BCPLANE_KIND_ALPHA = 5
# Per-spot LUT shape: SPOT_LUT_SAMPLE_COUNT (256) samples of (r, g, b) f32
# LE each — mirrors `pdfcer_render::SPOT_LUT_SAMPLE_COUNT` and the exact
# `SpotLut` table `fold_spots_srgb`/`fold_spots_srgb_excluding` index into.
_BCPLANE_LUT_SAMPLE_COUNT = 256
_BCPLANE_LUT_BYTES_PER_SPOT = _BCPLANE_LUT_SAMPLE_COUNT * 3 * 4
_BCPLANE_LUT_SAMPLE_STRUCT = struct.Struct(f"<{_BCPLANE_LUT_SAMPLE_COUNT * 3}f")


def parse_bplane2(data: bytes) -> dict:
    """Parse and fully validate a BCPLANE2 container into per-plane bytes.

    Strict on purpose: this is a data contract the browser will recompose
    from, so anything unexpected — wrong magic/version/flags, truncated
    file, plane lengths that do not match width×height, a bad CRC — is an
    error, not a best-effort read. Raises ValueError with a stable message
    on every rejection.
    """
    if len(data) < _BCPLANE_HEADER.size:
        raise ValueError("truncated BCPLANE2 header")
    (magic, version, flags, width, height, dpi_x100, intent,
     plane_count, spots_flattened, crc, dir_entries) = _BCPLANE_HEADER.unpack_from(data, 0)
    if magic != _BCPLANE_MAGIC:
        raise ValueError("not a BCPLANE2 container")
    if version != 2:
        raise ValueError(f"unsupported BCPLANE2 version {version}")
    if flags not in _BCPLANE_FLAGS_ACCEPTED:
        raise ValueError(f"unsupported BCPLANE2 flags {flags}")
    if width <= 0 or height <= 0:
        raise ValueError("invalid BCPLANE2 dimensions")
    if plane_count < 5 or plane_count != dir_entries:
        raise ValueError("BCPLANE2 plane/directory count mismatch")
    samples = width * height
    # 5 named planes minimum (C M Y K + alpha); refuse absurd payloads before
    # allocating (the directory must also physically fit in the file).
    if samples * plane_count > PLANES_MAX_DECOMPRESSED_BYTES:
        raise ValueError("BCPLANE2 payload exceeds the size ceiling")

    # Directory: one u8 kind per entry; spot entries carry a u32 length +
    # UTF-8 name. Directory order defines plane order in the region.
    offset = _BCPLANE_HEADER.size
    kinds: list[int] = []
    spot_names: list[str] = []
    try:
        for entry in range(dir_entries):
            kind = data[offset]
            offset += 1
            name = None
            if kind == _BCPLANE_KIND_SPOT:
                (name_len,) = struct.unpack_from("<I", data, offset)
                offset += 4
                name = data[offset:offset + name_len].decode("utf-8")
                offset += name_len
            elif kind > _BCPLANE_KIND_ALPHA:
                raise ValueError(f"unknown BCPLANE2 plane kind {kind}")
            kinds.append(kind)
            if name is not None:
                spot_names.append(name)
    except (IndexError, struct.error, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed BCPLANE2 directory: {exc}") from exc

    plane_region = data[offset:offset + samples * plane_count]
    if len(plane_region) != samples * plane_count:
        raise ValueError("truncated BCPLANE2 plane region")
    if (zlib.crc32(plane_region) & 0xFFFFFFFF) != crc:
        raise ValueError("BCPLANE2 CRC32 mismatch")
    offset += samples * plane_count

    # Optional spot-LUT region (flags bit3): per spot, in the SAME roster
    # order as spot_names, the exact 256-sample sRGB table
    # `fold_spots_srgb`/`fold_spots_srgb_excluding` indexed into for this
    # render. Strict: the region's own CRC and its exact expected length
    # (spot_count * 256 * 3 * 4 bytes, nothing more, nothing less) are both
    # checked — a truncated or padded LUT region is a hard error, not a
    # best-effort read, matching the discipline this function already
    # applies to the plane region above.
    spot_luts: list[list[tuple[float, float, float]]] | None = None
    if flags & _BCPLANE_FLAG_SPOT_LUTS:
        if len(data) < offset + 4:
            raise ValueError("truncated BCPLANE2 spot-LUT CRC")
        (lut_crc,) = struct.unpack_from("<I", data, offset)
        offset += 4
        lut_region_len = len(spot_names) * _BCPLANE_LUT_BYTES_PER_SPOT
        lut_region = data[offset:offset + lut_region_len]
        if len(lut_region) != lut_region_len:
            raise ValueError("truncated BCPLANE2 spot-LUT region")
        if (zlib.crc32(lut_region) & 0xFFFFFFFF) != lut_crc:
            raise ValueError("BCPLANE2 spot-LUT CRC32 mismatch")
        offset += lut_region_len
        spot_luts = []
        for i in range(len(spot_names)):
            flat = _BCPLANE_LUT_SAMPLE_STRUCT.unpack_from(
                lut_region, i * _BCPLANE_LUT_BYTES_PER_SPOT
            )
            spot_luts.append(list(zip(flat[0::3], flat[1::3], flat[2::3])))
    if len(data) != offset:
        raise ValueError("trailing bytes after BCPLANE2 container")

    planes = [plane_region[i * samples:(i + 1) * samples] for i in range(plane_count)]
    return {
        "version": version,
        "flags": flags,
        "width": width,
        "height": height,
        "dpi_x100": dpi_x100,
        "intent": intent,
        "spots_flattened": spots_flattened,
        "kinds": kinds,
        "spot_names": spot_names,
        "planes": planes,
        "spot_luts": spot_luts,
        "crc32": crc,
    }


def _render_page_planes_sync(pdf_bytes: bytes, page_index: int) -> bytes:
    """One page through the BCPLANE2 exporter: the authoritative N-channel
    CmykBuffer retained BEFORE the sRGB collapse, written as the BCPLANE2
    container. Returns the RAW container bytes (gzip happens at the
    transport boundary so Content-Encoding stays a response concern).

    Unlike the Ink Manager preview this is NOT a fallback path: a caller
    asking for planes asked for THE plane export, so failures surface as
    typed exceptions the endpoint maps to 4xx/502 rather than silently
    degrading to an image the caller did not request.
    """
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if doc.needs_pass:
        raise EncryptedPDFError("PDF is password-protected")
    if page_index < 0 or page_index >= len(doc):
        raise IndexError(f"page_index {page_index} is out of range for a {len(doc)}-page document")
    doc.close()

    with tempfile.TemporaryDirectory(prefix="boxcheck-planes-") as tmpdir:
        tmp = Path(tmpdir)
        input_pdf = tmp / "input.pdf"
        output_file = tmp / "page0.bplane2"
        input_pdf.write_bytes(pdf_bytes)

        cmd = [PLANES_BIN, str(input_pdf), str(output_file), "--page", str(page_index)]
        proc = subprocess.run(cmd, capture_output=True, timeout=PLANES_TIMEOUT_SECONDS)
        if proc.returncode != 0:
            raise RuntimeError(
                f"plane exporter failed (rc={proc.returncode}): "
                + proc.stderr.decode("utf-8", "ignore")[:500]
            )
        if not output_file.exists() or output_file.stat().st_size == 0:
            raise RuntimeError("plane exporter produced no output")
        return output_file.read_bytes()


@app.post("/check/page-planes")
@limiter.limit("20/minute")
async def check_page_planes(
    request: Request,
    file: UploadFile = File(...),
    page_index: int = 0,
):
    """Authoritative N-channel page planes for the client-side
    SeparationViewer: the page rendered through the SAME pdfcer Ink Manager
    path as /check/ink-preview (100 DPI, CmykAndSpotOnly, 512 MiB colorant
    ceiling), with the CmykBuffer retained BEFORE its sRGB collapse.

    The response is the gzip-compressed BCPLANE2 container
    (application/octet-stream, Content-Encoding: gzip): header with
    width/height/DPI/intent/spot names, a per-plane directory, the raw u8
    plane region (C, M, Y, K, spots in roster order, alpha — each exactly
    width×height, subtractive polarity 0 = no ink), CRC32-checked.

    Deliberately separate from /check/ink-preview, which stays UNCHANGED as
    the raster fallback: this endpoint is the data plane for a viewer that
    composites and toggles channels locally, with zero network traffic on
    hover or toggle. No probe, no exclusions — the viewer applies those
    locally against the same authoritative buffer.
    """
    pdf_bytes = await file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(pdf_bytes) > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail={"code": "file_too_large", "message": f"File too large, max {max_mb}MB.", "max_mb": max_mb},
        )

    try:
        raw = await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None, _render_page_planes_sync, pdf_bytes, page_index,
            ),
            timeout=PROCESSING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "timeout",
                "message": f"Plane export timed out after {PROCESSING_TIMEOUT_SECONDS}s.",
                "timeout_s": PROCESSING_TIMEOUT_SECONDS,
            },
        )
    except pymupdf.FileDataError:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pdf", "message": "File is not a valid or readable PDF."},
        )
    except EncryptedPDFError:
        raise HTTPException(
            status_code=422,
            detail={"code": "encrypted_pdf", "message": "PDF is password-protected."},
        )
    except IndexError as e:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_page_index", "message": str(e)},
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "plane_export_failed", "message": str(e)},
        )

    # Validate BEFORE responding: a container that cannot be parsed is a
    # broken exporter, not the caller's problem — surface it as a typed 502
    # rather than shipping bytes the viewer would reject anyway.
    try:
        parsed = await asyncio.get_running_loop().run_in_executor(None, parse_bplane2, raw)
    except ValueError as e:
        raise HTTPException(
            status_code=502,
            detail={"code": "plane_export_invalid", "message": str(e)},
        )

    headers = {
        # Container metadata the viewer needs BEFORE decompressing/allocating.
        "X-Plane-Width": str(parsed["width"]),
        "X-Plane-Height": str(parsed["height"]),
        "X-Plane-Dpi-X100": str(parsed["dpi_x100"]),
        "X-Plane-Intent": str(parsed["intent"]),
        "X-Plane-Count": str(len(parsed["planes"])),
        "X-Plane-Spots-Flattened": str(parsed["spots_flattened"]),
        # ensure_ascii keeps the header latin-1-safe for exotic colorants.
        "X-Plane-Spot-Names": json.dumps(parsed["spot_names"]),
        "X-Plane-Crc32": f"{parsed['crc32']:08x}",
    }
    return Response(
        content=gzip.compress(raw, compresslevel=6),
        media_type="application/octet-stream",
        headers={**headers, "Content-Encoding": "gzip"},
    )


@app.post("/check")
@limiter.limit("10/minute")
async def check_pdf(
    request: Request,
    file: UploadFile = File(...),
    print_method: Literal["carton", "label", "flexible", "digital", "offset", "unknown"] = "unknown",
    hairline_threshold: Optional[float] = None,
    unit: Literal["mm", "pt", "inch"] = "mm",
    bleed_threshold: Optional[float] = None,
    dpi_threshold: Optional[int] = None,
    product_id: Optional[str] = None,
    format_id: Optional[str] = None,
    include_canvas: bool = False,
    declared_width_mm: Optional[float] = None,
    declared_height_mm: Optional[float] = None,
):
    pdf_bytes = await file.read(MAX_FILE_SIZE_BYTES + 1)
    if len(pdf_bytes) > MAX_FILE_SIZE_BYTES:
        max_mb = MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail={"code": "file_too_large", "message": f"File too large, max {max_mb}MB.", "max_mb": max_mb},
        )

    try:
        return await asyncio.wait_for(
            asyncio.get_running_loop().run_in_executor(
                None, _check_pdf_sync, pdf_bytes, file.filename, print_method, hairline_threshold, unit,
                bleed_threshold, dpi_threshold, product_id, format_id, include_canvas,
                declared_width_mm, declared_height_mm,
            ),
            timeout=PROCESSING_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "timeout",
                "message": f"PDF processing timed out after {PROCESSING_TIMEOUT_SECONDS}s.",
                "timeout_s": PROCESSING_TIMEOUT_SECONDS,
            },
        )
    except pymupdf.FileDataError:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_pdf", "message": "File is not a valid or readable PDF."},
        )
    except EncryptedPDFError:
        raise HTTPException(
            status_code=422,
            detail={"code": "encrypted_pdf", "message": "PDF is password-protected."},
        )
