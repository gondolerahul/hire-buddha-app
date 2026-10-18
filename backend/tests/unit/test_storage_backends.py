"""Phase 14 WS1 1.2: files are kept by neutral keys behind one storage interface.

Every adapter meets the same contract (``tests/harness/storage.py``); the
Azure Blob adapter runs it against Azurite in
``tests/integration/test_storage_azurite.py``. Keys are ``<namespace>/<path>``
— never a disk path or a URL — and a key that could escape its namespace is
refused before any adapter sees it.
"""
import uuid

import pytest

from src.common.platform import storage as storage_mod
from src.common.platform.storage import (
    InvalidStorageKey,
    StorageObjectNotFound,
    company_namespace,
    materialized,
    validate_key,
)
from src.common.platform.storage.local_disk import LocalDiskBackend
from tests.harness.storage import MemoryStorage, check_contract


@pytest.fixture(autouse=True)
def _fresh_storage():
    storage_mod.set_storage(None)
    yield
    storage_mod.set_storage(None)


async def test_local_disk_meets_the_contract(tmp_path):
    await check_contract(LocalDiskBackend(tmp_path), "c-test")


async def test_the_memory_double_meets_the_contract():
    await check_contract(MemoryStorage(), "c-test")


@pytest.mark.parametrize("key", [
    "c-abc/artifacts/x.pdf",
    "system-generated/0b3c1c9e-0000-4000-8000-000000000000/2026-10-01/r.docx",
    "t-devacme01/uploads/a b (1).png",
])
def test_valid_keys(key):
    assert validate_key(key) == key


@pytest.mark.parametrize("key", [
    "", "c-abc", "c-abc/", "/c-abc/x", "c-abc//x", "c-abc/../x", "c-abc/./x",
    "C-ABC/x", "ab/x", "c--abc/x", "-abc/x", "c-abc\\x", "C:/x/y", "c-abc/x\x00y",
    "c-abc/" + "x" * 1100,
])
def test_invalid_keys(key):
    with pytest.raises(InvalidStorageKey):
        validate_key(key)


def test_a_company_namespace_is_a_container_name():
    company = uuid.uuid4()
    namespace = company_namespace(company)
    assert namespace == f"c-{company.hex}" and validate_key(f"{namespace}/x")


async def test_local_disk_writes_whole_files_only(tmp_path):
    backend = LocalDiskBackend(tmp_path)
    await backend.put("c-abc/a/b.txt", b"hello")
    leftovers = [p.name for p in (tmp_path / "c-abc" / "a").iterdir()]
    assert leftovers == ["b.txt"]
    assert backend.local_path("c-abc/a/b.txt") == (tmp_path / "c-abc" / "a" / "b.txt").resolve()


async def test_local_disk_refuses_a_symlink_out_of_its_root(tmp_path):
    import os

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    root = tmp_path / "root"
    (root / "c-abc").mkdir(parents=True)
    try:
        os.symlink(outside, root / "c-abc" / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need privileges on this platform")
    with pytest.raises(StorageObjectNotFound):
        await LocalDiskBackend(root).get("c-abc/link/secret.txt")


async def test_materialized_is_the_file_itself_on_local_disk(tmp_path):
    backend = LocalDiskBackend(tmp_path)
    storage_mod.set_storage(backend)
    await backend.put("c-abc/r.pdf", b"pdf")
    async with materialized("c-abc/r.pdf") as path:
        assert path == backend.local_path("c-abc/r.pdf")
    assert path.exists()


async def test_materialized_is_a_temporary_copy_elsewhere():
    memory = MemoryStorage()
    storage_mod.set_storage(memory)
    await memory.put("c-abc/r.pdf", b"pdf-bytes")
    async with materialized("c-abc/r.pdf") as path:
        assert path.read_bytes() == b"pdf-bytes" and path.suffix == ".pdf"
    assert not path.exists()
    with pytest.raises(StorageObjectNotFound):
        async with materialized("c-abc/missing.pdf"):
            pass
