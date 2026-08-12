"""Strip historical-narrative prefixes from ai/ comments.

Rewrites patterns like:
    # Phase 11 Track 8 — structured attribution tag.
    # Fix B: ensure ...
    # Ph-A: ...
    # RACE-123: ...
    # Gap #5: ...

into either the trailing explanation (with the prefix removed) or
removes the comment entirely when it has no payload after the prefix.

Idempotent. Run from the backend/ directory:
    .venv/bin/python scripts/sweep_comment_narration.py [--apply]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AI_ROOT = REPO_ROOT / "backend" / "src" / "ai"


PREFIX_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"(?P<indent>\s*#\s*)"
        r"(?:Phase\s+\d+(?:\s+Track\s+\d+)?(?:\s*[—\-:]\s*|\s+)?)"
        r"(?P<rest>.*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<indent>\s*#\s*)"
        r"(?:Fix\s+[A-Z]?\d?\s*[:\-—]\s*)"
        r"(?P<rest>.*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<indent>\s*#\s*)"
        r"(?:RACE-\d+\s*[:\-—]\s*)"
        r"(?P<rest>.*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<indent>\s*#\s*)"
        r"(?:Ph-[A-Z]\d?\s*[:\-—]\s*)"
        r"(?P<rest>.*)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?P<indent>\s*#\s*)"
        r"(?:Gap\s*#\d+\s*[:\-—]\s*)"
        r"(?P<rest>.*)",
        re.IGNORECASE,
    ),
]


def rewrite_line(line: str) -> str | None:
    """Return rewritten line, or None to drop entirely. Empty string is keep-as-is."""
    if not line.lstrip().startswith("#"):
        return line
    for pat in PREFIX_PATTERNS:
        m = pat.match(line)
        if not m:
            continue
        indent = m.group("indent")
        rest = m.group("rest").strip()
        if not rest:
            return None
        # Capitalise first letter so the rewrite still reads naturally.
        if rest and rest[0].islower():
            rest = rest[0].upper() + rest[1:]
        return f"{indent}{rest}"
    return line


def process_file(path: Path, *, apply: bool) -> tuple[int, int]:
    original = path.read_text()
    out_lines: list[str] = []
    changed = 0
    dropped = 0
    for line in original.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        new = rewrite_line(stripped)
        if new is None:
            dropped += 1
            continue
        if new != stripped:
            changed += 1
            out_lines.append(new + ("\n" if line.endswith("\n") else ""))
        else:
            out_lines.append(line)
    if (changed or dropped) and apply:
        path.write_text("".join(out_lines))
    return changed, dropped


def main() -> None:
    apply = "--apply" in sys.argv
    total_changed = 0
    total_dropped = 0
    files_touched: list[Path] = []
    for py in AI_ROOT.rglob("*.py"):
        try:
            changed, dropped = process_file(py, apply=apply)
        except OSError:
            continue
        if changed or dropped:
            files_touched.append(py)
            total_changed += changed
            total_dropped += dropped
            rel = py.relative_to(REPO_ROOT)
            print(f"  {rel}: {changed} rewritten, {dropped} dropped")
    mode = "applied" if apply else "DRY-RUN"
    print(
        f"\n{mode}: {len(files_touched)} files, "
        f"{total_changed} rewrites, {total_dropped} drops."
    )


if __name__ == "__main__":
    main()
