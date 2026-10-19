"""Running a promotion's checks (Phase 14 WS6 6.3, tech spec §11.2 step 2).

The suite itself is ``check_suite.py`` (standard library only). Where it runs:

* :class:`LocalChecksRunner` (development, Docker sandbox): the static checks
  (secrets, code, dependencies) read the files on this machine; the
  **tests** run in the company's sandbox — the same runtime and switch as
  ``sandbox_code`` — never in the platform's own process.
* :class:`KubernetesChecksRunner` (``SANDBOX_RUNTIME=kubernetes``, AKS): one
  Kubernetes Job in the tenant's namespace on the sandbox pool (Kata), image
  ``CHECKS_IMAGE`` (gitleaks, semgrep, pip-audit, npm, trivy), which fetches
  the files from a ten-minute signed URL and runs the whole suite, tests too.
  The results are the last ``HB-CHECKS`` line of its log.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import shutil
import tarfile
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.code_lanes import check_suite

logger = logging.getLogger(__name__)

MARKER = "HB-CHECKS "
JOB_TIMEOUT_SECONDS = 900


def overall(results: List[Dict[str, Any]]) -> str:
    """``failed`` when any check failed, else ``passed``."""
    return "failed" if any(r.get("conclusion") == "failure" for r in results) else "passed"


def tarball(files: Dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for path, content in sorted(files.items()):
            info = tarfile.TarInfo(path)
            info.size = len(content)
            info.mode = 0o644
            info.mtime = int(time.time())
            archive.addfile(info, io.BytesIO(content))
    return buffer.getvalue()


def parse_marker(output: str) -> Optional[List[Dict[str, Any]]]:
    for line in reversed((output or "").splitlines()):
        if MARKER in line:
            try:
                return json.loads(line.split(MARKER, 1)[1])
            except ValueError:
                return None
    return None


class LocalChecksRunner:
    name = "local"

    async def run(self, company_id: Any, files: Dict[str, bytes], *, tests: bool = True) -> List[Dict[str, Any]]:
        work = Path(tempfile.mkdtemp(prefix="hb-checks-"))
        try:
            for path, content in files.items():
                target = work / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            results = await asyncio.to_thread(check_suite.run_suite, work, tests=False)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if tests:
            results.append(await self._tests_in_sandbox(company_id, files))
        return results

    async def _tests_in_sandbox(self, company_id: Any, files: Dict[str, bytes]) -> Dict[str, Any]:
        has_tests = any(os.path.basename(p).startswith("test_") and p.endswith(".py") for p in files) or (
            "package.json" in files and b'"test"' in files["package.json"])
        if not has_tests:
            return {"name": "tests", "conclusion": "skipped", "summary": "no tests", "tool": "none"}
        from src.ai.tools.sandbox.runtime import run_sandbox_exec
        from src.ai.tools.sandbox.skill_files import SKILLS_DIR, materialise
        from src.ai.tools.sandbox.workspace import tenant_workspace

        source = Path(check_suite.__file__).read_text(encoding="utf-8")
        runner_root = materialise(str(company_id), f"{SKILLS_DIR}/.platform/checks",
                                  hashlib.sha256(source.encode()).hexdigest(), {"check_suite.py": source})
        call_dir = os.path.join(tenant_workspace(str(company_id)), ".checks", uuid.uuid4().hex[:12])
        try:
            for path, content in files.items():
                target = os.path.join(call_dir, *path.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as handle:
                    handle.write(content)
            result = await run_sandbox_exec(
                {"company_id": str(company_id)},
                ["python3", os.path.join(runner_root, "check_suite.py"), call_dir, "--tests", "--json"],
                cwd=call_dir, timeout=check_suite.TOOL_TIMEOUT)
        finally:
            shutil.rmtree(call_dir, ignore_errors=True)
        if result.launch_error or result.timed_out:
            reason = result.launch_error or "timed out"
            return {"name": "tests", "conclusion": "neutral", "summary": f"tests not run: {reason}"[:2000],
                    "tool": "sandbox"}
        parsed = parse_marker(result.stdout) or []
        found = next((r for r in parsed if r.get("name") == "tests"), None)
        return found or {"name": "tests", "conclusion": "neutral",
                         "summary": f"the sandbox reported nothing: {(result.stderr or result.stdout)[-1000:]}",
                         "tool": "sandbox"}


class KubernetesChecksRunner:
    name = "kubernetes"

    def __init__(self, kube: Any = None, *, poll_seconds: float = 3.0) -> None:
        self._kube = kube
        self.poll_seconds = poll_seconds

    @property
    def kube(self) -> Any:
        if self._kube is None:
            from src.common.platform.kube import get_kube

            self._kube = get_kube()
        return self._kube

    @staticmethod
    def job_manifest(namespace: str, name: str, source_url: str) -> Dict[str, Any]:
        from src.common.config import settings

        return {
            "apiVersion": "batch/v1", "kind": "Job",
            "metadata": {"name": name, "namespace": namespace, "labels": {"hb/role": "checks"}},
            "spec": {
                "backoffLimit": 0, "ttlSecondsAfterFinished": 3600, "activeDeadlineSeconds": JOB_TIMEOUT_SECONDS,
                "template": {
                    "metadata": {"labels": {"hb/role": "checks", "job-name": name}},
                    "spec": {
                        "restartPolicy": "Never", "automountServiceAccountToken": False,
                        "runtimeClassName": settings.SANDBOX_K8S_RUNTIME_CLASS or None,
                        "nodeSelector": {"hb/pool": settings.SANDBOX_K8S_NODE_POOL},
                        "tolerations": [{"key": "hb/pool", "operator": "Equal",
                                         "value": settings.SANDBOX_K8S_NODE_POOL, "effect": "NoSchedule"}],
                        "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001,
                                            "seccompProfile": {"type": "RuntimeDefault"}},
                        "containers": [{
                            "name": "checks", "image": getattr(settings, "CHECKS_IMAGE", "") or "hb-checks:local",
                            "args": ["/work", "--fetch", source_url, "--tests", "--json"],
                            "env": [{"name": "HOME", "value": "/tmp"}],
                            "resources": {"requests": {"cpu": "500m", "memory": "1Gi"},
                                          "limits": {"cpu": "2", "memory": "2Gi", "ephemeral-storage": "2Gi"}},
                            "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                                "capabilities": {"drop": ["ALL"]}},
                            "volumeMounts": [{"name": "work", "mountPath": "/work"}, {"name": "tmp", "mountPath": "/tmp"}],
                        }],
                        "volumes": [{"name": "work", "emptyDir": {"sizeLimit": "1Gi"}},
                                    {"name": "tmp", "emptyDir": {"sizeLimit": "1Gi"}}],
                    },
                },
            },
        }

    async def run(self, company_id: Any, files: Dict[str, bytes], *, tests: bool = True) -> List[Dict[str, Any]]:
        from src.common.platform.kube import path_for
        from src.common.platform.storage import company_namespace, get_storage
        from src.common.tenancy.directory import directory

        location = await directory.get(company_id)
        namespace = f"t-{location.key}"
        name = f"checks-{uuid.uuid4().hex[:10]}"
        key = f"{company_namespace(company_id)}/scratch/checks/{name}.tar.gz"
        storage = get_storage()
        await storage.put(key, tarball(files), content_type="application/gzip")
        url = await storage.signed_url(key, ttl_seconds=600)
        if not url:
            raise RuntimeError("the storage adapter gives no signed URLs: checks Jobs need Blob storage")
        try:
            await self.kube.apply(self.job_manifest(namespace, name, url))
            deadline = time.monotonic() + JOB_TIMEOUT_SECONDS + 60
            while True:
                job = await self.kube.get(path_for("Job", namespace, name))
                status = job.get("status") or {}
                if status.get("succeeded") or status.get("failed"):
                    break
                if time.monotonic() > deadline:
                    return [{"name": "checks", "conclusion": "failure", "summary": "the checks Job timed out",
                             "tool": "kubernetes"}]
                await asyncio.sleep(self.poll_seconds)
            pods = await self.kube.list(path_for("Pod", namespace), labels={"job-name": name})
            output = await self.kube.logs(namespace, pods[0]["metadata"]["name"], tail=50) if pods else ""
        finally:
            await storage.delete(key)
        parsed = parse_marker(output)
        if parsed is None:
            return [{"name": "checks", "conclusion": "failure", "summary": f"no results: {output[-1000:]}",
                     "tool": "kubernetes"}]
        return parsed


def checks_runner() -> Any:
    from src.common.config import settings

    if (settings.SANDBOX_RUNTIME or "").lower() == "kubernetes":
        return KubernetesChecksRunner()
    return LocalChecksRunner()
