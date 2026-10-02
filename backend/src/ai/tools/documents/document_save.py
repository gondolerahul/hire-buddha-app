"""
DocumentSaveTool — Save sandbox-generated documents to the artifact system.

Used by Document Renderer and Revision Agent after sandbox_code creates
a document file. Copies from sandbox temp dir to artifact storage and
registers the file in the Artifact DB.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, context_company_id
from src.ai.tools.sandbox.workspace import PathOutsideWorkspace, confine_path, safe_filename

# Artifact root for system-generated files

# MIME type mapping for document formats
_MIME_TYPES: Dict[str, str] = {
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
    "png": "image/png",
    "svg": "image/svg+xml",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


class DocumentSaveTool(Tool):
    """Save a generated document file to the platform artifact system.

    Copies a file from the sandbox temp directory to persistent artifact
    storage and registers it in the Artifact DB for traceability.

    Actions:
        save — Copy file from source_path to artifact storage and register
    """

    name = "document_save"
    description = (
        "Save a generated document file to the artifact system. "
        "Input: JSON with 'source_path' (path to file in sandbox), "
        "'filename' (display name), 'format' (pptx/docx/xlsx/pdf), "
        "and optional 'purpose' description. "
        "Returns JSON with artifact_id, file_path, and file_size."
    )

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, context=None)

    async def run_with_context(self, input_data: str, context=None) -> str:
        try:
            params = json.loads(input_data) if isinstance(input_data, str) else input_data
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "Invalid JSON input. Expected: {source_path, filename, format}"})

        source_path = params.get("source_path", "")
        filename = params.get("filename", "")
        doc_format = params.get("format", "").lower()
        purpose = params.get("purpose", "AI-generated document")

        # Validate required fields
        if not source_path:
            return json.dumps({"error": "Missing 'source_path'"})
        if not filename:
            return json.dumps({"error": "Missing 'filename'"})
        if not doc_format:
            return json.dumps({"error": "Missing 'format' (pptx/docx/xlsx/pdf)"})

        # The company comes from the execution context only (TL-03); it
        # locates the sandbox.
        company_id = context_company_id(context)
        if not company_id:
            return json.dumps({"error": NO_CONTEXT_ERROR})

        # (B) Resolve the source path inside this company's files (TL-54). The
        # sandbox runs with the company's workspace as its working directory,
        # so a relative path the agent wrote ("scratch/report.pptx") resolves
        # there. Any other host path — /etc/passwd, the backend's .env, another
        # company's artifact — is refused: this tool copies the file into the
        # company's downloadable artifacts.
        try:
            source_path = confine_path(company_id, source_path)
        except PathOutsideWorkspace as exc:
            return json.dumps({"error": str(exc)})
        filename = safe_filename(filename, "document")
        if not os.path.exists(source_path):
            return json.dumps({"error": f"Source file not found: {source_path}"})

        # Resolve MIME type
        mime_type = _MIME_TYPES.get(doc_format)
        if not mime_type:
            return json.dumps({
                "error": f"Unknown format '{doc_format}'. Supported: {', '.join(_MIME_TYPES.keys())}"
            })

        # Ensure filename has correct extension
        expected_ext = f".{doc_format}"
        if not filename.lower().endswith(expected_ext):
            filename = f"{filename}{expected_ext}"

        # One write path (TL-59): the bytes become an artifact of the call's
        # run; its stored path is what the model gets.
        try:
            with open(source_path, "rb") as f:
                file_bytes = f.read()
        except Exception as e:
            return json.dumps({"error": f"Failed to read file: {str(e)}"})
        from src.ai.artifact_service import save_tool_output
        try:
            artifact = await save_tool_output(
                context, file_name=filename, file_bytes=file_bytes, mime_type=mime_type,
                file_category="documents", generated_by="document_save", purpose=purpose,
                extra_metadata={"format": doc_format},
            )
        except Exception as e:
            return json.dumps({"error": f"Failed to save the document: {str(e)}"})

        return json.dumps({
            "status": "success",
            "artifact_id": str(artifact.id),
            "file_path": artifact.file_path,
            "filename": filename,
            "format": doc_format,
            "file_size": len(file_bytes),
            "mime_type": mime_type,
            "message": f"Saved {filename} ({len(file_bytes):,} bytes) to artifact storage",
        })

    def get_function_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "source_path": {
                        "type": "string",
                        "description": "Path to the generated file. Absolute preferred (e.g. /tmp/sandbox/<id>/report.pptx); a sandbox-relative path like 'scratch/report.pptx' also resolves.",
                    },
                    "filename": {
                        "type": "string",
                        "description": "Display filename for the artifact (e.g. 'investor_pitch_deck.pptx')",
                    },
                    "format": {
                        "type": "string",
                        "enum": ["pptx", "docx", "xlsx", "pdf", "png", "svg"],
                        "description": "Document format",
                    },
                    "purpose": {
                        "type": "string",
                        "description": "Optional description of the document's purpose",
                    },
                },
                "required": ["source_path", "filename", "format"],
            },
        }
