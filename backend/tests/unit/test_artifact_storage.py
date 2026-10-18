"""Phase 14 WS1 1.2/1.3: artifacts live in storage, not on the API's disk.

An artifact records its storage key; its bytes are read through the storage
adapter, so the same code works on local disk and on Blob storage (no local
file at all). Rows from before keep working from their file. A tool handed one
of its company's keys gets a local copy; another company's key is refused.
Opening a file sends the browser to a signed storage URL when the adapter has
one, and serves the bytes itself when it has not.
"""
import uuid
from types import SimpleNamespace

import pytest

from src.ai.artifact_models import Artifact
from src.ai.artifact_service import (
    ORIGIN_SYSTEM,
    ORIGIN_USER,
    ArtifactService,
    artifact_local_file,
    artifact_size,
    new_storage_key,
    read_artifact_bytes,
)
from src.common.platform import storage as storage_mod
from src.common.platform.storage import StorageObjectNotFound, company_namespace
from src.common.platform.storage.local_disk import LocalDiskBackend
from tests.harness.storage import MemoryStorage

COMPANY = uuid.UUID("0b3c1c9e-1111-4000-8000-000000000001")
OTHER = uuid.UUID("0b3c1c9e-2222-4000-8000-000000000002")


@pytest.fixture
def memory():
    backend = MemoryStorage()
    storage_mod.set_storage(backend)
    yield backend
    storage_mod.set_storage(None)


class _Session:
    def __init__(self, fail_commit=False):
        self.added, self.fail_commit = [], fail_commit

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("database down")

    async def refresh(self, row):
        pass


@pytest.mark.parametrize("origin, category, area", [
    (ORIGIN_SYSTEM, "documents", "artifacts"),
    (ORIGIN_USER, "images", "uploads"),
    (ORIGIN_SYSTEM, "recordings", "recordings"),
])
def test_a_new_key_is_in_the_companys_namespace(origin, category, area):
    key = new_storage_key(origin, category, COMPANY, "../../etc/passwd")
    namespace, kind, date, name = key.split("/")
    assert (namespace, kind) == (company_namespace(COMPANY), area)
    assert len(date) == 10 and name.endswith("_passwd")


async def test_save_artifact_stores_the_bytes_under_its_key(memory):
    db = _Session()
    artifact = await ArtifactService(db).save_artifact(
        file_bytes=b"%PDF", file_name="r.pdf", mime_type="application/pdf", file_category="documents",
        origin=ORIGIN_SYSTEM, company_id=COMPANY)
    assert artifact.storage_key.startswith(company_namespace(COMPANY) + "/artifacts/")
    # No local file on remote storage: the key is what a tool shows the model.
    assert artifact.file_path == artifact.storage_key
    assert memory.objects[artifact.storage_key] == b"%PDF"
    assert memory.content_types[artifact.storage_key] == "application/pdf"
    assert await read_artifact_bytes(artifact) == b"%PDF" and await artifact_size(artifact) == 4


async def test_save_artifact_on_local_disk_records_the_file(tmp_path):
    storage_mod.set_storage(LocalDiskBackend(tmp_path))
    try:
        artifact = await ArtifactService(_Session()).save_artifact(
            file_bytes=b"x", file_name="n.md", mime_type="text/markdown", file_category="text",
            origin=ORIGIN_SYSTEM, company_id=COMPANY)
    finally:
        storage_mod.set_storage(None)
    assert artifact.file_path == str(tmp_path.resolve() / artifact.storage_key)


async def test_a_failed_commit_leaves_no_object(memory):
    with pytest.raises(RuntimeError):
        await ArtifactService(_Session(fail_commit=True)).save_artifact(
            file_bytes=b"x", file_name="n.md", mime_type="text/markdown", file_category="text",
            origin=ORIGIN_SYSTEM, company_id=COMPANY)
    assert memory.objects == {}


async def test_a_row_from_before_storage_keys_reads_its_file(memory, tmp_path):
    old = tmp_path / "old.txt"
    old.write_bytes(b"legacy")
    artifact = Artifact(file_path=str(old), file_name="old.txt", storage_key=None)
    assert await read_artifact_bytes(artifact) == b"legacy"
    async with artifact_local_file(artifact) as path:
        assert path == old
    gone = Artifact(file_path=str(tmp_path / "gone.txt"), file_name="gone.txt", storage_key=None)
    assert await artifact_size(gone) is None
    with pytest.raises(StorageObjectNotFound):
        await read_artifact_bytes(gone)


async def test_a_provider_url_is_not_read_as_a_file(memory):
    artifact = Artifact(file_path="https://api.twilio.com/rec.wav", file_name="rec.wav", storage_key=None)
    assert await artifact_size(artifact) is None


async def test_artifact_local_file_copies_from_remote_storage(memory):
    key = f"{company_namespace(COMPANY)}/artifacts/2026-10-17/a_doc.docx"
    await memory.put(key, b"docx-bytes")
    artifact = Artifact(file_path=key, file_name="doc.docx", storage_key=key)
    async with artifact_local_file(artifact) as path:
        assert path.read_bytes() == b"docx-bytes" and path.suffix == ".docx"
    assert not path.exists()


# ── tools handed a storage key ─────────────────────────────────────────────


async def test_a_tool_gets_a_local_copy_of_its_companys_key(memory, monkeypatch, tmp_path):
    from src.ai.tools.sandbox import workspace

    monkeypatch.setattr(workspace, "workspace_root", lambda: str(tmp_path / "ws"))
    key = f"{company_namespace(COMPANY)}/artifacts/2026-10-17/a_slides.pptx"
    await memory.put(key, b"pptx")
    params = {"file_path": key, "inputs": [key, "relative/clip.mp4"]}
    await workspace.confine_params_async(params, COMPANY, ("file_path", "inputs"))
    copy = params["file_path"]
    assert open(copy, "rb").read() == b"pptx"
    assert copy.startswith(str(tmp_path / "ws" / str(COMPANY)))
    assert params["inputs"][0] == copy
    assert params["inputs"][1].endswith("clip.mp4")


async def test_another_companys_key_is_refused(memory, monkeypatch, tmp_path):
    from src.ai.tools.sandbox import workspace

    monkeypatch.setattr(workspace, "workspace_root", lambda: str(tmp_path / "ws"))
    theirs = f"{company_namespace(OTHER)}/artifacts/2026-10-17/a_secret.pdf"
    await memory.put(theirs, b"theirs")
    assert workspace.company_storage_key(COMPANY, theirs) is None
    # Not a key of this company: read as a path in its workspace, where it is not.
    resolved = await workspace.confine_path_async(COMPANY, theirs)
    assert resolved.startswith(str(tmp_path / "ws" / str(COMPANY)))
    import os
    assert not os.path.exists(resolved)


@pytest.mark.parametrize("value, own", [
    (f"system-generated/{COMPANY}/2026-10-01/r.docx", True),
    (f"user-uploads/{COMPANY}/2026-10-01/r.docx", True),
    (f"system-generated/{OTHER}/2026-10-01/r.docx", False),
    ("/etc/passwd", False),
    ("scratch/a.docx", False),
])
def test_which_keys_are_the_companys(value, own):
    from src.ai.tools.sandbox.workspace import company_storage_key

    assert (company_storage_key(COMPANY, value) == value) is own


# ── opening a file ─────────────────────────────────────────────────────────


async def test_open_redirects_to_a_signed_url_when_storage_has_one(memory):
    from src.ai.artifact_router import _signed_or_served

    key = f"{company_namespace(COMPANY)}/artifacts/2026-10-17/a_r.pdf"
    await memory.put(key, b"pdf")
    artifact = Artifact(id=uuid.uuid4(), file_path=key, file_name="r.pdf", storage_key=key,
                        mime_type="application/pdf")
    response = await _signed_or_served(artifact, SimpleNamespace(headers={}), inline=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith(f"https://storage.example/{key}?sig=")


async def test_download_streams_from_remote_storage(memory):
    from src.ai.artifact_router import _file_response

    key = f"{company_namespace(COMPANY)}/artifacts/2026-10-17/a_r.txt"
    await memory.put(key, b"hello world")
    artifact = Artifact(id=uuid.uuid4(), file_path=key, file_name="r.txt", storage_key=key,
                        mime_type="text/plain")
    response = await _file_response(artifact, SimpleNamespace(headers={}))
    body = b"".join([chunk async for chunk in response.body_iterator])
    assert body == b"hello world"
    assert response.headers["content-length"] == "11"
    assert "attachment" in response.headers["content-disposition"]


async def test_a_missing_object_is_404(memory):
    from fastapi import HTTPException

    from src.ai.artifact_router import _file_response

    key = f"{company_namespace(COMPANY)}/artifacts/2026-10-17/a_gone.txt"
    artifact = Artifact(id=uuid.uuid4(), file_path=key, file_name="gone.txt", storage_key=key)
    with pytest.raises(HTTPException) as caught:
        await _file_response(artifact, SimpleNamespace(headers={}))
    assert caught.value.status_code == 404


async def test_local_disk_serves_the_file_itself(tmp_path):
    from src.ai.artifact_router import _signed_or_served

    backend = LocalDiskBackend(tmp_path)
    storage_mod.set_storage(backend)
    try:
        key = f"{company_namespace(COMPANY)}/uploads/2026-10-17/a_p.png"
        await backend.put(key, b"png")
        artifact = Artifact(id=uuid.uuid4(), file_path=str(backend.local_path(key)), file_name="p.png",
                            storage_key=key, mime_type="image/png")
        response = await _signed_or_served(artifact, SimpleNamespace(headers={}), inline=True)
    finally:
        storage_mod.set_storage(None)
    assert response.status_code == 200 and response.path == str(backend.local_path(key))
    assert response.headers["content-disposition"].startswith("inline")


def test_the_files_scope_has_url_tokens():
    from src.common.security import URL_TOKEN_SCOPES

    assert "/api/v1/files/" in URL_TOKEN_SCOPES
