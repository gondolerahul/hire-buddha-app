"""The business's Google Drive, limited to the files a person chose (GOOG-E4).

The ``google_drive`` connector asks only for ``drive.file``: Google lets
HireBuddha open the files a person picks in the Google Picker
(``connections.service.set_picked_files``) and the files HireBuddha creates,
nothing else. This tool keeps to the same list — a file outside it is refused
before Google is asked — so an agent never reaches a file nobody gave it.

Operations: ``list_files`` (the chosen and created files), ``read_file`` (text
of a document, sheet, slides or text file), ``create_file`` and ``update_file``
(text content). Creating and changing files wait for a person's approval like
every write to a connected account (SH-E4).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import httpx
from pydantic import Field

from src.ai.tools.base import Tool, ToolOutput, ToolParams

logger = logging.getLogger(__name__)

DRIVE_API = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3"
MAX_READ_BYTES = 2 * 1024 * 1024
OPERATIONS = ("list_files", "read_file", "create_file", "update_file")
# Google's own formats, read as text.
EXPORTS = {"application/vnd.google-apps.document": "text/plain",
           "application/vnd.google-apps.spreadsheet": "text/csv",
           "application/vnd.google-apps.presentation": "text/plain"}
NOT_CHOSEN = ("HireBuddha may open only the Drive files a person chose for it (Connections → Google Drive → "
              "Choose files) and the files it created. Ask a person to choose this file.")


class GoogleDriveParams(ToolParams):
    operation: str = Field(..., json_schema_extra={"enum": list(OPERATIONS)},
                           description="list_files, read_file, create_file or update_file")
    file_id: Optional[str] = Field(None, description="For read_file and update_file")
    name: Optional[str] = Field(None, description="For create_file: the new file's name")
    content: Optional[str] = Field(None, description="For create_file and update_file: the text to save")
    mime_type: Optional[str] = Field("text/plain", description="For create_file: text/plain, text/csv, text/markdown, "
                                                               "or application/vnd.google-apps.document")
    account: Optional[str] = Field(None, description="Optional: which Drive connection, by its account")


def _allowed(meta: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    files = list(meta.get("picked_files") or []) + list(meta.get("created_files") or [])
    return {str(f.get("id")): f for f in files if isinstance(f, dict) and f.get("id")}


class GoogleDriveTool(Tool):
    name = "google_drive"
    description = ("The business's Google Drive, limited to the files a person chose for HireBuddha and the files "
                   "HireBuddha created: list them, read one as text, create a text file or Google Doc, or update one.")
    Params = GoogleDriveParams

    async def execute(self, params: GoogleDriveParams, ctx: Dict[str, Any]) -> ToolOutput:
        from src.connections.client import credentials_for

        if params.operation not in OPERATIONS:
            return ToolOutput.failed(f"operation is one of {list(OPERATIONS)}", code="invalid_input")
        writes = params.operation in ("create_file", "update_file")
        creds = await credentials_for(ctx, "google_drive", account=params.account,
                                      action="write" if writes else "read")
        if not creds:
            return ToolOutput.failed("No Google Drive is connected and shared with this agent (Connections).",
                                     code="no_connection")
        meta = creds.get("oauth_metadata") or {}
        allowed = _allowed(meta)
        headers = {"Authorization": f"Bearer {creds['access_token']}"}
        try:
            if params.operation == "list_files":
                return ToolOutput(output={"files": [{"id": i, "name": f.get("name"), "mime_type": f.get("mime_type")}
                                                    for i, f in allowed.items()],
                                          "note": "Only these files are reachable; a person chooses more."})
            if params.operation == "create_file":
                return await self._create(params, creds, headers, ctx)
            if not params.file_id:
                return ToolOutput.failed("file_id is required", code="invalid_input")
            if params.file_id not in allowed:
                return ToolOutput.failed(NOT_CHOSEN, code="file_not_chosen")
            if params.operation == "read_file":
                return await self._read(params.file_id, headers)
            return await self._update(params, headers)
        except httpx.HTTPStatusError as exc:
            return ToolOutput.failed(f"Google Drive answered {exc.response.status_code}: {exc.response.text[:300]}",
                                     code="provider_error")

    @staticmethod
    async def _read(file_id: str, headers: Dict[str, str]) -> ToolOutput:
        async with httpx.AsyncClient(timeout=60) as client:
            info = await client.get(f"{DRIVE_API}/files/{file_id}", headers=headers,
                                    params={"fields": "id,name,mimeType,size,modifiedTime"})
            info.raise_for_status()
            item = info.json()
            mime = str(item.get("mimeType") or "")
            if mime in EXPORTS:
                resp = await client.get(f"{DRIVE_API}/files/{file_id}/export", headers=headers,
                                        params={"mimeType": EXPORTS[mime]})
            elif mime.startswith("text/") or mime in ("application/json", "application/xml"):
                if int(item.get("size") or 0) > MAX_READ_BYTES:
                    return ToolOutput.failed(f"{item.get('name')} is larger than {MAX_READ_BYTES // 1024 // 1024} MB",
                                             code="too_large")
                resp = await client.get(f"{DRIVE_API}/files/{file_id}", headers=headers, params={"alt": "media"})
            else:
                return ToolOutput.failed(f"{item.get('name')} is a {mime} file; this tool reads documents, sheets, "
                                         "slides and text", code="unsupported_type")
            resp.raise_for_status()
        text = resp.content[:MAX_READ_BYTES].decode("utf-8", "replace")
        return ToolOutput(output={"id": file_id, "name": item.get("name"), "mime_type": mime,
                                  "modified": item.get("modifiedTime"), "text": text,
                                  "truncated": len(resp.content) > MAX_READ_BYTES})

    @staticmethod
    async def _create(params: GoogleDriveParams, creds: Dict[str, Any], headers: Dict[str, str],
                      ctx: Dict[str, Any]) -> ToolOutput:
        from src.connections import service

        if not params.name or params.content is None:
            return ToolOutput.failed("name and content are required to create a file", code="invalid_input")
        mime = params.mime_type or "text/plain"
        upload_type = "text/plain" if mime == "application/vnd.google-apps.document" else mime
        metadata = {"name": params.name, "mimeType": mime}
        boundary = "hirebuddha-drive-upload"
        body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n{json.dumps(metadata)}\r\n"
                f"--{boundary}\r\nContent-Type: {upload_type}; charset=UTF-8\r\n\r\n{params.content}\r\n"
                f"--{boundary}--").encode()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(f"{DRIVE_UPLOAD}/files", headers={
                **headers, "Content-Type": f"multipart/related; boundary={boundary}"}, content=body,
                params={"uploadType": "multipart", "fields": "id,name,mimeType,webViewLink"})
            resp.raise_for_status()
        made = resp.json()
        await service.remember_created_file(ctx.get("company_id"), creds["connection_id"],
                                            {"id": made.get("id"), "name": made.get("name"),
                                             "mime_type": made.get("mimeType")})
        return ToolOutput(output={"success": True, "id": made.get("id"), "name": made.get("name"),
                                  "link": made.get("webViewLink")})

    @staticmethod
    async def _update(params: GoogleDriveParams, headers: Dict[str, str]) -> ToolOutput:
        if params.content is None:
            return ToolOutput.failed("content is required to update a file", code="invalid_input")
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.patch(f"{DRIVE_UPLOAD}/files/{params.file_id}", headers={
                **headers, "Content-Type": "text/plain; charset=UTF-8"}, content=params.content.encode(),
                params={"uploadType": "media", "fields": "id,name,modifiedTime"})
            resp.raise_for_status()
        made = resp.json()
        return ToolOutput(output={"success": True, "id": made.get("id"), "name": made.get("name"),
                                  "modified": made.get("modifiedTime")})
