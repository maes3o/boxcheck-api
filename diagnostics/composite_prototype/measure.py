"""Read-only measurement script for the GS-composite-integration audit.
Does NOT modify render_preview.py/spot_separations.py/composite_prototype.py
— imports them as-is. Not wired into production; run manually for this
audit only."""
import io
import json
import resource
import sys
import time

sys.path.insert(0, "..")
sys.path.insert(0, ".")

import pymupdf

import composite_prototype as cp
from render_preview import render_page_preview, _page_scale, DEFAULT_MAX_DIMENSION_PX

FILES = [
    ("test-files/47 Magura_Brelok-lenta_20260907 PRINT.pdf", "simple CMYK, tiny"),
    ("test-files/PLS_Original_ENG_91_A3-PRINT.pdf", "CMYK + named process separations, A3-ish"),
    ("test-files/00029_21.08.2026_Dash_390х196х60_PRINT-2.pdf", "CMYK + real PANTONE spots + dieline"),
    ("test-files/M00016_22.07.2026_Завод_алмазного_інструменту_100х103х25_Е-PRINT.pdf", "heaviest file size (10.2MB), large/complex"),
    ("/tmp/synthetic_multipage.pdf", "synthetic 3-page"),
    ("test-files/57384_07.05.2025_КМВ_Кукурудзяні_кільця_зі_смаком_кальмару_75г_98.94%.pdf", "REAL reference file, 8 spots incl. White-1 overprint"),
]

results = []

for path, label in FILES:
    doc = pymupdf.open(path)
    page = doc[0]
    scale = _page_scale(page, DEFAULT_MAX_DIMENSION_PX)
    dpi = scale * 72.0

    # --- current production: pymupdf render_page_preview ---
    t0 = time.monotonic()
    preview = render_page_preview(page, DEFAULT_MAX_DIMENSION_PX)
    t_pymupdf = time.monotonic() - t0
    pymupdf_png_bytes = len(preview["url"])  # base64 length as a size proxy

    # --- prototype: Ghostscript composite at the SAME effective dpi ---
    pdf_bytes = cp.get_page_pdf_bytes(path, 0)
    rusage_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    t0 = time.monotonic()
    try:
        gs_result = cp.render_ghostscript_composite(pdf_bytes, dpi=dpi)
        t_gs = time.monotonic() - t0
        rusage_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        gs_ok = True
        gs_dims = f'{gs_result["width_px"]}x{gs_result["height_px"]}'
        gs_composite_bytes = len(gs_result["composite_tiff"])
        gs_separations_count = len(gs_result["separations"])
        gs_peak_rss_kb = rusage_after  # cumulative children max RSS since interpreter start
        gs_error = None
    except Exception as e:
        t_gs = time.monotonic() - t0
        gs_ok = False
        gs_dims = None
        gs_composite_bytes = None
        gs_separations_count = None
        gs_peak_rss_kb = None
        gs_error = str(e)[:300]

    row = {
        "file": path.split("/")[-1],
        "label": label,
        "page_count": len(doc),
        "mediabox_pt": f"{page.mediabox.width:.0f}x{page.mediabox.height:.0f}",
        "effective_dpi": round(dpi, 1),
        "pymupdf_preview_time_s": round(t_pymupdf, 3),
        "pymupdf_preview_dims": f'{preview["width_px"]}x{preview["height_px"]}',
        "gs_ok": gs_ok,
        "gs_composite_time_s": round(t_gs, 3),
        "gs_composite_dims": gs_dims,
        "gs_composite_tiff_bytes": gs_composite_bytes,
        "gs_separations_count": gs_separations_count,
        "gs_error": gs_error,
    }
    results.append(row)
    print(json.dumps(row, ensure_ascii=False, indent=2))
    doc.close()

with open("diagnostics/composite_prototype/measurements.json", "w") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\nsaved diagnostics/composite_prototype/measurements.json")
