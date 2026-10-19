"""App templates on the D48 stack (Phase 14 WS6 6.6, tech spec §11.6).

``backend/app_templates/<id>/`` holds one template: ``template.yaml`` (what it
is, its port and health path, the default roles, shared files it uses) and
``files/`` (its own sources). ``_shared/`` holds what several share: the web
Dockerfile, nginx config and runtime config script, the browser Data API
client (``hb-data.ts``), the Python one (``hb_data.py``).

:func:`render` turns a template and an app's name into the files of its first
commit. Placeholders are ``{{app_name}}``, ``{{display_name}}``,
``{{tenant_key}}``, ``{{data_api_url}}`` and the template's ``params``; a
template that ``uses_blueprint`` also gets ``src/app.json`` (CRM) naming the
objects it was generated for.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "app_templates"
_APP_NAME = re.compile(r"^[a-z][a-z0-9-]{1,28}[a-z0-9]$")
_PARAM_VALUE = re.compile(r"^[A-Za-z0-9_.:/@ ,+-]{0,200}$")
_UNSAFE_TEXT = re.compile(r"[<>{}\"'`$\\\r\n]")
TEXT_SUFFIXES = {".ts", ".tsx", ".js", ".json", ".html", ".css", ".py", ".txt", ".md", ".conf", ".sh", ".yaml",
                 ".yml", ""}


class TemplateError(ValueError):
    pass


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    version: str
    stack: str
    kind: str                       # web | api | mobile
    deployable: bool
    description: str
    port: int = 8080
    health_path: str = "/healthz"
    params: Dict[str, str] = field(default_factory=dict)
    shared: Dict[str, str] = field(default_factory=dict)
    roles: List[Dict[str, Any]] = field(default_factory=list)
    public_key: Optional[Dict[str, Any]] = None
    uses_blueprint: bool = False

    def view(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "version": self.version, "stack": self.stack, "kind": self.kind,
                "deployable": self.deployable, "description": self.description, "params": dict(self.params),
                "uses_blueprint": self.uses_blueprint, "roles": [r["name"] for r in self.roles]}


@lru_cache(maxsize=1)
def templates() -> Dict[str, Template]:
    found: Dict[str, Template] = {}
    for manifest in sorted(TEMPLATES_DIR.glob("*/template.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        if manifest.parent.name.startswith("_"):
            continue
        found[data["id"]] = Template(
            id=data["id"], name=data["name"], version=str(data["version"]), stack=data["stack"], kind=data["kind"],
            deployable=bool(data.get("deployable", True)), description=data.get("description", ""),
            port=int(data.get("port", 8080)), health_path=data.get("health_path", "/healthz"),
            params={k: str(v) for k, v in (data.get("params") or {}).items()},
            shared=dict(data.get("shared") or {}), roles=list(data.get("roles") or []),
            public_key=data.get("public_key"), uses_blueprint=bool(data.get("uses_blueprint")))
    return found


def get(template_id: str) -> Template:
    try:
        return templates()[template_id]
    except KeyError:
        raise TemplateError(f"no template {template_id!r} (one of {', '.join(sorted(templates()))})") from None


def catalog() -> List[Dict[str, Any]]:
    return [t.view() for t in templates().values()]


def check_app_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not _APP_NAME.match(name) or "--" in name:
        raise TemplateError("an app's name is 3–30 lower-case letters, digits and single hyphens, starting with a "
                            "letter (it becomes part of its web address)")
    return name


def safe_text(value: str, *, length: int = 80) -> str:
    """Text that may sit inside JSX, HTML and string literals of the sources unescaped."""
    return _UNSAFE_TEXT.sub("", str(value or "")).strip()[:length]


def _fill(text: str, values: Dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def _is_text(path: str) -> bool:
    return Path(path).suffix in TEXT_SUFFIXES or Path(path).name in ("Dockerfile",)


def render(template_id: str, *, app_name: str, display_name: str, tenant_key: str = "", data_api_url: str = "",
           params: Optional[Dict[str, Any]] = None, objects: Optional[List[str]] = None) -> Dict[str, bytes]:
    """The files of an app's first commit."""
    template = get(template_id)
    values = {**template.params}
    for key, value in (params or {}).items():
        if key not in template.params:
            raise TemplateError(f"{template.id} has no parameter {key!r}")
        if not _PARAM_VALUE.match(str(value)):
            raise TemplateError(f"{key}: letters, digits and . : / @ , + - only")
        values[key] = str(value)
    values.update(app_name=check_app_name(app_name), display_name=safe_text(display_name) or app_name,
                  tenant_key=safe_text(tenant_key, length=20), data_api_url=safe_text(data_api_url, length=200))
    out: Dict[str, bytes] = {}
    root = TEMPLATES_DIR / template.id / "files"
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        out[rel] = _fill(path.read_text(encoding="utf-8"), values).encode() if _is_text(rel) else path.read_bytes()
    for source, target in template.shared.items():
        path = TEMPLATES_DIR / "_shared" / source
        out[target] = _fill(path.read_text(encoding="utf-8"), values).encode()
    if template.uses_blueprint:
        app = {"display_name": values["display_name"], "objects": list(objects or [])}
        target = "src/app.json" if template.kind == "web" else "app/app.json"
        out[target] = (json.dumps(app, indent=2) + "\n").encode()
    out["README.md"] = _readme(template, values, objects).encode()
    out[".hirebuddha.json"] = (json.dumps({"template": template.id, "template_version": template.version,
                                           "port": template.port, "health_path": template.health_path,
                                           "kind": template.kind}, indent=2) + "\n").encode()
    return out


def _readme(template: Template, values: Dict[str, str], objects: Optional[List[str]]) -> str:
    lines = [f"# {values['display_name']}", "", f"Made from the HireBuddha **{template.name}** template "
             f"(version {template.version}): {template.stack}.", "", template.description, ""]
    if objects:
        lines += ["Records it works with: " + ", ".join(f"`{o}`" for o in objects) + ".", ""]
    if template.deployable:
        lines += ["Every change is a pull request; checks run on it, and once it is merged HireBuddha builds an "
                  f"image and runs it (port {template.port}, health `{template.health_path}`).", ""]
    else:
        lines += ["This app is built and published to the stores outside HireBuddha (Expo EAS).", ""]
    return "\n".join(lines)


def default_roles(template_id: str, objects: List[str]) -> List[Dict[str, Any]]:
    """The template's roles with ``"*"`` expanded to the app's objects:
    ``[{name, description, permissions: {"objects": {...}}, own_rows}]``."""
    out = []
    for role in get(template_id).roles:
        names = objects if role.get("objects") == "*" else list(role.get("objects") or [])
        out.append({"name": role["name"], "description": role.get("description"),
                    "permissions": {"objects": {n: list(role.get("operations") or ["read"]) for n in names},
                                    "own_rows": bool(role.get("own_rows"))}})
    return out
