"""
BoxCheck Ink Coverage — native colorant detection by content-stream analysis.

Walks a page's content stream (and the Form XObjects / patterns it invokes)
and reports which colorants are ACTUALLY PAINTED — as opposed to merely
declared in a Resources/ColorSpace dictionary. Independent of the raster
measurement (ink_gs_measure.py); ink_coverage.py reconciles the two.

Nothing here imports main.py (avoids a cycle). Hostile-input budgets:
10M tokens and 10 s per page, form depth 10 with cycle detection, 64 MB per
decoded stream, 32 colorants per page. Exceeding a budget raises
ScanBudgetExceeded; the caller degrades to plates-only detection.
"""

from __future__ import annotations

import math
import re
import time

MAX_TOKENS = 10_000_000
MAX_SECONDS = 10.0
MAX_FORM_XOBJECT_DEPTH = 10
MAX_STREAM_BYTES = 64 * 1024 * 1024
MAX_COLORANTS_PER_PAGE = 32
MAX_NESTING = 64
THIN_STROKE_PX = 2.0

PROCESS_NAMES = ("Cyan", "Magenta", "Yellow", "Black")


class ScanBudgetExceeded(Exception):
    pass


# --------------------------------------------------------------------------
# Lexer / object parser
# --------------------------------------------------------------------------

K_NUM, K_NAME, K_STR, K_OP = "num", "name", "str", "op"

_TOKEN_RE = re.compile(
    rb"""
    (?P<ws>[\x00\t\n\x0c\r ]+)
   |(?P<comment>%[^\r\n]*)
   |(?P<name>/[^\x00\t\n\x0c\r ()<>\[\]{}/%]*)
   |(?P<dopen><<)
   |(?P<dclose>>>)
   |(?P<hex><[^>]*>)
   |(?P<lit>\()
   |(?P<aopen>\[)
   |(?P<aclose>\])
   |(?P<brace>[{}])
   |(?P<reg>[^\x00\t\n\x0c\r ()<>\[\]{}/%]+)
   |(?P<stray>[)>])
    """,
    re.X,
)
_NUM_RE = re.compile(rb"[+-]?(?:\d+\.?\d*|\.\d+)\Z")
_STR_SPECIAL_RE = re.compile(rb"[()\\]")
_NAME_ESC_RE = re.compile(rb"#([0-9A-Fa-f]{2})")


def decode_name(raw: bytes) -> str:
    """PDF name (without the leading slash) -> str. #xx escapes are expanded;
    bytes are decoded as UTF-8 with a latin-1 fallback."""
    if b"#" in raw:
        raw = _NAME_ESC_RE.sub(lambda m: bytes([int(m.group(1), 16)]), raw)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


class Ref(int):
    """Indirect reference (object number)."""


class Budget:
    def __init__(self, max_tokens=MAX_TOKENS, max_seconds=MAX_SECONDS):
        self.max_tokens = max_tokens
        self.deadline = time.monotonic() + max_seconds
        self.tokens = 0

    def tick(self):
        self.tokens += 1
        if self.tokens > self.max_tokens:
            raise ScanBudgetExceeded("token budget")
        if not (self.tokens & 0xFFF) and time.monotonic() > self.deadline:
            raise ScanBudgetExceeded("time budget")

    def check_time(self):
        if time.monotonic() > self.deadline:
            raise ScanBudgetExceeded("time budget")


class Lexer:
    def __init__(self, data: bytes, budget: Budget):
        self.d = data
        self.pos = 0
        self.n = len(data)
        self.budget = budget

    def next(self):
        d, n = self.d, self.n
        while True:
            if self.pos >= n:
                return None
            m = _TOKEN_RE.match(d, self.pos)
            if m is None:
                self.pos += 1
                continue
            self.pos = m.end()
            k = m.lastgroup
            if k == "ws" or k == "comment":
                continue
            self.budget.tick()
            if k == "name":
                return (K_NAME, decode_name(m.group()[1:]))
            if k == "reg":
                t = m.group()
                if _NUM_RE.match(t):
                    return (K_NUM, float(t) if b"." in t else int(t))
                return (K_OP, t.decode("latin-1"))
            if k == "lit":
                return (K_STR, self._literal())
            if k == "hex":
                return (K_STR, m.group()[1:-1])
            return (k, None)

    def _literal(self) -> bytes:
        d = self.d
        start = self.pos
        depth = 1
        p = start
        while depth:
            m = _STR_SPECIAL_RE.search(d, p)
            if m is None:
                self.pos = self.n
                return d[start:]
            c = d[m.start()]
            if c == 0x5C:  # backslash: skip escaped char
                p = m.start() + 2
                continue
            depth += 1 if c == 0x28 else -1
            p = m.end()
        self.pos = p
        return d[start:p - 1]


def read_value(lex: Lexer, tok, depth: int = 0):
    """Reads one object whose first token is `tok`. Keywords: true/false/null.
    Unknown keywords come back as the `Op` marker class instance."""
    if depth > MAX_NESTING:
        raise ScanBudgetExceeded("nesting")
    kind, val = tok
    if kind in (K_NUM, K_NAME, K_STR):
        return val
    if kind == "aopen":
        items = []
        while True:
            t = lex.next()
            if t is None or t[0] == "aclose":
                break
            items.append(read_value(lex, t, depth + 1))
        return _collapse_refs(items)
    if kind == "dopen":
        items = []
        while True:
            t = lex.next()
            if t is None or t[0] == "dclose":
                break
            items.append(read_value(lex, t, depth + 1))
        items = _collapse_refs(items)
        out = {}
        i = 0
        while i + 1 < len(items):
            if isinstance(items[i], str) and not isinstance(items[i], Op):
                out[items[i]] = items[i + 1]
                i += 2
            else:
                i += 1
        return out
    if kind == K_OP:
        if val == "true":
            return True
        if val == "false":
            return False
        if val == "null":
            return None
        return Op(val)
    return None


class Op(str):
    """A bare keyword that is not a name/number/string (e.g. `R`, or garbage)."""


def _collapse_refs(items):
    if not any(isinstance(x, Op) and x == "R" for x in items):
        return items
    out = []
    for x in items:
        if isinstance(x, Op) and x == "R" and len(out) >= 2 \
                and isinstance(out[-1], int) and isinstance(out[-2], int) \
                and not isinstance(out[-1], bool) and not isinstance(out[-2], bool):
            out.pop()
            num = out.pop()
            out.append(Ref(num))
        else:
            out.append(x)
    return out


def parse_obj(data, budget: Budget | None = None):
    """Parses one PDF object from `data` (str or bytes), e.g. the text
    MuPDF's xref_object() returns. Returns None on empty input."""
    if isinstance(data, str):
        data = data.encode("latin-1", "replace")
    lex = Lexer(data, budget or Budget())
    first = lex.next()
    if first is None:
        return None
    return read_value(lex, first)


# --------------------------------------------------------------------------
# Matrices
# --------------------------------------------------------------------------

def mat_mul(m, n):
    """m x n in PDF row-vector convention (apply m first)."""
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a * a2 + b * c2, a * b2 + b * d2,
        c * a2 + d * c2, c * b2 + d * d2,
        e * a2 + f * c2 + e2, e * b2 + f * d2 + f2,
    )


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _as_matrix(v):
    if isinstance(v, list) and len(v) == 6 and all(isinstance(x, (int, float)) for x in v):
        return tuple(float(x) for x in v)
    return IDENTITY


# --------------------------------------------------------------------------
# Colour spaces
# --------------------------------------------------------------------------

class CS:
    """Normalised colour-space descriptor."""
    __slots__ = ("family", "names", "n", "base")

    def __init__(self, family, names=(), n=1, base=None):
        self.family = family
        self.names = list(names)
        self.n = n
        self.base = base


CS_GRAY = CS("DeviceGray", n=1)
CS_RGB = CS("DeviceRGB", n=3)
CS_CMYK = CS("DeviceCMYK", n=4)
CS_PATTERN = CS("Pattern", n=0)

_DEVICE_ALIASES = {
    "DeviceGray": CS_GRAY, "G": CS_GRAY, "CalGray": None,
    "DeviceRGB": CS_RGB, "RGB": CS_RGB,
    "DeviceCMYK": CS_CMYK, "CMYK": CS_CMYK,
    "Pattern": CS_PATTERN,
}


def initial_color(cs: CS):
    f = cs.family
    if f in ("Separation", "DeviceN"):
        return [1.0] * max(cs.n, 1)
    if f == "DeviceCMYK":
        return [0.0, 0.0, 0.0, 1.0]
    if f == "Pattern":
        return None
    return [0.0] * max(cs.n, 1)


# --------------------------------------------------------------------------
# Document access
# --------------------------------------------------------------------------

class Resources:
    """A resource dictionary with per-category fallback to its parent
    (a Form XObject without its own /XObject etc. inherits the caller's)."""

    def __init__(self, scanner, d, parent=None):
        self.sc = scanner
        self.d = d if isinstance(d, dict) else {}
        self.parent = parent

    def category(self, cat):
        v = self.sc.resolve(self.d.get(cat))
        if isinstance(v, dict):
            return v
        if self.parent is not None:
            return self.parent.category(cat)
        return {}

    def lookup(self, cat, name):
        return self.category(cat).get(name)


class PageScanner:
    def __init__(self, doc, base_dpi: float = 150.0, user_unit: float = 1.0,
                 max_tokens=MAX_TOKENS, max_seconds=MAX_SECONDS):
        self.doc = doc
        self.base_dpi = base_dpi
        self.user_unit = user_unit
        self.budget = Budget(max_tokens, max_seconds)
        self._obj_cache: dict[int, object] = {}
        self._cs_cache: dict[int, CS] = {}
        self.colorants: dict[str, dict] = {}
        self.converted: dict[str, int] = {}
        self.declared: dict[str, set] = {}
        self.flags: set[str] = set()
        self.thin_stroke_paints = 0
        self.min_stroke_width_pt: float | None = None
        self._declared_seen: set[int] = set()
        self._ctx_flags: list[str] = []   # active "unvalidated" contexts
        self.stack: list[int] = []        # form/pattern xrefs being executed
        self._current_res: Resources | None = None

    # ---- object access ---------------------------------------------------
    def obj(self, xref: int):
        if xref in self._obj_cache:
            return self._obj_cache[xref]
        try:
            text = self.doc.xref_object(xref, compressed=False)
            val = parse_obj(text, self.budget)
        except ScanBudgetExceeded:
            raise
        except Exception:
            val = None
        self._obj_cache[xref] = val
        return val

    def resolve(self, v):
        for _ in range(16):
            if isinstance(v, Ref):
                v = self.obj(int(v))
            else:
                return v
        return None

    def stream(self, xref: int) -> bytes:
        try:
            data = self.doc.xref_stream(xref) or b""
        except Exception:
            return b""
        if len(data) > MAX_STREAM_BYTES:
            raise ScanBudgetExceeded("stream size")
        return data

    # ---- colour spaces ---------------------------------------------------
    def parse_cs(self, v, res: Resources, depth: int = 0) -> CS:
        if depth > 8:
            return CS("Unknown")
        key = int(v) if isinstance(v, Ref) else None
        if key is not None and key in self._cs_cache:
            return self._cs_cache[key]
        v = self.resolve(v)
        out: CS
        if isinstance(v, str):
            dev = _DEVICE_ALIASES.get(v)
            if dev is not None:
                out = dev
            else:
                named = res.lookup("ColorSpace", v)
                out = self.parse_cs(named, res, depth + 1) if named is not None else CS("Unknown")
        elif isinstance(v, list) and v and isinstance(v[0], str):
            out = self._parse_cs_array(v, res, depth)
        else:
            out = CS("Unknown")
        if key is not None:
            self._cs_cache[key] = out
        return out

    def _parse_cs_array(self, arr, res, depth) -> CS:
        fam = arr[0]
        if fam in _DEVICE_ALIASES and _DEVICE_ALIASES[fam] is not None and fam != "Pattern":
            return _DEVICE_ALIASES[fam]
        if fam == "Pattern":
            base = self.parse_cs(arr[1], res, depth + 1) if len(arr) > 1 else None
            return CS("Pattern", n=0, base=base)
        if fam == "ICCBased":
            n = 3
            if len(arr) > 1 and isinstance(arr[1], Ref):
                d = self.obj(int(arr[1]))
                if isinstance(d, dict) and isinstance(d.get("N"), int):
                    n = d["N"]
            return CS("ICCBased", n=n)
        if fam == "CalGray":
            return CS("CalGray", n=1)
        if fam == "CalRGB":
            return CS("CalRGB", n=3)
        if fam == "Lab":
            return CS("Lab", n=3)
        if fam == "Separation" and len(arr) >= 2:
            name = self.resolve(arr[1])
            return CS("Separation", names=[name if isinstance(name, str) else ""], n=1)
        if fam == "DeviceN" and len(arr) >= 2:
            names = self.resolve(arr[1])
            if not isinstance(names, list):
                names = []
            names = [self.resolve(x) if isinstance(self.resolve(x), str) else "" for x in names]
            return CS("DeviceN", names=names, n=len(names))
        if fam in ("Indexed", "I") and len(arr) >= 2:
            base = self.parse_cs(arr[1], res, depth + 1)
            return CS("Indexed", n=1, base=base)
        return CS("Unknown")

    def collect_declared(self, res: Resources):
        """Registers Separation/DeviceN colorants declared in `res` so
        unused ones can be listed as declared-but-unused."""
        marker = id(res.d)
        if marker in self._declared_seen:
            return
        self._declared_seen.add(marker)
        csd = self.resolve(res.d.get("ColorSpace"))
        if not isinstance(csd, dict):
            return
        for _name, v in csd.items():
            cs = self.parse_cs(v, res)
            self._declare(cs)

    def _declare(self, cs: CS):
        if cs.family in ("Separation", "DeviceN"):
            for n in cs.names:
                if n and n not in ("None", "All"):
                    self.declared.setdefault(n, set()).add(cs.family)
        elif cs.family in ("Indexed", "Pattern") and cs.base is not None:
            self._declare(cs.base)

    # ---- registration ----------------------------------------------------
    def _register(self, name, family, group, tint, source, state, thin_info):
        c = self.colorants.get(name)
        if c is None:
            if len(self.colorants) >= MAX_COLORANTS_PER_PAGE:
                self.flags.add("colorant_limit")
                return
            c = {
                "name": name, "families": [], "via": {}, "paints": 0,
                "tmin": None, "tmax": None, "tint_unknown": False,
                "sources": [], "ov": 0, "ko": 0, "opm": set(),
                "thin": 0, "minw": None, "flags": set(),
            }
            self.colorants[name] = c
        if family not in c["families"]:
            c["families"].append(family)
        k = (family, group)
        c["via"][k] = c["via"].get(k, 0) + 1
        c["paints"] += 1
        if tint is None:
            c["tint_unknown"] = True
        else:
            c["tmin"] = tint if c["tmin"] is None else min(c["tmin"], tint)
            c["tmax"] = tint if c["tmax"] is None else max(c["tmax"], tint)
        if source not in c["sources"]:
            c["sources"].append(source)
        is_stroke = source.endswith("stroke")
        ov = state["op_stroke"] if is_stroke else state["op_fill"]
        if ov:
            c["ov"] += 1
        else:
            c["ko"] += 1
        c["opm"].add(state["opm"])
        if thin_info is not None:
            c["thin"] += 1
            c["minw"] = thin_info if c["minw"] is None else min(c["minw"], thin_info)
        if state["transp"]:
            c["flags"].add("transparency_used")
        for cf in self._ctx_flags:
            c["flags"].add(cf)

    def _paint_cs(self, cs: CS, val, source, state, thin_info):
        """Registers one paint of colour `val` in space `cs`."""
        fam = cs.family
        if fam == "DeviceCMYK":
            comps = val if (isinstance(val, list) and len(val) >= 4) else [0, 0, 0, 1]
            for i, nm in enumerate(PROCESS_NAMES):
                t = float(comps[i])
                if t > 0:
                    self._register(nm, "DeviceCMYK", None, min(t, 1.0), source, state, thin_info)
        elif fam == "Separation":
            nm = cs.names[0] if cs.names else ""
            t = float(val[0]) if isinstance(val, list) and val else 1.0
            self._paint_named(nm, "Separation", None, t, source, state, thin_info)
        elif fam == "DeviceN":
            group = "+".join(cs.names)
            for i, nm in enumerate(cs.names):
                t = float(val[i]) if isinstance(val, list) and i < len(val) else 1.0
                self._paint_named(nm, "DeviceN", group, t, source, state, thin_info)
        elif fam == "Indexed":
            self.flags.add("indexed")
            base = cs.base
            if base is not None and base.family in ("Separation", "DeviceN", "DeviceCMYK"):
                self._paint_unknown_tint(base, source, state, thin_info)
            else:
                self._convert(cs.family)
        elif fam in ("DeviceGray", "DeviceRGB", "CalGray", "CalRGB", "Lab", "ICCBased", "Unknown"):
            if fam == "ICCBased":
                self.flags.add("icc")
            if fam == "Lab":
                self.flags.add("lab")
            self._convert(fam)

    def _paint_named(self, nm, family, group, t, source, state, thin_info):
        if nm == "None" or nm == "":
            return
        if nm == "All":
            self.flags.add("all_used")
            return
        self._register(nm, family, group, max(0.0, min(t, 1.0)), source, state, thin_info)

    def _paint_unknown_tint(self, cs: CS, source, state, thin_info):
        if cs.family == "DeviceCMYK":
            for nm in PROCESS_NAMES:
                self._register(nm, "DeviceCMYK", None, None, source, state, thin_info)
        elif cs.family == "Separation":
            self._register_unknown(cs.names[0] if cs.names else "", "Separation", None, source, state, thin_info)
        elif cs.family == "DeviceN":
            group = "+".join(cs.names)
            for nm in cs.names:
                self._register_unknown(nm, "DeviceN", group, source, state, thin_info)

    def _register_unknown(self, nm, family, group, source, state, thin_info):
        if nm in ("", "None"):
            return
        if nm == "All":
            self.flags.add("all_used")
            return
        self._register(nm, family, group, None, source, state, thin_info)

    def _convert(self, family):
        self.converted[family] = self.converted.get(family, 0) + 1

    # ---- interpreter -----------------------------------------------------
    def new_state(self):
        return {
            "fill_cs": CS_GRAY, "stroke_cs": CS_GRAY,
            "fill": [0.0], "stroke": [0.0],
            "fill_pat": None, "stroke_pat": None,
            "ctm": IDENTITY, "lw": 1.0, "dashed": False,
            "op_fill": False, "op_stroke": False, "opm": 0,
            "tr": 0, "transp": False,
        }

    def run(self, data: bytes, res: Resources, state: dict, depth: int):
        lex = Lexer(data, self.budget)
        ops: list = []
        stack: list[dict] = []
        path_open = False
        self.collect_declared(res)

        while True:
            t = lex.next()
            if t is None:
                break
            kind = t[0]
            if kind == K_OP and t[1] not in ("true", "false", "null"):
                op = t[1]
                n = ops
                ops = []
                if op == "q":
                    stack.append(dict(state))
                elif op == "Q":
                    if stack:
                        state = stack.pop()
                elif op == "cm":
                    if len(n) >= 6 and all(isinstance(x, (int, float)) for x in n[-6:]):
                        state["ctm"] = mat_mul(tuple(float(x) for x in n[-6:]), state["ctm"])
                elif op == "w":
                    if n and isinstance(n[-1], (int, float)):
                        state["lw"] = abs(float(n[-1]))
                elif op == "d":
                    if n and isinstance(n[0], list):
                        state["dashed"] = bool(n[0])
                elif op == "gs":
                    if n and isinstance(n[-1], str):
                        self._apply_gs(state, res, n[-1])
                elif op in ("m", "l", "c", "v", "y", "re", "h"):
                    path_open = True
                elif op in ("f", "F", "f*"):
                    if path_open:
                        self._paint_path(state, True, False)
                    path_open = False
                elif op in ("S", "s"):
                    if path_open:
                        self._paint_path(state, False, True)
                    path_open = False
                elif op in ("B", "B*", "b", "b*"):
                    if path_open:
                        self._paint_path(state, True, True)
                    path_open = False
                elif op == "n":
                    path_open = False
                elif op in ("W", "W*"):
                    pass
                elif op == "g":
                    self._set_color(state, False, CS_GRAY, n[-1:] if n else [0.0])
                elif op == "G":
                    self._set_color(state, True, CS_GRAY, n[-1:] if n else [0.0])
                elif op == "rg":
                    self._set_color(state, False, CS_RGB, n[-3:])
                elif op == "RG":
                    self._set_color(state, True, CS_RGB, n[-3:])
                elif op == "k":
                    self._set_color(state, False, CS_CMYK, n[-4:])
                elif op == "K":
                    self._set_color(state, True, CS_CMYK, n[-4:])
                elif op in ("cs", "CS"):
                    if n and isinstance(n[-1], str):
                        cs = self.parse_cs(n[-1], res)
                        stroke = op == "CS"
                        state["stroke_cs" if stroke else "fill_cs"] = cs
                        state["stroke" if stroke else "fill"] = initial_color(cs)
                        state["stroke_pat" if stroke else "fill_pat"] = None
                elif op in ("sc", "scn", "SC", "SCN"):
                    self._set_color_n(state, op in ("SC", "SCN"), n)
                elif op == "sh":
                    if n and isinstance(n[-1], str):
                        self._paint_shading(state, res, n[-1])
                elif op == "Do":
                    if n and isinstance(n[-1], str):
                        self._do(state, res, n[-1], depth)
                elif op == "BI":
                    self._inline_image(lex, state, res, n)
                    path_open = False
                elif op == "Tr":
                    if n and isinstance(n[-1], (int, float)):
                        state["tr"] = int(n[-1])
                elif op in ("Tj", "TJ", "'", '"'):
                    self._paint_text(state, op, n)
                elif op == "BT":
                    pass
                # remaining operators carry no ink information
                continue

            # operand
            try:
                ops.append(read_value(lex, t))
            except ScanBudgetExceeded:
                raise
            if len(ops) > 512:
                del ops[:-64]

    # ---- operator helpers ------------------------------------------------
    def _apply_gs(self, state, res, name):
        d = self.resolve(res.lookup("ExtGState", name))
        if not isinstance(d, dict):
            return
        d = {k: self.resolve(v) for k, v in d.items()}
        if "op" in d and isinstance(d["op"], bool):
            state["op_fill"] = d["op"]
            if "OP" not in d:
                state["op_stroke"] = d["op"]
        if "OP" in d and isinstance(d["OP"], bool):
            state["op_stroke"] = d["OP"]
            if "op" not in d:
                state["op_fill"] = d["OP"]
        if "OPM" in d and isinstance(d["OPM"], (int, float)):
            state["opm"] = int(d["OPM"])
        if "LW" in d and isinstance(d["LW"], (int, float)):
            state["lw"] = abs(float(d["LW"]))
        if "D" in d and isinstance(d["D"], list) and d["D"]:
            arr = self.resolve(d["D"][0])
            state["dashed"] = bool(arr) if isinstance(arr, list) else state["dashed"]
        transp = state["transp"]
        for key in ("CA", "ca"):
            v = d.get(key)
            if isinstance(v, (int, float)) and v < 1:
                transp = True
        bm = d.get("BM")
        if isinstance(bm, list) and bm:
            bm = bm[0]
        if isinstance(bm, str) and bm not in ("Normal", "Compatible"):
            transp = True
        sm = d.get("SMask")
        if sm is not None and sm != "None":
            transp = True
        if transp and not state["transp"]:
            self.flags.add("transparency")
        state["transp"] = transp

    def _set_color(self, state, stroke, cs, comps):
        vals = [float(x) for x in comps if isinstance(x, (int, float))]
        if not vals:
            vals = initial_color(cs)
        state["stroke_cs" if stroke else "fill_cs"] = cs
        state["stroke" if stroke else "fill"] = vals
        state["stroke_pat" if stroke else "fill_pat"] = None

    def _set_color_n(self, state, stroke, operands):
        cs = state["stroke_cs" if stroke else "fill_cs"]
        pat = None
        if operands and isinstance(operands[-1], str):
            pat = operands[-1]
            operands = operands[:-1]
        vals = [float(x) for x in operands if isinstance(x, (int, float)) and not isinstance(x, bool)]
        if cs.family == "Pattern":
            state["stroke_pat" if stroke else "fill_pat"] = (pat, vals)
            return
        n = max(cs.n, 1)
        if len(vals) >= n:
            vals = vals[-n:]
        elif not vals:
            vals = initial_color(cs)
        state["stroke" if stroke else "fill"] = vals

    def _thin(self, state):
        """Effective stroke width (pt) when thinner than the thin-stroke
        threshold at the base DPI, else None."""
        a, b, c, d = state["ctm"][:4]
        scale = math.sqrt(abs(a * d - b * c)) * self.user_unit
        width_pt = state["lw"] * scale
        px = width_pt * self.base_dpi / 72.0
        if px < THIN_STROKE_PX:
            self.thin_stroke_paints += 1
            self.min_stroke_width_pt = width_pt if self.min_stroke_width_pt is None \
                else min(self.min_stroke_width_pt, width_pt)
            return width_pt
        return None

    def _paint_path(self, state, fill, stroke):
        if fill:
            self._paint_current(state, False, "path")
        if stroke:
            self._paint_current(state, True, "path")

    def _paint_current(self, state, stroke, kind):
        src = kind + (":stroke" if stroke else "")
        # sources are reported without the internal ':stroke' marker
        thin = self._thin(state) if stroke else None
        pat = state["stroke_pat" if stroke else "fill_pat"]
        cs = state["stroke_cs" if stroke else "fill_cs"]
        if cs.family == "Pattern":
            if pat is not None:
                self._paint_pattern(state, pat, cs, stroke, thin)
            return
        self._paint_cs(cs, state["stroke" if stroke else "fill"], src, state, thin)

    def _paint_text(self, state, op, operands):
        has_glyphs = False
        for o in operands:
            if isinstance(o, (bytes, bytearray)) and o:
                has_glyphs = True
            elif isinstance(o, list) and any(isinstance(x, (bytes, bytearray)) and x for x in o):
                has_glyphs = True
        if not has_glyphs:
            return
        tr = state["tr"]
        if tr == 3 or tr == 7:       # invisible / clip-only
            return
        if tr in (0, 2, 4, 6):
            self._paint_current(state, False, "text")
        if tr in (1, 2, 5, 6):
            self._paint_current(state, True, "text")

    # ---- shading / patterns ----------------------------------------------
    def _function_ranges(self, fn, n, depth=0):
        """Per-component (lo, hi) outputs for an exponential/stitching
        function; None where it cannot be derived."""
        fn = self.resolve(fn)
        if depth > 5:
            return None
        if isinstance(fn, list):
            out = []
            for f in fn:
                r = self._function_ranges(f, 1, depth + 1)
                out.append(r[0] if r else None)
            return out
        if not isinstance(fn, dict):
            return None
        ft = fn.get("FunctionType")
        if ft == 2:
            c0 = self.resolve(fn.get("C0")) or [0.0]
            c1 = self.resolve(fn.get("C1")) or [1.0]
            if not (isinstance(c0, list) and isinstance(c1, list)) or len(c0) != len(c1):
                return None
            try:
                return [(min(float(a), float(b)), max(float(a), float(b))) for a, b in zip(c0, c1)]
            except (TypeError, ValueError):
                return None
        if ft == 3:
            subs = self.resolve(fn.get("Functions"))
            if not isinstance(subs, list):
                return None
            acc = None
            for s in subs:
                r = self._function_ranges(s, n, depth + 1)
                if r is None:
                    return None
                if acc is None:
                    acc = list(r)
                else:
                    acc = [None if (a is None or b is None) else (min(a[0], b[0]), max(a[1], b[1]))
                           for a, b in zip(acc, r)]
            return acc
        return None

    def _register_shading(self, sh, res, state, source):
        sh = self.resolve(sh)
        if not isinstance(sh, dict):
            return
        cs = self.parse_cs(sh.get("ColorSpace"), res)
        ranges = self._function_ranges(sh.get("Function"), cs.n) if "Function" in sh else None
        fam = cs.family
        if fam == "DeviceCMYK":
            for i, nm in enumerate(PROCESS_NAMES):
                r = ranges[i] if ranges and i < len(ranges) else None
                self._reg_range(nm, "DeviceCMYK", None, r, source, state)
        elif fam == "Separation":
            r = ranges[0] if ranges else None
            nm = cs.names[0] if cs.names else ""
            self._reg_range_named(nm, "Separation", None, r, source, state)
        elif fam == "DeviceN":
            group = "+".join(cs.names)
            for i, nm in enumerate(cs.names):
                r = ranges[i] if ranges and i < len(ranges) else None
                self._reg_range_named(nm, "DeviceN", group, r, source, state)
        elif fam == "Indexed":
            self.flags.add("indexed")
            self._convert(fam)
        else:
            if fam == "ICCBased":
                self.flags.add("icc")
            if fam == "Lab":
                self.flags.add("lab")
            self._convert(fam)

    def _reg_range_named(self, nm, family, group, r, source, state):
        if nm in ("", "None"):
            return
        if nm == "All":
            self.flags.add("all_used")
            return
        self._reg_range(nm, family, group, r, source, state)

    def _reg_range(self, nm, family, group, r, source, state):
        if r is None:
            self._register(nm, family, group, None, source, state, None)
            return
        lo, hi = max(0.0, min(1.0, r[0])), max(0.0, min(1.0, r[1]))
        if family == "DeviceCMYK" and hi <= 0:
            return
        self._register(nm, family, group, lo, source, state, None)
        if hi != lo:
            self._register(nm, family, group, hi, source, state, None)
            c = self.colorants[nm] if nm in self.colorants else None
            if c:   # one shading is a single paint, not two
                c["paints"] -= 1
                k = (family, group)
                c["via"][k] -= 1
                if state["op_fill"]:
                    c["ov"] -= 1
                else:
                    c["ko"] -= 1

    def _paint_shading(self, state, res, name):
        self._register_shading(res.lookup("Shading", name), res, state, "shading")

    def _paint_pattern(self, state, pat, cs, stroke, thin):
        name, comps = pat
        self.flags.add("pattern")
        if name is None:
            return
        self._ctx_flags.append("unvalidated:pattern")
        try:
            self._run_pattern(name, comps, cs, state, stroke)
        finally:
            self._ctx_flags.pop()

    def _run_pattern(self, name, comps, cs, state, stroke):
        res = self._current_res
        if res is None:
            return
        ref = res.lookup("Pattern", name)
        pd = self.resolve(ref)
        if not isinstance(pd, dict):
            return
        if pd.get("PatternType") == 2:
            self._register_shading(pd.get("Shading"), res, state, "pattern")
            return
        if pd.get("PatternType") != 1 or not isinstance(ref, Ref):
            return
        xref = int(ref)
        if xref in self.stack or len(self.stack) >= MAX_FORM_XOBJECT_DEPTH:
            return
        data = self.stream(xref)
        sub = self.new_state()
        sub["op_fill"], sub["op_stroke"], sub["opm"] = state["op_fill"], state["op_stroke"], state["opm"]
        sub["transp"] = state["transp"]
        if pd.get("PaintType") == 2 and cs.base is not None:
            sub["fill_cs"] = sub["stroke_cs"] = cs.base
            sub["fill"] = sub["stroke"] = list(comps) or initial_color(cs.base)
        sub["ctm"] = state["ctm"]
        pres = Resources(self, self.resolve(pd.get("Resources")), res)
        self.stack.append(xref)
        prev = self._current_res
        self._current_res = pres
        try:
            self.run(data, pres, sub, len(self.stack))
        finally:
            self._current_res = prev
            self.stack.pop()

    # ---- XObjects ----------------------------------------------------------
    def _do(self, state, res, name, depth):
        ref = res.lookup("XObject", name)
        xo = self.resolve(ref)
        if not isinstance(xo, dict) or not isinstance(ref, Ref):
            return
        sub = xo.get("Subtype")
        if sub == "Form":
            xref = int(ref)
            if xref in self.stack or len(self.stack) >= MAX_FORM_XOBJECT_DEPTH:
                return
            data = self.stream(xref)
            child = dict(state)
            child["ctm"] = mat_mul(_as_matrix(self.resolve(xo.get("Matrix"))), state["ctm"])
            grp = self.resolve(xo.get("Group"))
            if isinstance(grp, dict) and grp.get("S") == "Transparency":
                self.flags.add("transparency")
                child["transp"] = True
            fres = Resources(self, self.resolve(xo.get("Resources")), res)
            self.stack.append(xref)
            prev = self._current_res
            self._current_res = fres
            try:
                self.run(data, fres, child, depth + 1)
            finally:
                self._current_res = prev
                self.stack.pop()
        elif sub == "Image":
            self._image(state, res, xo)

    def _image(self, state, res, d, inline=False):
        self.flags.add("image")
        if not inline and (d.get("SMask") is not None or d.get("Mask") is not None):
            self.flags.add("transparency")
        is_mask = d.get("ImageMask") is True or d.get("IM") is True
        self._ctx_flags.append("unvalidated:image")
        try:
            if is_mask:
                self._paint_current(state, False, "imagemask")
                return
            csv = d.get("ColorSpace", d.get("CS"))
            if csv is None:
                return
            cs = self.parse_cs(csv, res)
            if cs.family in ("DeviceCMYK", "Separation", "DeviceN"):
                self._paint_unknown_tint(cs, "image", state, None)
            elif cs.family == "Indexed":
                self.flags.add("indexed")
                if cs.base is not None and cs.base.family in ("DeviceCMYK", "Separation", "DeviceN"):
                    self._paint_unknown_tint(cs.base, "image", state, None)
                else:
                    self._convert("Indexed")
            else:
                if cs.family == "ICCBased":
                    self.flags.add("icc")
                if cs.family == "Lab":
                    self.flags.add("lab")
                self._convert(cs.family)
        finally:
            self._ctx_flags.pop()

    def _inline_image(self, lex: Lexer, state, res, _ops):
        params = {}
        key = None
        while True:
            t = lex.next()
            if t is None:
                return
            if t[0] == K_OP and t[1] == "ID":
                break
            if t[0] == K_NAME and key is None:
                key = t[1]
                continue
            v = read_value(lex, t)
            if key is not None:
                params[key] = v
                key = None
        # Skip the single whitespace after ID, then the binary payload.
        d = lex.d
        start = lex.pos + 1 if lex.pos < lex.n and d[lex.pos] in b" \t\r\n\x00\x0c" else lex.pos
        if d[start - 1:start + 1] == b"\r\n" and d[lex.pos:lex.pos + 2] == b"\r\n":
            start = lex.pos + 2
        end = self._find_ei(d, start)
        lex.pos = end
        # abbreviations for the keys/values we use
        norm = {}
        for k, v in params.items():
            kk = {"W": "Width", "H": "Height", "BPC": "BitsPerComponent",
                  "CS": "ColorSpace", "F": "Filter", "IM": "ImageMask"}.get(k, k)
            norm[kk] = v
        abbr = {"G": "DeviceGray", "RGB": "DeviceRGB", "CMYK": "DeviceCMYK", "I": "Indexed"}
        csv = norm.get("ColorSpace")
        if isinstance(csv, str) and csv in abbr:
            norm["ColorSpace"] = abbr[csv]
        elif isinstance(csv, list) and csv and isinstance(csv[0], str) and csv[0] in abbr:
            csv = list(csv)
            csv[0] = abbr[csv[0]]
            if len(csv) > 1 and isinstance(csv[1], str) and csv[1] in abbr:
                csv[1] = abbr[csv[1]]
            norm["ColorSpace"] = csv
        self._image(state, res, norm, inline=True)

    @staticmethod
    def _find_ei(d: bytes, start: int) -> int:
        pat = re.compile(rb"(?:^|[\x00\t\n\x0c\r ])EI(?=[\x00\t\n\x0c\r ]|$)")
        p = start
        while True:
            m = pat.search(d, p)
            if m is None:
                return len(d)
            tail = d[m.end():m.end() + 16]
            if all(c < 128 and (c >= 32 or c in b"\t\n\r\x0c\x00") for c in tail):
                return m.end()
            p = m.end()


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------

def _page_resources(sc: PageScanner, page) -> Resources:
    """Page /Resources, following /Parent for inherited resources."""
    xref = page.xref
    for _ in range(32):
        d = sc.obj(xref)
        if not isinstance(d, dict):
            break
        if "Resources" in d:
            r = sc.resolve(d["Resources"])
            if isinstance(r, dict):
                return Resources(sc, r)
        parent = d.get("Parent")
        if isinstance(parent, Ref):
            xref = int(parent)
        else:
            break
    return Resources(sc, {})


def scan_page(doc, page, base_dpi: float = 150.0, user_unit: float = 1.0,
              max_tokens: int = MAX_TOKENS, max_seconds: float = MAX_SECONDS) -> dict:
    """Detects the colorants a page really paints.

    Returns:
      colorants        {name: info} for colorants painted at tint > 0 (or an
                       unknown tint: images, unevaluable gradients)
      zero_tint_only   {name: info} for colorants painted only at tint 0
      declared_unused  [{name, families}]
      converted        {family: paints} for RGB/Gray/Cal/Lab/ICC/Indexed paints
      flags            set of feature flags (transparency, image, pattern,
                       icc, lab, indexed, all_used, colorant_limit)
      thin_stroke_paints, min_stroke_width_pt
    Raises ScanBudgetExceeded when a hostile-input budget is hit.
    """
    sc = PageScanner(doc, base_dpi=base_dpi, user_unit=user_unit,
                     max_tokens=max_tokens, max_seconds=max_seconds)
    res = _page_resources(sc, page)
    sc._current_res = res
    data = page.read_contents()
    if len(data) > MAX_STREAM_BYTES:
        raise ScanBudgetExceeded("stream size")
    try:
        sc.run(data, res, sc.new_state(), 0)
    except RecursionError:
        raise ScanBudgetExceeded("recursion")

    used, zero = {}, {}
    for name, c in sc.colorants.items():
        info = _finish(c)
        known_zero = (not c["tint_unknown"]) and c["tmax"] is not None and c["tmax"] <= 0
        (zero if known_zero else used)[name] = info
    declared = [
        {"name": n, "families": sorted(f)}
        for n, f in sc.declared.items()
        if n not in sc.colorants and n not in PROCESS_NAMES   # process inks always exist
    ]
    return {
        "colorants": used,
        "zero_tint_only": zero,
        "declared_unused": declared,
        "converted": dict(sc.converted),
        "flags": set(sc.flags),
        "thin_stroke_paints": sc.thin_stroke_paints,
        "min_stroke_width_pt": sc.min_stroke_width_pt,
    }


def _finish(c: dict) -> dict:
    srcs = []
    for s in c["sources"]:
        s = s.split(":")[0]
        if s not in srcs:
            srcs.append(s)
    via = [
        {"family": fam, "devicen_group": grp, "paints": cnt}
        for (fam, grp), cnt in c["via"].items()
    ]
    tint = None
    if c["tmin"] is not None:
        tint = {"min": round(c["tmin"], 4), "max": round(c["tmax"], 4)}
    return {
        "name": c["name"],
        "families": list(c["families"]),
        "used_via": via,
        "tint": tint,
        "tint_unknown": c["tint_unknown"],
        "paint": {
            "sources": srcs,
            "overprint_paints": c["ov"],
            "knockout_paints": c["ko"],
            "opm": sorted(c["opm"]),
        },
        "thin_stroke_paints": c["thin"],
        "min_stroke_width_pt": None if c["minw"] is None else round(c["minw"], 4),
        "flags": sorted(c["flags"]),
    }
