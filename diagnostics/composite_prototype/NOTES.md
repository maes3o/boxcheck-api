# STEP 1 prototype — empirical notes

## `-dSeparationColorNames` does NOT exclude a real colorant (tested, disproved)

Initial assumption: Ghostscript's tiffsep `-dSeparationColorNames` device
parameter could be used to omit `White-1` from the list, forcing it to fall
back through its Separation colorspace's alternate space instead of getting
its own overprint-composited plate — giving a "White-1 disabled" composite
to compare against the baseline.

Tested directly against the real production PDF (single page, extracted via
`composite_prototype.get_page_pdf_bytes`):

```
gs -dBATCH -dNOPAUSE -dSAFER -sDEVICE=tiffsep -r150.00 -dFirstPage=1 -dLastPage=1 \
   -sOutputFile=composite_test3.tif \
   -c "<< /SeparationColorNames [/Cyan /Magenta /Yellow /Black] >> setpagedevice" \
   -f input.pdf
```

(Plain `-dSeparationColorNames=[...]` on the command line errors out in this
GS 9.55.0 build: `Invalid value for option ..., use -sNAME= to define string
constants` — the `-c ... setpagedevice` form above is the one that actually
runs.)

**Result: Ghostscript still wrote a separate `composite_test3(White-1).tif`
plate, byte-identical in size (54374 bytes) to the unrestricted baseline
run.** `Lak`, `PANTONE 3262 C`, and `PANTONE Black C` — also omitted from
the list — were likewise still rendered as their own plates. So
`SeparationColorNames` did not suppress anything actually painted in the
page's content in this GS version — conclusion: **no working GS-native,
content-stream-safe way to synthesize a "White-1 off" composite was found**
within this prototype's scope. Do not re-attempt this exact approach without
new evidence it behaves differently in some other GS build/version.

## What was used instead

Rather than a fabricated on/off toggle, `compare_under_mask()` compares
Ghostscript's real composite against pymupdf's naive (no overprint model at
all) composite, split by whether White-1's own real ink mask (from the SAME
Ghostscript tiffsep run) is present at each pixel. This answers "does GS's
overprint modeling do something different specifically where White-1
paints" empirically, without needing the excluded-plate render. See
`report.json` for the real numbers from the production PDF.

## Known small alignment gap

GS composite: 4246×3363 px. pymupdf naive composite at the same nominal DPI
(150): 4247×3363 px — 1px width difference, consistent with the
already-documented independent-rounding gap between the two rasterizers
(see `spot_separations.py`'s own comment on this). `compare_under_mask`
crops both to their common region before comparing, same defensive pattern
`spot_separations.py::_average_color_at_high_coverage` already uses.
