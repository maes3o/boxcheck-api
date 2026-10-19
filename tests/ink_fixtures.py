"""Synthetic PDFs for the Ink Coverage tests, built in code (like the other
BoxCheck tests) — no binary fixtures. The independent validation corpus under
/tmp/ink_validation_corpus_v1 is used only as optional regression input and
is never copied or modified.
"""
from __future__ import annotations

import zlib


def pname(s: str) -> str:
    """PDF name with #xx escapes for anything outside the safe ASCII set."""
    out = []
    for b in s.encode("utf-8"):
        c = chr(b)
        if b < 0x21 or b > 0x7E or c in "#()<>[]{}/%":
            out.append("#%02X" % b)
        else:
            out.append(c)
    return "/" + "".join(out)


class Pdf:
    def __init__(self):
        self.objs: list[bytes | None] = []

    def reserve(self) -> int:
        self.objs.append(None)
        return len(self.objs)

    def set(self, n: int, body):
        self.objs[n - 1] = body if isinstance(body, bytes) else body.encode("latin-1")

    def add(self, body) -> int:
        n = self.reserve()
        self.set(n, body)
        return n

    def stream(self, dict_body: str, data, flate: bool = False) -> int:
        data = data if isinstance(data, bytes) else data.encode("latin-1")
        if flate:
            data = zlib.compress(data, 9)
            dict_body += " /Filter /FlateDecode"
        n = self.reserve()
        self.set(n, ("<< %s /Length %d >>\nstream\n" % (dict_body, len(data))).encode("latin-1")
                 + data + b"\nendstream")
        return n

    def build(self, root: int, extra_trailer: str = "") -> bytes:
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offs = []
        for i, o in enumerate(self.objs, 1):
            assert o is not None, i
            offs.append(len(out))
            out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
        x = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(self.objs) + 1)
        for o in offs:
            out += b"%010d 00000 n \n" % o
        out += b"trailer\n<< /Size %d /Root %d 0 R %s >>\nstartxref\n%d\n%%%%EOF\n" % (
            len(self.objs) + 1, root, extra_trailer.encode("latin-1"), x)
        return bytes(out)


def tint_fn(pdf: Pdf, n_out: int = 4, c1: str = "0 0 0 1") -> int:
    return pdf.add("<< /FunctionType 2 /Domain [0 1] /C0 [%s] /C1 [%s] /N 1 >>" % (" ".join(["0"] * n_out), c1))


def separation_cs(pdf: Pdf, name: str, c1: str = "0 1 1 0") -> int:
    return pdf.add("[/Separation %s /DeviceCMYK %d 0 R]" % (pname(name), tint_fn(pdf, 4, c1)))


def devicen_cs(pdf: Pdf, names: list[str]) -> int:
    n = len(names)
    fn = pdf.stream(
        "/FunctionType 4 /Domain [%s] /Range [0 1 0 1 0 1 0 1]" % " ".join(["0 1"] * n),
        "{ " + " ".join(["pop"] * n) + " 0 0 0 0 }",
    )
    return pdf.add("[/DeviceN [%s] /DeviceCMYK %d 0 R]" % (" ".join(pname(x) for x in names), fn))


def make_pdf(pages: list[dict], *, root_extra: str = "", pdf: Pdf | None = None,
             trailer_extra: str = "") -> bytes:
    """pages: [{content, resources(str), mediabox, extra(str)}].
    A `pdf` with pre-built objects (colour spaces ...) can be passed in; the
    resource strings reference them as 'N 0 R'."""
    pdf = pdf or Pdf()
    cat = pdf.reserve()
    pages_ref = pdf.reserve()
    kids = []
    for p in pages:
        cont = pdf.stream(p.get("stream_dict", ""), p["content"], flate=p.get("flate", False))
        mb = p.get("mediabox", (0, 0, 200, 200))
        kids.append(pdf.add(
            "<< /Type /Page /Parent %d 0 R /MediaBox [%s] /Contents %d 0 R /Resources << %s >> %s >>"
            % (pages_ref, " ".join(str(v) for v in mb), cont, p.get("resources", ""), p.get("extra", ""))
        ))
    pdf.set(pages_ref, "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % k for k in kids), len(kids)))
    pdf.set(cat, "<< /Type /Catalog /Pages %d 0 R %s >>" % (pages_ref, root_extra))
    return pdf.build(cat, trailer_extra)


# --------------------------------------------------------------------------
# Ready-made documents (200 x 200 pt pages; areas in % of the page)
# --------------------------------------------------------------------------

def cmyk_quarter() -> bytes:
    """C 100% + M 50% over 25% of the page -> C mean 25, M mean 12.5."""
    return make_pdf([{"content": "1 0.5 0 0 k\n50 50 100 100 re f\n"}])


def spot_pdf(name: str, tint: float = 1.0, rect=(50, 50, 100, 100), content_extra: str = "") -> bytes:
    pdf = Pdf()
    cs = separation_cs(pdf, name)
    return make_pdf(
        [{"content": "/CS1 cs %g scn\n%s re f\n%s" % (tint, " ".join(str(v) for v in rect), content_extra),
          "resources": "/ColorSpace << /CS1 %d 0 R >>" % cs}],
        pdf=pdf)


def multi_spot_pdf(names: list[str], tint: float = 1.0) -> bytes:
    """One small square per spot, in a row of columns."""
    pdf = Pdf()
    refs = {n: separation_cs(pdf, n) for n in names}
    body = []
    for i, n in enumerate(names):
        body.append("/C%d cs %g scn\n%d 10 5 5 re f" % (i, tint, 2 + 6 * i))
    res = "/ColorSpace << %s >>" % " ".join("/C%d %d 0 R" % (i, refs[n]) for i, n in enumerate(names))
    return make_pdf([{"content": "\n".join(body), "resources": res, "mediabox": (0, 0, 400, 100)}], pdf=pdf)


def devicen_pdf(names: list[str], tints: list[float]) -> bytes:
    pdf = Pdf()
    cs = devicen_cs(pdf, names)
    return make_pdf(
        [{"content": "/CS1 cs %s scn\n50 50 100 100 re f\n" % " ".join("%g" % t for t in tints),
          "resources": "/ColorSpace << /CS1 %d 0 R >>" % cs}],
        pdf=pdf)


def declared_unused_pdf() -> bytes:
    pdf = Pdf()
    used = separation_cs(pdf, "Used Spot")
    unused = separation_cs(pdf, "Unused Spot")
    dn = devicen_cs(pdf, ["Unused DN A", "Unused DN B"])
    return make_pdf(
        [{"content": "/CS1 cs 1 scn\n0 0 100 100 re f\n",
          "resources": "/ColorSpace << /CS1 %d 0 R /CS2 %d 0 R /CS3 %d 0 R >>" % (used, unused, dn)}],
        pdf=pdf)


def nested_form_pdf() -> bytes:
    """K 0.8 in a form inside a form, scaled by 0.5 and offset: 100x100 pt
    inner square -> 50x50 pt on the page = 6.25% of 200x200; mean 0.8*6.25."""
    pdf = Pdf()
    inner = pdf.stream("/Type /XObject /Subtype /Form /BBox [0 0 100 100] /Resources << >>",
                       "0 0 0 0.8 k\n0 0 100 100 re f\n")
    outer = pdf.stream(
        "/Type /XObject /Subtype /Form /BBox [0 0 100 100] /Matrix [0.5 0 0 0.5 0 0] /Resources << /XObject << /F2 %d 0 R >> >>" % inner,
        "/F2 Do")
    return make_pdf(
        [{"content": "1 0 0 1 20 20 cm\n/F1 Do\n", "resources": "/XObject << /F1 %d 0 R >>" % outer}], pdf=pdf)


def multipage_pdf() -> bytes:
    pdf = Pdf()
    cs = separation_cs(pdf, "Page Two Spot")
    return make_pdf([
        {"content": "1 0 0 0 k\n0 0 100 200 re f\n"},
        {"content": "/CS1 cs 0.5 scn\n0 0 200 100 re f\n", "resources": "/ColorSpace << /CS1 %d 0 R >>" % cs},
        {"content": "0 0 0 0.5 k\n0 0 200 100 re f\n"},
    ], pdf=pdf)


def overprint_pdf(opm: int, overprint: bool = True) -> bytes:
    """Cyan 100% square, then Magenta 100% square over it with/without
    overprint. With overprint the Cyan plate keeps its ink where M overlaps."""
    gs = "/GS1 << /Type /ExtGState /OP %s /op %s /OPM %d >>" % (
        str(overprint).lower(), str(overprint).lower(), opm)
    content = ("1 0 0 0 k\n0 0 100 100 re f\n"
               "/GS1 gs\n0 1 0 0 k\n50 0 100 100 re f\n")
    return make_pdf([{"content": content, "resources": "/ExtGState << %s >>" % gs}])


def spot_under_cmyk_pdf(overprint: bool) -> bytes:
    pdf = Pdf()
    cs = separation_cs(pdf, "Under Spot")
    gs = "/GS1 << /Type /ExtGState /OP %s /op %s /OPM 1 >>" % (str(overprint).lower(), str(overprint).lower())
    content = ("/CS1 cs 1 scn\n0 0 100 100 re f\n/GS1 gs\n1 0 0 0 k\n50 0 100 100 re f\n")
    return make_pdf([{"content": content, "resources": "/ColorSpace << /CS1 %d 0 R >> /ExtGState << %s >>" % (cs, gs)}], pdf=pdf)


def thin_stroke_pdf(width: float = 0.25) -> bytes:
    pdf = Pdf()
    cs = separation_cs(pdf, "Thin Line")
    return make_pdf(
        [{"content": "/CS1 CS 1 SCN\n%g w\n20 100 m 180 100 l S\n" % width,
          "resources": "/ColorSpace << /CS1 %d 0 R >>" % cs}], pdf=pdf)


def rgb_gray_pdf() -> bytes:
    return make_pdf([{"content": "0.9 0.2 0.1 rg\n0 0 100 100 re f\n0.5 g\n100 100 50 50 re f\n"}])


def all_none_pdf() -> bytes:
    pdf = Pdf()
    allcs = pdf.add("[/Separation /All /DeviceCMYK %d 0 R]" % tint_fn(pdf))
    nonecs = pdf.add("[/Separation /None /DeviceCMYK %d 0 R]" % tint_fn(pdf))
    return make_pdf(
        [{"content": "/A cs 0.5 scn\n0 0 100 100 re f\n/N cs 1 scn\n100 100 50 50 re f\n",
          "resources": "/ColorSpace << /A %d 0 R /N %d 0 R >>" % (allcs, nonecs)}], pdf=pdf)


def inline_image_pdf() -> bytes:
    # Binary payload containing a fake "EI" must not end the image early.
    payload = b"\x00\x01 EI \xff\xfe\x80"
    content = (b"q 20 0 0 20 0 0 cm\nBI /W 2 /H 2 /BPC 8 /CS /G ID " + payload + b"\nEI\nQ\n"
               b"0 0 0 1 k\n100 100 50 50 re f\n")
    return make_pdf([{"content": content.decode("latin-1")}])


def imagemask_pdf() -> bytes:
    pdf = Pdf()
    cs = separation_cs(pdf, "Mask Spot")
    img = pdf.stream("/Type /XObject /Subtype /Image /Width 1 /Height 1 /ImageMask true /BitsPerComponent 1",
                     b"\x00")
    return make_pdf(
        [{"content": "/CS1 cs 1 scn\nq 100 0 0 100 0 0 cm /Im1 Do Q\n",
          "resources": "/ColorSpace << /CS1 %d 0 R >> /XObject << /Im1 %d 0 R >>" % (cs, img)}], pdf=pdf)


def text_mode3_pdf() -> bytes:
    pdf = Pdf()
    cs = separation_cs(pdf, "Text Spot")
    font = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    content = ("/CS1 cs 1 scn\nBT /F1 40 Tf 3 Tr 10 100 Td (HIDDEN) Tj ET\n"
               "BT /F1 40 Tf 0 Tr 10 20 Td (V) Tj ET\n")
    return make_pdf(
        [{"content": content,
          "resources": "/ColorSpace << /CS1 %d 0 R >> /Font << /F1 %d 0 R >>" % (cs, font)}], pdf=pdf)


def invisible_text_only_pdf() -> bytes:
    pdf = Pdf()
    cs = separation_cs(pdf, "Ghost Spot")
    font = pdf.add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    return make_pdf(
        [{"content": "/CS1 cs 1 scn\nBT /F1 40 Tf 3 Tr 10 100 Td (HIDDEN) Tj ET\n",
          "resources": "/ColorSpace << /CS1 %d 0 R >> /Font << /F1 %d 0 R >>" % (cs, font)}], pdf=pdf)


def ctm_stroke_pdf(scale: float, width: float) -> bytes:
    pdf = Pdf()
    cs = separation_cs(pdf, "Scaled Line")
    return make_pdf(
        [{"content": "/CS1 CS 1 SCN\n%g 0 0 %g 0 0 cm\n%g w\n10 20 m 190 20 l S\n" % (scale, scale, width),
          "resources": "/ColorSpace << /CS1 %d 0 R >>" % cs}], pdf=pdf)


def transparency_pdf() -> bytes:
    pdf = Pdf()
    cs = separation_cs(pdf, "Glass Spot")
    gs = "/GS1 << /Type /ExtGState /ca 0.5 >>"
    return make_pdf(
        [{"content": "/GS1 gs\n/CS1 cs 1 scn\n0 0 100 100 re f\n",
          "resources": "/ColorSpace << /CS1 %d 0 R >> /ExtGState << %s >>" % (cs, gs)}], pdf=pdf)


def ocg_off_pdf() -> bytes:
    """Spot painted inside an optional-content layer that is OFF by default."""
    pdf = Pdf()
    cs = separation_cs(pdf, "Layer Spot")
    ocg = pdf.add("<< /Type /OCG /Name (Die) >>")
    content = "/OC /MC0 BDC\n/CS1 cs 1 scn\n0 0 100 100 re f\nEMC\n"
    root_extra = "/OCProperties << /OCGs [%d 0 R] /D << /OFF [%d 0 R] /Order [%d 0 R] >> >>" % (ocg, ocg, ocg)
    return make_pdf(
        [{"content": content,
          "resources": "/ColorSpace << /CS1 %d 0 R >> /Properties << /MC0 %d 0 R >>" % (cs, ocg)}],
        pdf=pdf, root_extra=root_extra)


def self_referencing_form_pdf() -> bytes:
    pdf = Pdf()
    f = pdf.reserve()
    pdf.set(f, ("<< /Type /XObject /Subtype /Form /BBox [0 0 200 200] /Resources << /XObject << /F1 %d 0 R >> >> /Length 40 >>\n"
                "stream\n1 0 0 0 k 0 0 50 50 re f /F1 Do\nendstream" % f))
    return make_pdf([{"content": "/F1 Do\n", "resources": "/XObject << /F1 %d 0 R >>" % f}], pdf=pdf)


def deep_nesting_pdf(depth: int = 30) -> bytes:
    pdf = Pdf()
    prev = None
    refs = []
    for i in range(depth):
        refs.append(pdf.reserve())
    for i, r in enumerate(refs):
        child = ("/XObject << /F %d 0 R >>" % refs[i + 1]) if i + 1 < depth else ""
        body = ("1 0 0 0 k 0 0 20 20 re f /F Do" if i + 1 < depth else "1 0 0 0 k 0 0 20 20 re f")
        pdf.set(r, ("<< /Type /XObject /Subtype /Form /BBox [0 0 200 200] /Resources << %s >> /Length %d >>\nstream\n%s\nendstream"
                    % (child, len(body), body)))
    return make_pdf([{"content": "/F Do\n", "resources": "/XObject << /F %d 0 R >>" % refs[0]}], pdf=pdf)


def flate_bomb_pdf(megabytes: int = 70) -> bytes:
    """Content stream that inflates to > the 64 MB per-stream cap."""
    return make_pdf([{"content": b" " * (megabytes * 1024 * 1024), "flate": True}])


def giant_mediabox_pdf() -> bytes:
    return make_pdf([{"content": "1 0 0 0 k\n0 0 1000 1000 re f\n", "mediabox": (0, 0, 14400, 14400)}])


def rotated_pdf() -> bytes:
    return make_pdf([{"content": "1 0 0 0 k\n0 0 100 200 re f\n", "mediabox": (0, 0, 200, 100), "extra": "/Rotate 90"}])


def userunit_pdf() -> bytes:
    return make_pdf([{"content": "1 0 0 0 k\n0 0 100 100 re f\n", "extra": "/UserUnit 2"}])


def cropbox_pdf() -> bytes:
    """MediaBox 200x200, CropBox the left half; C fills the whole media box
    -> inside the CropBox coverage is 100%."""
    return make_pdf([{"content": "1 0 0 0 k\n0 0 200 200 re f\n", "extra": "/CropBox [0 0 100 200]"}])


def unicode_name_pdf(name: str) -> bytes:
    return spot_pdf(name)


def case_variant_names_pdf() -> bytes:
    return multi_spot_pdf(["Spot A", "spot a"])


def many_spots_pdf(n: int, size=(2000, 1500), thin_line: bool = False) -> bytes:
    """`n` spot colours, one 20x20 pt square each; optionally a hairline in the
    first spot (forces the high-DPI second pass). Big pages exercise the
    memory cost of many spot planes."""
    pdf = Pdf()
    refs = [separation_cs(pdf, "Spot %02d" % i) for i in range(n)]
    body = ["/C%d cs 1 scn %d 10 20 20 re f" % (i, 10 + 30 * i) for i in range(n)]
    if thin_line:
        body.append("/C0 CS 1 SCN 0.2 w 10 700 m 1000 700 l S")
    res = "/ColorSpace << %s >>" % " ".join("/C%d %d 0 R" % (i, r) for i, r in enumerate(refs))
    return make_pdf([{"content": "\n".join(body), "resources": res, "mediabox": (0, 0, size[0], size[1])}], pdf=pdf)
