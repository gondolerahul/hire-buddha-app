"""ToolValidator static-analysis gate — Phase 12 `06` §2.2.

The non-negotiable static half of tool-synthesis safety: synthesized source is
parsed and walked before it can ever execute. These tests lock in that the gate
rejects the classic escape/exfiltration primitives and accepts a well-formed,
policy-compliant tool.
"""
from __future__ import annotations

import pytest

from src.ai.meta.tool_validator import ToolValidator
from src.ai.schemas.tools import NetworkPolicy, ToolSpec


def _spec(**kw) -> ToolSpec:
    base = dict(name="word_count", description="count words")
    base.update(kw)
    return ToolSpec(**base)


CLEAN_TOOL = '''
import json
from src.ai.tools.base import Tool


class WordCountTool(Tool):
    name = "word_count"

    async def run(self, input_data: str) -> str:
        data = json.loads(input_data)
        return json.dumps({"count": len(data.get("text", "").split())})
'''


def _validate(source: str, spec=None):
    return ToolValidator().validate(source, spec or _spec())


def test_clean_tool_passes() -> None:
    res = _validate(CLEAN_TOOL)
    assert res.ok, res.summary()
    assert "json" in res.imported_modules


@pytest.mark.parametrize("primitive", ["eval", "exec", "compile", "__import__"])
def test_dynamic_code_rejected(primitive: str) -> None:
    src = CLEAN_TOOL.replace(
        'return json.dumps({"count": len(data.get("text", "").split())})',
        f'return {primitive}("1+1")' if primitive != "__import__"
        else 'return __import__("os").getcwd()',
    )
    res = _validate(src)
    assert not res.ok
    assert any(v.code in ("forbidden_call", "forbidden_name") for v in res.violations)


def test_subprocess_rejected() -> None:
    src = CLEAN_TOOL.replace("import json", "import json\nimport subprocess")
    src = src.replace(
        'return json.dumps({"count": len(data.get("text", "").split())})',
        'return subprocess.run(["ls"]).stdout',
    )
    res = _validate(src)
    assert not res.ok
    codes = {v.code for v in res.violations}
    assert "import_not_allowed" in codes or "forbidden_process" in codes


def test_os_environ_secret_access_rejected() -> None:
    src = CLEAN_TOOL.replace("import json", "import json\nimport os")
    src = src.replace(
        'return json.dumps({"count": len(data.get("text", "").split())})',
        'return os.environ.get("SECRET", "")',
    )
    res = _validate(src)
    assert not res.ok
    # os isn't in the allow-list AND os.environ is a forbidden dotted access.
    codes = {v.code for v in res.violations}
    assert "import_not_allowed" in codes or "forbidden_attr" in codes


def test_disallowed_import_rejected() -> None:
    src = CLEAN_TOOL.replace("import json", "import json\nimport pickle")
    res = _validate(src)
    assert not res.ok
    assert any(v.code == "import_not_allowed" and "pickle" in v.message for v in res.violations)


def test_allowed_import_honored() -> None:
    src = CLEAN_TOOL.replace("import json", "import json\nimport pickle")
    res = _validate(src, _spec(allowed_imports=["pickle"]))
    assert res.ok, res.summary()


def test_network_import_denied_by_default() -> None:
    src = CLEAN_TOOL.replace("import json", "import json\nimport socket")
    res = _validate(src)
    assert not res.ok
    assert any(v.code == "network_denied" for v in res.violations)


def test_network_import_allowed_with_policy() -> None:
    src = CLEAN_TOOL.replace("import json", "import json\nimport socket")
    res = _validate(src, _spec(network_policy=NetworkPolicy.ALLOWLIST))
    assert res.ok, res.summary()


def test_dunder_escape_rejected() -> None:
    src = CLEAN_TOOL.replace(
        'return json.dumps({"count": len(data.get("text", "").split())})',
        'return str(type(data).__subclasses__())',
    )
    res = _validate(src)
    assert not res.ok
    assert any(v.code == "forbidden_attr" for v in res.violations)


def test_no_tool_class_rejected() -> None:
    res = _validate("import json\nx = 1\n")
    assert not res.ok
    assert any(v.code == "no_tool_class" for v in res.violations)


def test_missing_run_rejected() -> None:
    src = '''
from src.ai.tools.base import Tool


class BadTool(Tool):
    name = "bad"

    def helper(self) -> int:
        return 1
'''
    res = _validate(src)
    assert not res.ok
    assert any(v.code == "no_run_method" for v in res.violations)


def test_syntax_error_rejected() -> None:
    res = _validate("def broken(:\n  pass")
    assert not res.ok
    assert res.violations[0].code == "syntax_error"


def test_relative_import_rejected() -> None:
    src = CLEAN_TOOL.replace(
        "from src.ai.tools.base import Tool",
        "from src.ai.tools.base import Tool\nfrom . import sibling",
    )
    res = _validate(src)
    assert not res.ok
    assert any(v.code == "relative_import" for v in res.violations)
