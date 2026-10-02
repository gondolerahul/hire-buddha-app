"""File Writer tool for AI Entities."""

import json
import os
from src.ai.tools.base import NO_CONTEXT_ERROR, Tool, context_company_id


class FileWriterTool(Tool):
    """Tool for writing text content to a file."""

    name = "file_writer"
    category = "document"
    description = (
        "Write text content to a specific file. "
        "Input should be a JSON object with 'filename' and 'content'. "
        "The file is kept as an artifact of the run; its path is returned."
    )

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

            company_id = context_company_id(context)
            if not company_id:
                return f"Error: {NO_CONTEXT_ERROR}"

            # Determine file category
            ext = os.path.splitext(filename)[1].lower()
            file_category = "text" if ext in (".txt", ".md") else "documents"

            # One write path: the artifact store, with the call's run (TL-59).
            from src.ai.artifact_service import save_tool_output
            artifact = await save_tool_output(
                context,
                file_name=filename,
                file_bytes=content.encode("utf-8"),
                mime_type="text/markdown" if ext == ".md" else "text/plain",
                file_category=file_category,
                generated_by=generated_by,
                purpose=purpose,
                extra_metadata={"char_count": len(content)},
            )
            return json.dumps({
                "status": "success",
                "artifact_id": str(artifact.id),
                "file_path": artifact.file_path,
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
