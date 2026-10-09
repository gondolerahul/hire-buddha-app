"""The API's full route table, written into 17-api-reference.md (API-17, API-I1).

A path is three concatenations away from its decorator — the mount prefix in
``main.py``, the router's prefix, the decorator's path — so reading the code
gives the wrong URL. This lists every route the app really serves: method,
full path, the guard its dependencies apply, and the module that declares it.

    python scripts/route_census.py            # print the table
    python scripts/route_census.py --write    # rewrite the block in the doc

``tests/unit/test_route_census.py`` fails when the doc's block is not what this
prints, so a route added, moved or removed without the doc fails the suite.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Iterable

BACKEND = Path(__file__).resolve().parents[1]
DOC = BACKEND.parent / "docs" / "current" / "17-api-reference.md"
START = "<!-- route-census:start -->"
END = "<!-- route-census:end -->"


def _dependencies(dependant: Any) -> Iterable[Any]:
    for dep in getattr(dependant, "dependencies", []) or []:
        yield dep.call
        yield from _dependencies(dep)


def guard(route: Any) -> str:
    """What a caller needs, as the route's dependencies require it."""
    from fastapi.routing import APIWebSocketRoute

    if isinstance(route, APIWebSocketRoute):
        return "own handshake"
    found: list[str] = []
    for call in _dependencies(route.dependant):
        name = getattr(call, "__name__", type(call).__name__)
        if type(call).__name__ == "RoleChecker":
            roles = sorted(str(getattr(r, "value", r)) for r in call.allowed_roles)
            found.append("roles: " + ", ".join(roles))
        elif name == "get_current_user_from_query":
            found.append("URL token")
        elif name == "require_internal":
            found.append("internal token")
        elif name.startswith("get_current_user") or name == "get_current_active_user":
            found.append("signed in")
    if not found:
        return "—"
    # The narrowest guard says the most: roles over a bare sign-in.
    roles = [g for g in found if g.startswith("roles:")]
    return roles[0] if roles else found[0]


def rows() -> list[tuple[str, str, str, str, bool]]:
    sys.path.insert(0, str(BACKEND))
    from fastapi.routing import APIRoute, APIWebSocketRoute

    from src.main import app

    out = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in sorted(route.methods or ()):
                out.append((route.path, method, guard(route), route.endpoint.__module__,
                            bool(route.deprecated)))
        elif isinstance(route, APIWebSocketRoute):
            out.append((route.path, "WS", guard(route), route.endpoint.__module__, False))
    return sorted(set(out))


def table() -> str:
    lines = [
        START,
        "",
        "| Method | Path | Guard | Module |",
        "|---|---|---|---|",
    ]
    for path, method, who, module, deprecated in rows():
        shown = f"`{path}`" + (" *(deprecated)*" if deprecated else "")
        lines.append(f"| {method} | {shown} | {who} | `{module}` |")
    lines += ["", END]
    return "\n".join(lines)


def doc_block(text: str) -> str:
    """The census block as the doc has it (LF line endings)."""
    text = text.replace("\r\n", "\n")
    start, end = text.find(START), text.find(END)
    if start < 0 or end < 0:
        return ""
    return text[start:end + len(END)]


def write() -> None:
    raw = DOC.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    text = raw.replace("\r\n", "\n")
    block = doc_block(text)
    if not block:
        raise SystemExit(f"{DOC.name} has no {START} … {END} block")
    text = text.replace(block, table())
    DOC.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite the block in 17-api-reference.md")
    args = parser.parse_args()
    if args.write:
        write()
        print(f"wrote {len(rows())} routes into {DOC}")
    else:
        print(table())


if __name__ == "__main__":
    main()
