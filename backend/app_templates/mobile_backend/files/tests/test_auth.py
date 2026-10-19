import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location("auth", pathlib.Path(__file__).parents[1] / "app" / "auth.py")
auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(auth)


def test_bearer_reads_the_token():
    assert auth.bearer("Bearer abc.def") == "abc.def"
    assert auth.bearer("bearer  xyz ") == "xyz"


def test_bearer_refuses_other_schemes():
    assert auth.bearer(None) is None
    assert auth.bearer("Basic abc") is None
    assert auth.bearer("Bearer ") is None
