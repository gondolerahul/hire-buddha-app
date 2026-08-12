"""Shared ffmpeg / ffprobe helpers for the video tools (Phase 12 `03`).

Every ffmpeg invocation routes through :func:`run_sandbox_exec` so it runs
inside the per-tenant container (`02`) when enabled, falls back to the host
subprocess otherwise, and is cost-attributed as *compute* (not LLM) in one
place. The tools build the operation (which clips, which params); this module
owns argv construction, the concat-list plumbing, and error surfacing.

Because tenant files live on the bind-mount at an identical host/container path
(`02` S4), the concat list and all input/output paths are valid in either
runtime — nothing here needs to know which runtime it got.
"""
from __future__ import annotations

import os
import uuid
from typing import Any, List, Mapping, Optional, Sequence

from src.ai.tools.sandbox.runtime import ExecResult, run_sandbox_exec


class FFmpegError(RuntimeError):
    """An ffmpeg/ffprobe invocation failed, timed out, or could not launch."""


def _describe_failure(verb: str, res: ExecResult) -> str:
    if res.not_found:
        return f"{verb} not available in the sandbox runtime"
    if res.launch_error:
        return f"{verb} failed to launch: {res.launch_error}"
    if res.timed_out:
        return f"{verb} timed out"
    tail = (res.stderr or "").strip().splitlines()[-3:]
    return f"{verb} exited {res.returncode}: {' / '.join(tail)}"


async def run_ffmpeg(
    context: Optional[Mapping[str, Any]],
    args: Sequence[str],
    *,
    timeout: float = 300.0,
) -> ExecResult:
    """Run ``ffmpeg -y <args>`` through the metered sandbox runtime.

    Raises :class:`FFmpegError` on any non-success outcome so callers can wrap a
    single ``except FFmpegError``.
    """
    argv = ["ffmpeg", "-y", *args]
    res = await run_sandbox_exec(context, argv, timeout=timeout)
    if not res.ok:
        raise FFmpegError(_describe_failure("ffmpeg", res))
    return res


async def probe_duration(
    context: Optional[Mapping[str, Any]],
    path: str,
    *,
    timeout: float = 30.0,
) -> Optional[float]:
    """Return the media duration in seconds via ffprobe, or ``None`` if unknown."""
    argv = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    res = await run_sandbox_exec(context, argv, timeout=timeout)
    if not res.ok:
        return None
    try:
        return float((res.stdout or "").strip())
    except (TypeError, ValueError):
        return None


def _write_concat_list(inputs: Sequence[str], work_dir: str) -> str:
    """Write an ffmpeg concat-demuxer list file and return its path."""
    os.makedirs(work_dir, exist_ok=True)
    concat_path = os.path.join(work_dir, f"concat_{uuid.uuid4().hex[:8]}.txt")
    with open(concat_path, "w", encoding="utf-8") as fh:
        for clip in inputs:
            # The demuxer requires single-quoted absolute paths with internal
            # quotes escaped per its mini-format.
            safe = os.path.abspath(clip).replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")
    return concat_path


async def concat_clips(
    context: Optional[Mapping[str, Any]],
    inputs: Sequence[str],
    output_path: str,
    *,
    work_dir: Optional[str] = None,
    timeout: float = 300.0,
) -> str:
    """Concatenate ``inputs`` (in order) into ``output_path``.

    Tries the no-reencode concat demuxer first (stream copy, fast); on failure
    — clips with mismatched codecs/params — falls back to re-encoding. Returns
    ``output_path``.
    """
    if not inputs:
        raise FFmpegError("concat requires at least one input clip")
    if len(inputs) == 1:
        # Single clip: re-mux to the requested container/name without re-encode.
        await run_ffmpeg(
            context, ["-i", inputs[0], "-c", "copy", output_path], timeout=timeout
        )
        return output_path

    work = work_dir or os.path.dirname(os.path.abspath(output_path))
    concat_path = _write_concat_list(inputs, work)
    try:
        try:
            await run_ffmpeg(
                context,
                ["-f", "concat", "-safe", "0", "-i", concat_path, "-c", "copy", output_path],
                timeout=timeout,
            )
        except FFmpegError:
            await run_ffmpeg(
                context,
                [
                    "-f", "concat", "-safe", "0", "-i", concat_path,
                    "-c:v", "libx264", "-c:a", "aac", output_path,
                ],
                timeout=timeout,
            )
    finally:
        if os.path.exists(concat_path):
            os.remove(concat_path)
    return output_path


async def trim_clip(
    context: Optional[Mapping[str, Any]],
    input_path: str,
    output_path: str,
    *,
    start: float = 0.0,
    duration: Optional[float] = None,
    end: Optional[float] = None,
    timeout: float = 300.0,
) -> str:
    """Cut ``input_path`` to ``[start, start+duration]`` (or ``[start, end]``)."""
    args: List[str] = ["-ss", f"{max(0.0, start):g}", "-i", input_path]
    if duration is not None:
        args += ["-t", f"{max(0.0, duration):g}"]
    elif end is not None:
        args += ["-to", f"{max(0.0, end):g}"]
    args += ["-c", "copy", output_path]
    try:
        await run_ffmpeg(context, args, timeout=timeout)
    except FFmpegError:
        # Stream-copy can't cut at arbitrary points (keyframe boundaries); the
        # accurate path re-encodes.
        reenc = list(args)
        reenc[-2:-1] = []  # drop "-c"
        reenc.remove("copy")
        reenc[-1:-1] = ["-c:v", "libx264", "-c:a", "aac"]
        await run_ffmpeg(context, reenc, timeout=timeout)
    return output_path


async def resize_clip(
    context: Optional[Mapping[str, Any]],
    input_path: str,
    output_path: str,
    *,
    width: int,
    height: int,
    timeout: float = 300.0,
) -> str:
    """Re-scale ``input_path`` to ``width``×``height`` (``-1`` keeps aspect)."""
    await run_ffmpeg(
        context,
        ["-i", input_path, "-vf", f"scale={width}:{height}", "-c:a", "copy", output_path],
        timeout=timeout,
    )
    return output_path
