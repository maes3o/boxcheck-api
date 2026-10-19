"""Minimal InkProbe backend bridge tests for /check/ink-preview.

Covers only the additive probe contract:
- both probe_x+probe_y supplied -> wrapper gets --probe-ink, response has ink_probe
- only one supplied -> HTTP 422
- no probe -> existing response shape, no ink_probe key
- malformed/missing probe stdout -> preview fallback intact, no ink_probe
"""
import io
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pymupdf
from fastapi.testclient import TestClient
from PIL import Image

import main

PROBE_JSON_LINE = (
    '{"x":10,"y":20,"source":"cmyk-buffer",'
    '"cmyk":[0.75,0,1,0],'
    '"spots":{"White-1":0.5},'
    '"alpha":1,"srgb":[47,181,73]}'
)


def _tiny_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=200, height=200)
    page.insert_text((20, 20), "probe", fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data


def _fake_run_factory(stdout: bytes, returncode: int = 0):
    def _fake_run(cmd, **kwargs):
        output_path = Path(cmd[2])
        img = Image.new("RGB", (50, 40), color=(10, 20, 30))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        output_path.write_bytes(buf.getvalue())
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=b"")

    return _fake_run


def test_probe_x_without_y_is_422():
    client = TestClient(main.app)
    res = client.post(
        "/check/ink-preview?probe_x=10",
        files={"file": ("test.pdf", _tiny_pdf_bytes(), "application/pdf")},
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "incomplete_probe_coordinate"


def test_probe_y_without_x_is_422():
    client = TestClient(main.app)
    res = client.post(
        "/check/ink-preview?probe_y=20",
        files={"file": ("test.pdf", _tiny_pdf_bytes(), "application/pdf")},
    )
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "incomplete_probe_coordinate"


def test_no_probe_returns_existing_shape():
    result = main._render_ink_preview_sync(_tiny_pdf_bytes(), 0, [], [])
    assert set(result.keys()) == {"url", "width_px", "height_px", "scale"}
    assert "ink_probe" not in result


def test_probe_success_response_shape_and_cmd():
    seen_cmds = []

    def _fake_run(cmd, **kwargs):
        seen_cmds.append(list(cmd))
        return _fake_run_factory(PROBE_JSON_LINE.encode())(cmd, **kwargs)

    with patch("main.subprocess.run", side_effect=_fake_run):
        result = main._render_ink_preview_sync(
            _tiny_pdf_bytes(), 0, ["White-1"], [], probe_x=10, probe_y=20,
        )
    assert seen_cmds and "--probe-ink" in seen_cmds[0]
    assert seen_cmds[0][seen_cmds[0].index("--probe-ink") + 1] == "10,20"
    assert set(result.keys()) == {"url", "width_px", "height_px", "scale", "ink_probe"}
    probe = result["ink_probe"]
    assert probe["x"] == 10 and probe["y"] == 20
    assert probe["source"] == "cmyk-buffer"
    assert probe["cmyk"] == [0.75, 0, 1, 0]
    assert probe["spots"] == {"White-1": 0.5}
    assert probe["alpha"] == 1
    assert probe["srgb"] == [47, 181, 73]


def test_malformed_probe_stdout_does_not_break_preview():
    with patch(
        "main.subprocess.run",
        side_effect=_fake_run_factory(b"not json at all\n"),
    ):
        result = main._render_ink_preview_sync(
            _tiny_pdf_bytes(), 0, ["White-1"], [], probe_x=10, probe_y=20,
        )
    assert set(result.keys()) == {"url", "width_px", "height_px", "scale"}
    assert "ink_probe" not in result
    assert result["url"].startswith("data:image/png;base64,")


def test_wrapper_failure_with_probe_falls_back_to_preview():
    with patch(
        "main.subprocess.run",
        side_effect=_fake_run_factory(b"", returncode=1),
    ):
        result = main._render_ink_preview_sync(
            _tiny_pdf_bytes(), 0, ["White-1"], [], probe_x=10, probe_y=20,
        )
    assert set(result.keys()) == {"url", "width_px", "height_px", "scale"}
    assert "ink_probe" not in result
