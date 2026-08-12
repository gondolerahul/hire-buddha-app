"""Video tool split — Phase 12 `03`.

Covers the three composable tools (``video_generate`` / ``video_edit`` /
``video_add_sound``), the shared ffmpeg helper argv construction, and the
deprecated ``video_generation`` shim. ffmpeg is not installed on CI hosts, so
every ffmpeg/ffprobe call is routed through a fake ``run_sandbox_exec`` that
records argv — we assert on the commands built, not on real encoding.
"""
from __future__ import annotations

import json
from typing import Any, List, Optional, Sequence

import pytest

from src.ai.tools.base import ToolRegistry, ToolStatus
from src.ai.tools.media.video import _ffmpeg, _support
from src.ai.tools.media.video.video_add_sound import VideoAddSoundTool
from src.ai.tools.media.video.video_edit import VideoEditTool
from src.ai.tools.media.video.video_generate import VideoGenerateTool
from src.ai.tools.sandbox.runtime import ExecResult


class _FakeExec:
    """Records every (argv) it is asked to run; returns a canned ExecResult."""

    def __init__(self, *, stdout: str = "3.5\n", returncode: int = 0) -> None:
        self.calls: List[List[str]] = []
        self._stdout = stdout
        self._returncode = returncode

    async def __call__(
        self,
        context: Any,
        argv: Sequence[str],
        *,
        cwd: Optional[str] = None,
        timeout: float = 30.0,
        env: Any = None,
    ) -> ExecResult:
        self.calls.append(list(argv))
        return ExecResult(returncode=self._returncode, stdout=self._stdout)

    @property
    def last(self) -> List[str]:
        return self.calls[-1]


@pytest.fixture()
def fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> _FakeExec:
    fake = _FakeExec()
    monkeypatch.setattr(_ffmpeg, "run_sandbox_exec", fake)
    return fake


def _make_clip(tmp_path, name: str) -> str:
    p = tmp_path / name
    p.write_bytes(b"\x00\x00")  # presence only; ffmpeg is faked
    return str(p)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
def test_three_tools_registered_and_shim_deprecated() -> None:
    import src.ai.tools  # noqa: F401  (triggers registration)

    assert isinstance(ToolRegistry.get_tool("video_generate"), VideoGenerateTool)
    assert isinstance(ToolRegistry.get_tool("video_edit"), VideoEditTool)
    assert isinstance(ToolRegistry.get_tool("video_add_sound"), VideoAddSoundTool)
    shim = ToolRegistry.get_tool("video_generation")
    assert shim is not None and shim.status == ToolStatus.DEPRECATED


# --------------------------------------------------------------------------- #
# _ffmpeg helpers — argv construction
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_concat_single_clip_remuxes(fake_ffmpeg: _FakeExec, tmp_path) -> None:
    out = str(tmp_path / "out.mp4")
    await _ffmpeg.concat_clips(None, [_make_clip(tmp_path, "a.mp4")], out)
    assert fake_ffmpeg.last[:2] == ["ffmpeg", "-y"]
    assert "-c" in fake_ffmpeg.last and "copy" in fake_ffmpeg.last
    assert fake_ffmpeg.last[-1] == out


@pytest.mark.asyncio
async def test_concat_multi_uses_concat_demuxer(fake_ffmpeg: _FakeExec, tmp_path) -> None:
    out = str(tmp_path / "out.mp4")
    clips = [_make_clip(tmp_path, "a.mp4"), _make_clip(tmp_path, "b.mp4")]
    await _ffmpeg.concat_clips(None, clips, out)
    assert "concat" in fake_ffmpeg.last  # -f concat
    # The concat list file is cleaned up afterward.
    leftover = list(tmp_path.glob("concat_*.txt"))
    assert leftover == []


@pytest.mark.asyncio
async def test_concat_reencodes_on_copy_failure(monkeypatch, tmp_path) -> None:
    calls: List[List[str]] = []

    async def flaky(context, argv, *, cwd=None, timeout=30.0, env=None):
        calls.append(list(argv))
        # First (copy) attempt fails; the re-encode retry succeeds.
        ok = "libx264" in argv
        return ExecResult(returncode=0 if ok else 1, stderr="codec mismatch")

    monkeypatch.setattr(_ffmpeg, "run_sandbox_exec", flaky)
    out = str(tmp_path / "out.mp4")
    clips = [_make_clip(tmp_path, "a.mp4"), _make_clip(tmp_path, "b.mp4")]
    await _ffmpeg.concat_clips(None, clips, out)
    assert any("libx264" in c for c in calls)


@pytest.mark.asyncio
async def test_run_ffmpeg_raises_on_failure(monkeypatch) -> None:
    async def boom(context, argv, *, cwd=None, timeout=30.0, env=None):
        return ExecResult(returncode=1, stderr="bad args")

    monkeypatch.setattr(_ffmpeg, "run_sandbox_exec", boom)
    with pytest.raises(_ffmpeg.FFmpegError):
        await _ffmpeg.run_ffmpeg(None, ["-i", "x"])


@pytest.mark.asyncio
async def test_probe_duration_parses_stdout(fake_ffmpeg: _FakeExec) -> None:
    dur = await _ffmpeg.probe_duration(None, "clip.mp4")
    assert dur == pytest.approx(3.5)
    assert fake_ffmpeg.last[0] == "ffprobe"


# --------------------------------------------------------------------------- #
# _support — segment math
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("total", [3, 5, 8, 20, 17])
def test_calculate_segments_cover_duration(total: int) -> None:
    segs = _support.calculate_segments(total)
    assert all(s in (4, 5, 6, 8) for s in segs)
    # Segments cover at least the requested duration (small remainders < 4s are
    # rounded up to a 4s segment — preserved legacy behavior).
    assert sum(segs) >= total
    assert sum(segs) - total < 4


# --------------------------------------------------------------------------- #
# video_edit — routing + validation
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_edit_extend_is_pure_planning(fake_ffmpeg: _FakeExec) -> None:
    tool = VideoEditTool()
    res = json.loads(await tool.run(json.dumps({"operation": "extend", "length_seconds": 20})))
    assert res["operation"] == "extend"
    assert sum(res["segment_plan"]) == 20
    assert fake_ffmpeg.calls == []  # no ffmpeg for a planning op


@pytest.mark.asyncio
async def test_edit_concat_invokes_ffmpeg(fake_ffmpeg: _FakeExec, tmp_path) -> None:
    tool = VideoEditTool()
    clips = [_make_clip(tmp_path, "a.mp4"), _make_clip(tmp_path, "b.mp4")]
    out = str(tmp_path / "merged.mp4")
    res = json.loads(
        await tool.run(json.dumps({"operation": "concat", "inputs": clips, "output_path": out}))
    )
    assert res["video_path"] == out
    assert fake_ffmpeg.calls  # ffmpeg ran


@pytest.mark.asyncio
async def test_edit_unknown_operation_errors() -> None:
    tool = VideoEditTool()
    res = json.loads(await tool.run(json.dumps({"operation": "frobnicate"})))
    assert "error" in res


@pytest.mark.asyncio
async def test_edit_trim_requires_one_input(fake_ffmpeg: _FakeExec, tmp_path) -> None:
    tool = VideoEditTool()
    clips = [_make_clip(tmp_path, "a.mp4"), _make_clip(tmp_path, "b.mp4")]
    res = json.loads(await tool.run(json.dumps({"operation": "trim", "inputs": clips})))
    assert "error" in res


@pytest.mark.asyncio
async def test_edit_missing_input_file_errors() -> None:
    tool = VideoEditTool()
    res = json.loads(
        await tool.run(json.dumps({"operation": "concat", "inputs": ["/nope/missing.mp4"]}))
    )
    assert "not found" in res["error"]


# --------------------------------------------------------------------------- #
# video_generate — validation paths (no genai/DB needed)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_generate_rejects_over_single_segment() -> None:
    tool = VideoGenerateTool()
    res = json.loads(
        await tool.run(json.dumps({"prompt": "a cat", "length_seconds": 20}))
    )
    assert res["error"] == "length_exceeds_single_segment"
    assert res["max_segment_seconds"] == _support.MAX_SEGMENT_SECONDS


@pytest.mark.asyncio
async def test_generate_requires_prompt() -> None:
    tool = VideoGenerateTool()
    res = json.loads(await tool.run(json.dumps({"length_seconds": 5})))
    assert "error" in res


# --------------------------------------------------------------------------- #
# video_add_sound — routing + validation + mux argv
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_add_sound_replace_builds_mux(fake_ffmpeg: _FakeExec, tmp_path) -> None:
    tool = VideoAddSoundTool()
    video = _make_clip(tmp_path, "v.mp4")
    audio = _make_clip(tmp_path, "a.m4a")
    out = str(tmp_path / "withsound.mp4")
    res = json.loads(
        await tool.run(
            json.dumps(
                {
                    "video_path": video,
                    "source": "file",
                    "mode": "replace",
                    "audio_path": audio,
                    "output_path": out,
                }
            )
        )
    )
    assert res["video_path"] == out
    argv = fake_ffmpeg.last
    assert "-map" in argv and "0:v" in argv  # keeps the source video stream
    assert argv[-1] == out


@pytest.mark.asyncio
async def test_add_sound_tts_unavailable_is_structured(tmp_path) -> None:
    tool = VideoAddSoundTool()
    video = _make_clip(tmp_path, "v.mp4")
    res = json.loads(
        await tool.run(json.dumps({"video_path": video, "source": "tts", "text": "hi"}))
    )
    assert res["error"] == "tts_provider_unavailable"


@pytest.mark.asyncio
async def test_add_sound_missing_audio_file_errors(tmp_path) -> None:
    tool = VideoAddSoundTool()
    video = _make_clip(tmp_path, "v.mp4")
    res = json.loads(
        await tool.run(
            json.dumps({"video_path": video, "source": "file", "audio_path": "/nope.m4a"})
        )
    )
    assert "error" in res


# --------------------------------------------------------------------------- #
# Deprecated shim — delegates
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_shim_single_segment_delegates_to_generate(monkeypatch) -> None:
    from src.ai.tools.media.video_generation import VideoGenerationTool

    shim = VideoGenerationTool()
    captured = {}

    async def fake_generate(input_data, context=None):
        captured["input"] = input_data
        return json.dumps({"video_path": "/x.mp4", "duration_seconds": 5})

    monkeypatch.setattr(shim._generate, "run_with_context", fake_generate)
    out = json.loads(
        await shim.run(json.dumps({"prompt": "cat", "length_seconds": 5}))
    )
    assert out["video_path"] == "/x.mp4"
    assert "cat" in captured["input"]
