"""A small PDF writer for invoices and credit notes (Phase 15 T6-5).

No PDF library is installed on the platform's images, and an invoice needs
only text and rules: this writes PDF 1.4 by hand — A4 pages, the standard
Helvetica fonts (WinAnsi), text and lines. Characters outside Latin-1 are
replaced (the rupee sign is written "INR").
"""
from __future__ import annotations

from typing import List, Tuple

A4 = (595, 842)
_REPLACE = {"₹": "INR ", "–": "-", "—": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "·": "-", "×": "x"}


def _text(value: str) -> str:
    for old, new in _REPLACE.items():
        value = value.replace(old, new)
    value = value.encode("latin-1", "replace").decode("latin-1")
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_width(value: str, size: float) -> float:
    """An estimate of Helvetica's width (0.5 em a character), for right alignment."""
    return len(value) * size * 0.5


class Page:
    def __init__(self) -> None:
        self.ops: List[str] = []

    def text(self, x: float, y: float, value: str, size: float = 10, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self.ops.append(f"BT /{font} {size:.1f} Tf {x:.1f} {y:.1f} Td ({_text(value)}) Tj ET")

    def right(self, x: float, y: float, value: str, size: float = 10, bold: bool = False) -> None:
        self.text(x - text_width(value, size), y, value, size, bold)

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.5) -> None:
        self.ops.append(f"{width:.2f} w {x1:.1f} {y1:.1f} m {x2:.1f} {y2:.1f} l S")


class Document:
    def __init__(self, title: str = "") -> None:
        self.title = title
        self.pages: List[Page] = []

    def page(self) -> Page:
        page = Page()
        self.pages.append(page)
        return page

    def to_bytes(self) -> bytes:
        objects: List[bytes] = []

        def add(body: str) -> int:
            objects.append(body.encode("latin-1"))
            return len(objects)

        catalog = add("")                      # filled below
        pages_ref = add("")
        regular = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        bold = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        kids: List[int] = []
        for page in self.pages or [Page()]:
            stream = "\n".join(page.ops)
            content = add(f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream")
            kids.append(add(f"<< /Type /Page /Parent {pages_ref} 0 R /MediaBox [0 0 {A4[0]} {A4[1]}] "
                            f"/Resources << /Font << /F1 {regular} 0 R /F2 {bold} 0 R >> >> "
                            f"/Contents {content} 0 R >>"))
        objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_ref} 0 R >>".encode("latin-1")
        objects[pages_ref - 1] = (f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] "
                                  f"/Count {len(kids)} >>").encode("latin-1")
        info = add(f"<< /Title ({_text(self.title)}) /Producer (HireBuddha) >>")
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets: List[int] = []
        for number, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("latin-1")
        for offset in offsets:
            out += f"{offset:010d} 00000 n \n".encode("latin-1")
        out += (f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R /Info {info} 0 R >>\n"
                f"startxref\n{xref}\n%%EOF\n").encode("latin-1")
        return bytes(out)


def rows(page: Page, top: float, items: List[Tuple[str, str]], *, x: float = 50, value_x: float = 545,
         size: float = 10, gap: float = 15) -> float:
    """Label / right-aligned value rows from ``top`` down; returns the next y."""
    y = top
    for label, value in items:
        page.text(x, y, label, size)
        page.right(value_x, y, value, size)
        y -= gap
    return y
