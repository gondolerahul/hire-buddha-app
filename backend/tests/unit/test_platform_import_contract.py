"""Phase 14 P-02: cloud SDKs are imported only inside the platform adapters.

Application code depends on the interfaces in ``src/common/platform`` so the
same code runs on Azure, on-premise or a laptop (tech spec §19). An
``azure.*`` or ``google.cloud.*`` import anywhere else ties it to one cloud.
Model-provider SDKs (``google-genai``, ``anthropic``, ``openai``) are not
infrastructure and are not covered.
"""
import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
ADAPTERS = BACKEND / "src" / "common" / "platform"
CLOUD_SDKS = ("azure", "google.cloud")


def _cloud_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found = []
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names = [node.module]
        for name in names:
            if any(name == sdk or name.startswith(sdk + ".") for sdk in CLOUD_SDKS):
                found.append(f"{path.relative_to(BACKEND).as_posix()}:{node.lineno} {name}")
    return found


@pytest.mark.parametrize("root", ["src", "cortex_memory"])
def test_cloud_sdks_only_in_platform_adapters(root):
    offenders = [
        hit
        for path in (BACKEND / root).rglob("*.py")
        if "__pycache__" not in path.parts and ADAPTERS not in path.parents
        for hit in _cloud_imports(path)
    ]
    assert offenders == [], "move these behind an interface in src/common/platform: " + ", ".join(offenders)


def test_the_check_sees_an_import():
    sample = ADAPTERS / "storage" / "azure_blob.py"
    assert any("azure.storage.blob" in hit for hit in _cloud_imports(sample))
