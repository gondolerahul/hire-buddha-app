"""GW-09: the run stream's headers are ones the deployment's proxy honours.

The stream sat behind Apache with ``X-Accel-Buffering: no`` — an nginx-only
header that did nothing there, while ``setup_apache.sh`` enables mod_deflate.
``Cache-Control: no-transform`` is the standard way to keep an intermediary
from compressing or buffering the frames.
"""
from __future__ import annotations

from src.ai.router import SSE_HEADERS


def test_the_stream_is_not_cached_or_transformed() -> None:
    directives = {d.strip() for d in SSE_HEADERS["Cache-Control"].split(",")}
    assert {"no-cache", "no-transform"} <= directives


def test_no_nginx_only_header() -> None:
    assert "X-Accel-Buffering" not in SSE_HEADERS
