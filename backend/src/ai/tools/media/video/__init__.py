"""Composable video tools (Phase 12 `03`).

The legacy ``video_generation`` mega-tool did three jobs in one (generate,
split/merge, audio). This package splits them into three independently
invocable, individually cost-attributed tools so a planner can express
"generate N segments → ``video_edit`` concat → ``video_add_sound`` narration"
as an explicit, inspectable multi-step plan:

* :class:`~src.ai.tools.media.video.video_generate.VideoGenerateTool`
  (``video_generate``) — AI generation of a single segment.
* :class:`~src.ai.tools.media.video.video_edit.VideoEditTool`
  (``video_edit``) — ffmpeg-only clip composition (concat/trim/extend/resize).
* :class:`~src.ai.tools.media.video.video_add_sound.VideoAddSoundTool`
  (``video_add_sound``) — attach / mix an audio track onto a clip.

All ffmpeg work routes through :mod:`._ffmpeg`, which runs inside the per-tenant
container (`02`) when enabled and is metered as compute (not LLM).
"""
from src.ai.tools.media.video.video_add_sound import VideoAddSoundTool
from src.ai.tools.media.video.video_edit import VideoEditTool
from src.ai.tools.media.video.video_generate import VideoGenerateTool

__all__ = ["VideoGenerateTool", "VideoEditTool", "VideoAddSoundTool"]
