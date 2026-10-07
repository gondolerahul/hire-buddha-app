# 03 — Decompose the Video Generation Tool

> Scope item 3. `tools/video_generation.py` (590 LoC) currently does three
> distinct jobs in one tool. Split it into three composable tools so the agent
> (and the planner) can reason about, sequence, and cost each independently.

---

## 1. Current state (audited)

`VideoGenerationTool` (`name="video_generation"`, `status=EXPERIMENTAL`) is a
single tool wrapping Google Veo 3.1 that today:

1. **Generates** video from a text prompt (and optional start/end reference
   frames) — `_generate_single_video`, `_resolve_vertex_metadata`.
2. **Splits & merges** — for durations > 8s it computes segments
   (`_calculate_segments`), generates each, and **merges them with ffmpeg
   concat** (`_merge_videos`), including a "video extension" mode where each
   segment extends the previous clip.
3. **Adds sound** — audio is a boolean flag (`is_audio_required`) passed through
   to the Veo API (model-generated audio only; no separate score/voiceover/SFX
   track, no mixing).

Plus cost logging (`_record_video_billing`) and artifact registration
(`_register_video_artifact`).

**Why split:** these are different capabilities with different inputs, costs,
failure modes, and reuse patterns. Merging clips the agent *already has* should
not require re-generating them. Adding a music bed or voiceover is editing, not
generation. A planner that sees one mega-tool can't sequence "generate 3 clips →
stitch → add narration"; three tools make that an explicit, inspectable plan.

---

## 2. Target — three composable tools

All three live under `tools/media/video/` (the `01` §5 layout move) over a small
shared `tools/media/video/_ffmpeg.py` helper, and all run ffmpeg inside the
**per-tenant container** (`02`) where ffmpeg is baked into the image.

### 2.1 `video_generate` — AI generation only

* **Job:** text-(or image-)to-video for a *single segment within the model's
  native limit* (≤8s for Veo 3.1). One model call → one clip.
* **In:** `model_name`, `prompt`, `length_seconds` (≤ model max),
  `start_frame_path?`, `end_frame_path?`, `is_audio_required?`.
* **Out:** one clip path + provenance (model, cost, has_audio).
* **Keeps:** `_generate_single_video`, `_resolve_vertex_metadata`,
  `_record_video_billing`, `_register_video_artifact`.
* **Drops:** segment math and ffmpeg merge (moves to `video_edit`).
* **Long videos:** the agent now plans `video_generate` per segment + one
  `video_edit` to stitch — explicit and inspectable, instead of hidden
  auto-splitting. (Optionally keep a thin convenience: if `length` > model max,
  return a structured hint "exceeds single-segment limit; generate segments and
  compose with video_edit" rather than silently doing it.)

### 2.2 `video_edit` — clip composition / editing / merging

* **Job:** operate on clips the agent already has (generated or uploaded).
* **In:** `operation` ∈ `concat | trim | extend | overlay | transition |
  resize`, `inputs[]` (clip paths), op-specific params, `output_path?`.
* **Out:** one composed clip + provenance (operation graph).
* **Owns:** `_calculate_segments` (now used for *re-segmenting/extension on
  request*, not auto), `_merge_videos` (ffmpeg concat), plus new ffmpeg-backed
  trim/transition/overlay/resize. This is pure ffmpeg — **no model cost**, only
  compute. Cost attribution = compute, not LLM.

### 2.3 `video_add_sound` — audio track / mixing

* **Job:** attach or mix an audio track onto an existing (silent or scored) clip.
* **In:** `video_path`, `source` ∈ `file | tts | generated`,
  `audio_path?` (file), `text?`+`voice?` (TTS narration), `music_prompt?`
  (generated bed), `mix` (gain/duck/loop/fade), `replace_or_overlay`.
* **Out:** clip with the new/mixed audio.
* **Implementation:** ffmpeg for muxing/mixing; TTS via the platform's existing
  speech provider (the `voice/` package already exists in `backend/src/ai/`);
  optional generated-music via a provider behind a flag. Veo's native audio flag
  stays available on `video_generate`; `video_add_sound` is for *separate*
  voiceover/music/SFX the agent supplies or synthesizes.

---

## 3. Shared concerns

* **`tools/media/video/_ffmpeg.py`:** one wrapper for the concat-list, mux, and
  filter-graph invocations (replaces the inline ffmpeg in `_merge_videos`), with
  consistent error surfacing and the output-path/artifact conventions.
* **Artifacts & provenance:** all three register outputs via the existing
  artifact registration with a typed provenance block (op or model, inputs,
  cost). A multi-step video plan thus leaves a full lineage in CORTEX.
* **Status & gating:** keep `status=EXPERIMENTAL` and the
  `tools.experimental.<id>` opt-in per tool. `video_generate` carries the high
  per-call cost gate; `video_edit` is cheap (compute-only); `video_add_sound` is
  cheap-to-moderate (TTS/music cost only if used).
* **Execution location:** ffmpeg/TTS run in the per-tenant container (`02`), not
  the host. This removes the host `subprocess` ffmpeg calls in today's tool.

---

## 4. Migration plan

| Step | Work |
|------|------|
| V1 | Create `tools/media/video/` + `_ffmpeg.py`; extract the ffmpeg/concat helpers |
| V2 | `video_generate` = generation-only (lift `_generate_single_video` et al.) |
| V3 | `video_edit` = concat/trim/extend/overlay/transition/resize over `_ffmpeg` |
| V4 | `video_add_sound` = file/TTS/generated audio mux+mix (reuse `voice/` for TTS) |
| V5 | Keep `video_generation` as a **deprecated thin shim** that composes the three for one release (so existing entities/seed scripts don't break), then remove |
| V6 | Update Document Factory / seed entities that reference `video_generation`; route ffmpeg through the container runtime (`02`) |

Backwards compatibility: the deprecated `video_generation` shim means no entity
breaks on day one; the three new tools are added to the registry and the shim is
removed once seeds are migrated.

---

## 5. Exit criteria

* Three registered tools — `video_generate`, `video_edit`, `video_add_sound` —
  each independently invocable and individually cost-attributed.
* A planner can express "generate N segments → `video_edit` concat →
  `video_add_sound` narration" as an explicit multi-step plan.
* ffmpeg/TTS execute in the per-tenant container, not the host.
* The old `video_generation` tool is removed after the shim release; no seed
  entity references it.
