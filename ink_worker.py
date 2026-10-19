"""
BoxCheck Ink Coverage — isolated worker process.

    python -m ink_worker <in.pdf> <out.json> [--workdir DIR] [--pages 1,2,3] [--deadline SECONDS]

Runs the whole analysis (PyMuPDF content parsing + Ghostscript) outside the
API process: MuPDF is C code parsing hostile streams, and a segfault or
decompression bomb must not take uvicorn down. ink_runner.py launches this
under `prlimit --as=3 GB --cpu=60`; it also applies the same limits to
itself (setrlimit — no preexec_fn) as defence in depth. The output file is
rewritten atomically after every page, so a hard kill by the runner still
leaves a valid partial result.
"""

from __future__ import annotations

import json
import os
import resource
import sys
import tempfile

AS_LIMIT_BYTES = 3 * 1024 ** 3
CPU_LIMIT_SECONDS = 60


def _apply_limits() -> None:
    if os.environ.get("INK_NO_SELF_RLIMIT"):
        return
    for res, lim in ((resource.RLIMIT_AS, AS_LIMIT_BYTES), (resource.RLIMIT_CPU, CPU_LIMIT_SECONDS)):
        soft, hard = resource.getrlimit(res)
        if hard != resource.RLIM_INFINITY:
            lim = min(lim, hard)
        resource.setrlimit(res, (lim, hard if hard != resource.RLIM_INFINITY else lim))


def _write_json(path: str, obj: dict) -> None:
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".ink-out-", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: ink_worker in.pdf out.json [--workdir DIR] [--pages 1,2] [--deadline S]", file=sys.stderr)
        return 2
    in_path, out_path = argv[1], argv[2]
    workdir = None
    pages = None
    deadline = None
    i = 3
    while i < len(argv):
        a = argv[i]
        if a == "--workdir":
            workdir = argv[i + 1]; i += 2
        elif a == "--pages":
            pages = [int(x) for x in argv[i + 1].split(",") if x]; i += 2
        elif a == "--deadline":
            deadline = float(argv[i + 1]); i += 2
        else:
            print("unknown argument", a, file=sys.stderr)
            return 2

    _apply_limits()
    # imported after the limits are in place so imports count against them
    from pathlib import Path
    from ink_coverage import InkError, analyze_ink_coverage, TOTAL_DEADLINE_S

    with open(in_path, "rb") as f:
        pdf_bytes = f.read()
    opts = {"pages": pages, "deadline_s": deadline if deadline is not None else TOTAL_DEADLINE_S}
    if workdir:
        opts["workdir"] = Path(workdir)
    try:
        result = analyze_ink_coverage(pdf_bytes, opts, progress=lambda r: _write_json(out_path, r))
        _write_json(out_path, result)
    except InkError as e:
        _write_json(out_path, {"error": {"code": e.code, "message": e.message}})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
