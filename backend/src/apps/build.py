"""Building an app's image from a commit (Phase 14 WS6 6.7, tech spec §11.4; TD-08).

The build context is the commit as a tarball (from GitHub with an
installation token, or from the built-in Git), its top directory stripped and,
for an app in a sub-folder, only that folder. The Dockerfile comes from the
template; a tenant may edit it, and the result is scanned like the rest.

Builders (``APP_BUILDER``, default from ``PLATFORM_PROFILE``):

* ``docker`` — the local Docker CLI (development): ``docker build`` from the
  tarball on stdin; ``syft`` / ``trivy`` when installed for the SBOM and scan.
* ``acr_tasks`` — **ACR Tasks** on the apps registry (no Docker daemon in the
  cluster): the context is uploaded to the registry's build-source URL, then
  one multi-step task builds and pushes ``t-<key>/<app>:<sha>``, writes the
  SBOM with syft and scans with trivy. The platform's workload identity calls
  the ARM API.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import shutil
import tarfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

ARM = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
ACR_API = "2019-06-01-preview"


class BuildError(RuntimeError):
    pass


@dataclass
class BuildResult:
    image: str
    digest: Optional[str]
    log: str = ""
    sbom: Optional[bytes] = None
    scan: Dict[str, Any] = field(default_factory=dict)
    base_image_digest: Optional[str] = None
    external_id: Optional[str] = None


def build_context(archive: bytes, *, subdir: str = "", strip_top: bool = True) -> bytes:
    """The commit's tarball as a build context: the top directory GitHub
    (``owner-repo-sha/``) and Gitea (``repo/``) put everything under stripped
    (``strip_top``; a local ``git archive`` has none), and only ``subdir`` when given."""
    subdir = subdir.strip("/")
    source = tarfile.open(fileobj=io.BytesIO(archive), mode="r:*")
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as target:
        for member in source.getmembers():
            if not member.isfile():
                continue
            name = member.name.lstrip("./")
            if strip_top:
                if "/" not in name:
                    continue
                name = name.split("/", 1)[1]
            if subdir:
                if not name.startswith(subdir + "/"):
                    continue
                name = name[len(subdir) + 1:]
            if not name or name.startswith("/") or ".." in name.split("/"):
                continue
            data = source.extractfile(member)
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = member.size, member.mode & 0o755, member.mtime
            target.addfile(info, data)
    if not _has(out.getvalue(), "Dockerfile"):
        raise BuildError("the commit has no Dockerfile" + (f" in {subdir}/" if subdir else ""))
    return out.getvalue()


def _has(context: bytes, name: str) -> bool:
    with tarfile.open(fileobj=io.BytesIO(context), mode="r:gz") as archive:
        return any(m.name == name for m in archive.getmembers())


async def _run(*argv: str, stdin: Optional[bytes] = None, timeout: float = 1800) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE if stdin else None,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise BuildError(f"{argv[0]} {argv[1] if len(argv) > 1 else ''} timed out") from None
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


class DockerBuilder:
    name = "docker"

    async def build(self, context: bytes, *, repository: str, tag: str, labels: Dict[str, str]) -> BuildResult:
        from src.common.config import settings

        if not shutil.which("docker"):
            raise BuildError("the docker CLI is not on this machine (APP_BUILDER=docker)")
        image = f"{repository}:{tag}"
        argv = ["docker", "build", "--pull", "-t", image]
        for key, value in labels.items():
            argv += ["--label", f"{key}={value}"]
        code, out, err = await _run(*argv, "-", stdin=context, timeout=settings.APP_BUILD_TIMEOUT_SECONDS)
        log = (out + err)[-200_000:]
        if code != 0:
            raise BuildError(f"docker build failed:\n{log[-4000:]}")
        _, digest, _ = await _run("docker", "image", "inspect", "--format", "{{.Id}}", image, timeout=60)
        result = BuildResult(image=image, digest=digest.strip() or None, log=log)
        if shutil.which("syft"):
            code, sbom, _ = await _run("syft", image, "-o", "spdx-json", timeout=600)
            result.sbom = sbom.encode() if code == 0 else None
        if shutil.which("trivy"):
            code, scan, err = await _run("trivy", "image", "--quiet", "--format", "json", "--severity",
                                         "CRITICAL,HIGH", image, timeout=900)
            result.scan = summarise_trivy(scan) if code == 0 else {"error": err[-500:]}
        else:
            result.scan = {"skipped": "trivy is not installed on this machine"}
        return result


def summarise_trivy(report: str) -> Dict[str, Any]:
    """``{"tool": "trivy", "critical": n, "high": n, "top": [...]}`` from trivy's JSON."""
    try:
        data = json.loads(report or "{}")
    except ValueError:
        return {"tool": "trivy", "error": "unreadable report"}
    counts = {"critical": 0, "high": 0}
    top = []
    for result in data.get("Results") or []:
        for vuln in result.get("Vulnerabilities") or []:
            severity = str(vuln.get("Severity", "")).lower()
            if severity in counts:
                counts[severity] += 1
                if len(top) < 10:
                    top.append(f"{vuln.get('VulnerabilityID')} {vuln.get('PkgName')} {vuln.get('InstalledVersion')}")
    return {"tool": "trivy", **counts, "top": top}


class AcrTasksBuilder:
    """ACR Tasks through the ARM API: upload the context, run an encoded multi-step task, read the run."""

    name = "acr_tasks"

    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None, poll_seconds: float = 5.0) -> None:
        from src.common.config import settings

        self.subscription = settings.ACR_SUBSCRIPTION_ID
        self.group = settings.ACR_RESOURCE_GROUP
        self.registry = settings.ACR_REGISTRY_NAME
        self.login_server = settings.ACR_LOGIN_SERVER or (f"{self.registry}.azurecr.io" if self.registry else "")
        self._transport = transport
        self.poll_seconds = poll_seconds
        if not (self.subscription and self.group and self.registry):
            raise BuildError("APP_BUILDER=acr_tasks needs ACR_SUBSCRIPTION_ID, ACR_RESOURCE_GROUP, ACR_REGISTRY_NAME")

    @property
    def _base(self) -> str:
        return (f"/subscriptions/{self.subscription}/resourceGroups/{self.group}/providers/"
                f"Microsoft.ContainerRegistry/registries/{self.registry}")

    async def _arm(self, method: str, path: str, body: Any = None) -> Dict[str, Any]:
        from src.common.platform.identity import get_token_source

        token = await get_token_source().token(ARM_SCOPE)
        async with httpx.AsyncClient(base_url=ARM, transport=self._transport, timeout=60) as client:
            response = await client.request(method, path, params={"api-version": ACR_API}, json=body,
                                            headers={"Authorization": f"Bearer {token}"})
        if response.status_code >= 400:
            raise BuildError(f"ACR {method} {path.rsplit('/', 1)[-1]}: {response.status_code} {response.text[:300]}")
        return response.json() if response.content else {}

    @staticmethod
    def task_yaml(image: str, labels: Dict[str, str]) -> str:
        """Build and push; then the SBOM (syft) and the scan (trivy), whose output lands in the run log
        between markers the platform reads back."""
        label_args = " ".join(f"--label {k}={v}" for k, v in labels.items())
        return "\n".join([
            "version: v1.1.0",
            "steps:",
            f"  - build: -t {image} {label_args} -f Dockerfile .",
            f"  - push: [\"{image}\"]",
            f"  - cmd: anchore/syft:v1.18.1 {image} -o spdx-json=/workspace/sbom.json --quiet",
            "  - cmd: bash -c 'echo HB-SBOM-BEGIN; base64 -w0 /workspace/sbom.json; echo; echo HB-SBOM-END'",
            f"  - cmd: aquasec/trivy:0.58.1 image --quiet --format json --severity CRITICAL,HIGH "
            f"--output /workspace/scan.json {image}",
            "  - cmd: bash -c 'echo HB-SCAN-BEGIN; cat /workspace/scan.json; echo; echo HB-SCAN-END'",
        ]) + "\n"

    async def build(self, context: bytes, *, repository: str, tag: str, labels: Dict[str, str]) -> BuildResult:
        from src.common.config import settings

        image = f"{self.login_server}/{repository}:{tag}"
        upload = await self._arm("POST", f"{self._base}/listBuildSourceUploadUrl")
        async with httpx.AsyncClient(transport=self._transport, timeout=300) as client:
            put = await client.put(upload["uploadUrl"], content=context,
                                   headers={"x-ms-blob-type": "BlockBlob", "Content-Type": "application/gzip"})
        if put.status_code >= 400:
            raise BuildError(f"uploading the build context: {put.status_code}")
        run = await self._arm("POST", f"{self._base}/scheduleRun", {
            "type": "EncodedTaskRunRequest",
            "encodedTaskContent": base64.b64encode(self.task_yaml(image, labels).encode()).decode(),
            "sourceLocation": upload["relativePath"], "platform": {"os": "Linux", "architecture": "amd64"},
            "timeout": settings.APP_BUILD_TIMEOUT_SECONDS, "isArchiveEnabled": False})
        run_id = run.get("properties", {}).get("runId") or run.get("name")
        deadline = time.monotonic() + settings.APP_BUILD_TIMEOUT_SECONDS + 120
        while True:
            state = await self._arm("GET", f"{self._base}/runs/{run_id}")
            status = (state.get("properties") or {}).get("status")
            if status in ("Succeeded", "Failed", "Canceled", "Error", "Timeout"):
                break
            if time.monotonic() > deadline:
                raise BuildError(f"ACR run {run_id} did not finish in time")
            await asyncio.sleep(self.poll_seconds)
        log = await self._log(run_id)
        if status != "Succeeded":
            raise BuildError(f"ACR run {run_id} {status}:\n{log[-4000:]}")
        outputs = (state.get("properties") or {}).get("outputImages") or []
        digest = outputs[0].get("digest") if outputs else None
        sbom = _between(log, "HB-SBOM-BEGIN", "HB-SBOM-END")
        scan = _between(log, "HB-SCAN-BEGIN", "HB-SCAN-END")
        return BuildResult(image=image, digest=digest, log=log[-200_000:], external_id=run_id,
                           sbom=base64.b64decode(sbom) if sbom else None,
                           scan=summarise_trivy(scan) if scan else {"error": "no scan output"})

    async def _log(self, run_id: str) -> str:
        try:
            link = await self._arm("POST", f"{self._base}/runs/{run_id}/listLogSasUrl")
            async with httpx.AsyncClient(transport=self._transport, timeout=60) as client:
                response = await client.get(link["logLink"])
            return response.text
        except Exception as error:  # noqa: BLE001 - the build's outcome stands without its log
            return f"(log unavailable: {error})"


def _between(text: str, begin: str, end: str) -> Optional[str]:
    start = text.find(begin)
    stop = text.find(end, start + len(begin)) if start >= 0 else -1
    if start < 0 or stop < 0:
        return None
    return text[start + len(begin):stop].strip()


_builder: Any = None


def get_builder() -> Any:
    global _builder
    if _builder is None:
        from src.common.platform import AdapterNotAvailable, adapter_name

        name = adapter_name("app_builder")
        if name == "docker":
            _builder = DockerBuilder()
        elif name == "acr_tasks":
            _builder = AcrTasksBuilder()
        else:
            raise AdapterNotAvailable(f"APP_BUILDER={name!r} has no adapter (docker, acr_tasks)")
    return _builder


def set_builder(builder: Any) -> None:
    global _builder
    _builder = builder
