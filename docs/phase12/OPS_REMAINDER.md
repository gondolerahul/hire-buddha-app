# Phase 12 — Ops-only remainder

> Everything in Phase 12 that is **code-complete and gate-green** but cannot be
> *finished* inside this development VM, because it needs production
> infrastructure, registry/PyPI credentials, a live canary, or a running
> frontend toolchain. Each item below is "build done, ship pending" — the human
> runs these in the prod/CI environment. Last updated 2026-06-08.

---

## 1. `02` S7 — sandbox container go-live

Code + image + egress proxy are done (see `security_review_02_sandbox.md` and the
`02` plan). Remaining is pure ops:

- [ ] **Image CVE scan** — run `trivy image hb-sandbox:<digest>` (and the
      `hb-egress-proxy` image); triage criticals before any network-granting
      canary. The image pin lives in `backend/docker/sandbox/image.pin`.
- [ ] **Registry publish** — push `hb-sandbox` + `hb-egress-proxy` to the prod
      registry; update the pinned digests.
- [ ] **Canary flip** — set `sandbox.container_runtime_enabled` ON for one
      company, watch sandbox cost + error rate, then default-ON. Network tools
      require `NetworkPolicy.ALLOWLIST` + the egress proxy.

## 2. `04` — publish `cortex-memory` to PyPI

The package is feature-complete in-repo (`backend/cortex_memory/`, mypy --strict
clean, 85% cov, builds a clean `cortex_memory-0.1.0` wheel, CI workflow present).
Remaining:

- [ ] Move to a public repo + `twine upload` to PyPI (needs PyPI token).
- [ ] Host pins `cortex-memory==0.1.0` and drops the in-repo copy.
- [ ] Lock decisions K1–K7 (`04` §4).

## 3. `06` GA canary flips (need a live canary + telemetry)

The board + tool synthesis + learning loop are code-complete behind default-OFF
flags. The canary ramps (`06` §9 rollout table) are operational, not code:

- [ ] `meta_agent.board_routing` already default-ON in dev; confirm
      `meta_cognition_migration` ran in all prod tenants before prod GA.
- [ ] `meta_agent.tool_synthesis_enabled` per-company canary (Meta-Agent only,
      container-only exec, HITL promotion of the first N DRAFT tools).
- [ ] `meta_agent.curator_consolidation_enabled` per-company canary (every merge
      HITL + audited).
- [ ] `memory.trust_score_learning` per-company canary.
- [ ] `agent_loop.llm_strategist_enabled` Meta-Agent-only pilot; A/B vs
      deterministic on the `tests/eval` harness before any wider rollout.

## 4. P-O3 — frontend Storybook / Lighthouse / Playwright

Needs the Node/browser toolchain + a running SPA; out of scope for the backend
VM. Track separately with the frontend.

## 5. C4 G4 flag soak

Dev-skipped by explicit decision (no live canary in this env), same policy as the
Stage-0 telemetry gate. The deletion already landed; this is a no-op unless a
prod soak is desired retroactively (it cannot un-delete `execute_run`).
