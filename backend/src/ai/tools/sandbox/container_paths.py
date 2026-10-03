r"""Where a host path is inside a tenant container (TL-16).

On a Linux host a tenant's directories are mounted at their own paths, so a
path means the same thing on both sides and nothing is translated. A Windows
host (development) cannot do that — ``C:\...`` is not a path in a Linux
container — so each directory is mounted under ``/host/<drive>/...`` and the
runtime translates: host paths in an exec's argv, working directory and
environment going in, container paths in its output coming back.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, List

__all__ = ["container_path", "mount_args", "to_container_text", "to_host_text"]

_TRANSLATE = os.name == "nt"


def container_path(host_path: str) -> str:
    """The path ``host_path`` is mounted at inside the container."""
    if not _TRANSLATE:
        return host_path
    drive, rest = os.path.splitdrive(os.path.abspath(host_path))
    return "/host/" + drive.rstrip(":").lower() + rest.replace("\\", "/")


def _root_pattern(root: str) -> "re.Pattern[str]":
    parts = [re.escape(p) for p in re.split(r"[\\/]+", os.path.abspath(root)) if p]
    # The root, then the rest of a path up to whitespace or a quote.
    return re.compile(r"[\\/]+".join(parts) + r"""(?:[\\/][^\s"'`<>|;]*)?""", re.IGNORECASE)


def to_container_text(text: str, roots: Iterable[str]) -> str:
    """``text`` with every path under one of ``roots`` written as its container path."""
    if not _TRANSLATE or not text:
        return text
    for root in roots:
        text = _root_pattern(root).sub(lambda m: container_path(m.group(0)), text)
    return text


def to_host_text(text: str, roots: Iterable[str]) -> str:
    """``text`` with each root's container path written back as the host path."""
    if not _TRANSLATE or not text:
        return text
    for root in sorted(roots, key=len, reverse=True):
        text = text.replace(container_path(root), os.path.abspath(root))
    return text


def mount_args(roots: List[tuple[str, bool]]) -> List[str]:
    """``-v`` arguments for ``(host directory, read_only)`` pairs."""
    args: List[str] = []
    for host_dir, read_only in roots:
        os.makedirs(host_dir, exist_ok=True)
        args += ["-v", f"{os.path.abspath(host_dir)}:{container_path(host_dir)}{':ro' if read_only else ''}"]
    return args
