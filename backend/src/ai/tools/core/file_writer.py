"""File Writer tool for AI Entities."""

import json
import os
from datetime import datetime
from pathlib import Path
from src.ai.tools.base import Tool


class FileWriterTool(Tool):
    """Tool for writing text content to a file."""

    name = "file_writer"
    description = (
        "Write text content to a specific file. "
        "Input should be a JSON object with 'filename' and 'content'. "
        "Files are saved in the 'artifact/system-generated' directory."
    )

    # Root: artifact/system-generated/ (resolved relative to the backend dir)
    BASE_DIR = Path(__file__).resolve().parents[3] / "artifact" / "system-generated"

    async def run(self, input_data: str) -> str:
        return await self.run_with_context(input_data, context=None)

    async def run_with_context(self, input_data: str, context=None) -> str:
        try:
            params = json.loads(input_data)
            filename = params.get("filename")
            content = params.get("content")

            if not filename or not content:
                return json.dumps({"error": "Missing 'filename' or 'content'"})

            # Ensure safe filename
            filename = os.path.basename(filename)
            if not filename.endswith(('.txt', '.md', '.json', '.csv')):
                filename += ".md"

            # Use context injected by worker if available
            company_id = None
            purpose = params.get("purpose", "AI-generated text document")
            generated_by = params.get("generated_by", "file_writer")

            if context:
                company_id = context.get("company_id") or params.get("company_id", "default")
            else:
                company_id = params.get("company_id", "default")

            # Determine file category
            ext = os.path.splitext(filename)[1].lower()
            file_category = "text" if ext in (".txt", ".md") else "documents"

            # Write file to disk
            date_str = datetime.utcnow().strftime("%Y-%m-%d")
            output_dir = self.BASE_DIR / str(company_id) / date_str
            output_dir.mkdir(parents=True, exist_ok=True)

            file_path = output_dir / filename
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            # Register in artifacts DB
            if company_id and company_id != "default":
                try:
                    from uuid import UUID as _UUID
                    from src.common.database import AsyncSessionLocal
                    from src.ai.artifact_service import ArtifactService, ORIGIN_SYSTEM

                    async with AsyncSessionLocal() as _db:
                        art_svc = ArtifactService(_db)
                        await art_svc.save_artifact(
                            file_bytes=content.encode("utf-8"),
                            file_name=filename,
                            mime_type="text/markdown" if ext == ".md" else "text/plain",
                            file_category=file_category,
                            origin=ORIGIN_SYSTEM,
                            company_id=_UUID(str(company_id)),
                            purpose=purpose,
                            generated_by=generated_by,
                            extra_metadata={"char_count": len(content)},
                        )
                except Exception as _reg_err:
                    pass  # Non-fatal — file is already saved to disk

            return json.dumps({
                "status": "success",
                "file_path": str(file_path),
                "message": f"Successfully wrote {len(content)} bytes to {filename}"
            })

        except Exception as e:
            return json.dumps({"error": f"File Writer Error: {str(e)}"})

    def get_function_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Name of the file (e.g., notes.md)"},
                    "content": {"type": "string", "description": "Text content to write"},
                    "purpose": {"type": "string", "description": "What this file is for"},
                    "generated_by": {"type": "string", "description": "Which agent/process created this"}
                },
                "required": ["filename", "content"]
            }
        }
