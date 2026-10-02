"""Keep a document a tool built: one write path (TL-59)."""
from __future__ import annotations

import io
from typing import Any, Optional


async def keep_document(
    document: Any,
    context: Optional[dict],
    *,
    file_name: str,
    mime_type: str,
    generated_by: str,
    purpose: Optional[str] = None,
) -> Any:
    """Save a python-docx / python-pptx / openpyxl document as an artifact of
    the call's run and return the artifact (its ``file_path`` and ``id``).

    The document is saved to memory and handed to the artifact store once;
    there is no first copy under ``backend/src/artifact``.
    """
    from src.ai.artifact_service import save_tool_output

    buffer = io.BytesIO()
    document.save(buffer)
    return await save_tool_output(
        context, file_name=file_name, file_bytes=buffer.getvalue(), mime_type=mime_type,
        file_category="documents", generated_by=generated_by, purpose=purpose,
    )
