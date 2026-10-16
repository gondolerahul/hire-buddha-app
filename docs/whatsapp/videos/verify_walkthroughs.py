"""Decode every walkthrough and create contact sheets for visual review."""

from pathlib import Path

import av
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
QA = ROOT / "_qa"
QA.mkdir(exist_ok=True)

for video in sorted(ROOT.glob("*.mp4")):
    with av.open(str(video)) as container:
        stream = container.streams.video[0]
        duration = float(stream.duration * stream.time_base)
        picks = [1, duration * 0.2, duration * 0.4, duration * 0.6, duration * 0.8, duration - 2]
        frames = []
        for frame in container.decode(video=0):
            t = float(frame.pts * frame.time_base)
            if picks and t >= picks[0]:
                frames.append((t, frame.to_image().resize((800, 450))))
                picks.pop(0)
        if len(frames) != 6:
            raise RuntimeError(f"Unable to decode six checkpoints from {video.name}")
        sheet = Image.new("RGB", (1600, 1434), (15, 12, 11))
        draw = ImageDraw.Draw(sheet)
        for i, (t, frame_image) in enumerate(frames):
            x = i % 2 * 800
            y = i // 2 * 478
            sheet.paste(frame_image, (x, y))
            draw.text((x + 12, y + 454), f"{t:.1f} s", fill="#f4ddd6")
        sheet.save(QA / f"{video.stem}.png")
        print(f"{video.name}: {duration:.1f}s, {stream.width}x{stream.height}, {stream.frames} frames, decode OK")
