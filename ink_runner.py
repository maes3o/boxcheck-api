"""
BoxCheck Ink Coverage — async runner for the isolated worker.

    result = await run_ink_analysis(pdf_bytes, pages=None)

Responsibilities: concurrency slot (Semaphore, INK_MAX_CONCURRENCY, default
min(2, cores-1); waits at most 5 s, otherwise InkBusy -> HTTP 503), free-disk
guard, per-request temp directory removed in `finally`, spawn of
`prlimit --as=3GB --cpu=60 python -m ink_worker` in its own session,
55 s total deadline with process-group kill, and salvage of the worker's
partial output (unfinished pages come back as skipped_timeout, not an error).

The default thread pool is never used, so /check cannot be starved.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path

from ink_coverage import InkError, TOTAL_DEADLINE_S

logger = logging.getLogger("boxcheck.ink_runner")

TMP_PREFIX = "boxcheck-ink-"
SLOT_WAIT_S = 5.0
WORKER_MARGIN_S = 2.0          # worker's own deadline is this much before the hard kill
AS_LIMIT_BYTES = 3 * 1024 ** 3
CPU_LIMIT_SECONDS = 60
MIN_FREE_BYTES = 2 * 1024 ** 3
THIRD_PIXEL_BUDGET_BYTES = 3 * 40_000_000
STDERR_CAP = 64 * 1024
STALE_TMP_AGE_S = 3600
HERE = Path(__file__).resolve().parent


class InkBusy(Exception):
    def __init__(self, retry_after: int = 10):
        super().__init__("busy")
        self.retry_after = retry_after


class InkTimeout(Exception):
    pass


class InkWorkerCrash(Exception):
    pass


def max_concurrency() -> int:
    env = os.environ.get("INK_MAX_CONCURRENCY")
    if env:
        try:
            return max(1, int(env))
        except ValueError:
            pass
    return max(1, min(2, (os.cpu_count() or 1) - 1))


_semaphore: asyncio.Semaphore | None = None


def _sem() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max_concurrency())
    return _semaphore


def sweep_stale_tempdirs(max_age_s: float = STALE_TMP_AGE_S, base: str | None = None) -> int:
    """Deletes boxcheck-ink-* directories older than `max_age_s` (covers a
    SIGKILLed or restarted API). Returns how many were removed."""
    base = base or tempfile.gettempdir()
    removed = 0
    now = time.time()
    try:
        entries = list(os.scandir(base))
    except OSError:
        return 0
    for e in entries:
        if e.is_dir(follow_symlinks=False) and e.name.startswith(TMP_PREFIX):
            try:
                if now - e.stat(follow_symlinks=False).st_mtime > max_age_s:
                    shutil.rmtree(e.path, ignore_errors=True)
                    removed += 1
            except OSError:
                pass
    return removed


def _enough_disk(path: str) -> bool:
    try:
        return shutil.disk_usage(path).free >= max(MIN_FREE_BYTES, THIRD_PIXEL_BUDGET_BYTES)
    except OSError:
        return True


def _worker_cmd(in_pdf: Path, out_json: Path, workdir: Path, pages, worker_deadline: float) -> list[str]:
    cmd = [sys.executable, "-m", "ink_worker", str(in_pdf), str(out_json),
           "--workdir", str(workdir), "--deadline", f"{worker_deadline:.1f}"]
    if pages:
        cmd += ["--pages", ",".join(str(p) for p in pages)]
    prlimit = shutil.which("prlimit")
    if prlimit:
        cmd = [prlimit, f"--as={AS_LIMIT_BYTES}", f"--cpu={CPU_LIMIT_SECONDS}"] + cmd
    return cmd


def _kill_group(proc) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _read_result(out_json: Path):
    try:
        return json.loads(out_json.read_text())
    except (OSError, ValueError):
        return None


async def run_ink_analysis(pdf_bytes: bytes, pages: list[int] | None = None) -> dict:
    t0 = time.monotonic()
    sem = _sem()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=SLOT_WAIT_S)
    except asyncio.TimeoutError:
        raise InkBusy()
    try:
        tmp_base = tempfile.gettempdir()
        if not _enough_disk(tmp_base):
            raise InkBusy()
        reqdir = Path(tempfile.mkdtemp(prefix=TMP_PREFIX))
        proc = None
        try:
            in_pdf = reqdir / "request.pdf"
            out_json = reqdir / "result.json"
            workdir = reqdir / "work"
            workdir.mkdir()
            in_pdf.write_bytes(pdf_bytes)

            remaining = TOTAL_DEADLINE_S - (time.monotonic() - t0)
            cmd = _worker_cmd(in_pdf, out_json, workdir, pages, max(remaining - WORKER_MARGIN_S, 5.0))
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(HERE), env=env, start_new_session=True,
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _o, err = await asyncio.wait_for(proc.communicate(), timeout=max(remaining, 1.0))
            except asyncio.TimeoutError:
                _kill_group(proc)
                await proc.wait()
                partial = _read_result(out_json)
                if isinstance(partial, dict) and "pages" in partial:
                    return _mark_incomplete(partial)
                raise InkTimeout()

            _kill_group(proc)   # reap any stray Ghostscript left in the group
            result = _read_result(out_json)
            if proc.returncode != 0 or result is None:
                logger.warning("ink worker failed rc=%s stderr=%s", proc.returncode,
                               (err or b"")[:STDERR_CAP].decode("latin-1", "replace")[-500:])
                raise InkWorkerCrash()
            if "error" in result:
                e = result["error"]
                raise InkError(e.get("code", "invalid_pdf"), e.get("message", ""))
            return result
        finally:
            if proc is not None and proc.returncode is None:
                _kill_group(proc)
            shutil.rmtree(reqdir, ignore_errors=True)
    finally:
        sem.release()


def _mark_incomplete(result: dict) -> dict:
    doc = result.get("document", {})
    doc["complete"] = False
    return result
