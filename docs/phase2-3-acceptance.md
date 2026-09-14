# Phase 2–3 — Acceptance closeout

Date: 2026-09-14 · Target: internal-team local development, not production deployment.

Status: **accepted for local development**. Phase 2–3 closeout is complete; Phase 4 can begin.

## Scope and checks

- Backend: 87 tests, 92.53% statement coverage; strict Python types and lint.
- Frontend: 18 component tests; ESLint, formatting, TypeScript and production build.
- Phase 2: real project provisioning/lifecycle, role matrix, SDK service contracts, worker crash recovery and retained data.
- Phase 3: 10 Auth/RLS integration groups, four SDK groups and seven Chromium browser acceptance groups.
- Browser: real signup/confirmation, recovery/password change/replay denial, user-row isolation, refresh/logout, Dashboard settings/key mutations and desktop/mobile layout.
- Git-visible credential audit passed; `AGENTS.md` remains unchanged.

## GitHub verification

The first run, [34807323317](https://github.com/Burinboo256/SiBase/actions/runs/34807323317), passed Phase 1 but failed fresh project provisioning. The launcher had relied on data-service images already being present locally; Docker's create-container API does not download missing images. Startup now preloads every pinned Auth/REST/Storage/Realtime/S3 image, with regression tests for cached and missing-image cases. Worker diagnostics expose only the exception class, never upstream credential-bearing text.

[Run 34807687931](https://github.com/Burinboo256/SiBase/actions/runs/34807687931) then passed provisioning, Auth/RLS and browser acceptance, but the host-side secret scanner could not read a container-owned `0600` synthetic credential fixture. Git now supplies its inventory as the checkout owner and only the read-only scanner runs with sufficient CI privileges. File permissions remain private; empty inventories fail closed and matched values are never printed.

Verified code commit: `62165befbd29702cb208b08611a6012f16a21954`. [Final verification run](https://github.com/Burinboo256/SiBase/actions/runs/34808678414) **passed both jobs**, including all Phase 2–3 integration/browser checks, secret audit and worker crash recovery. Completed 2026-09-14 05:18 UTC. [Sanitized CI evidence](evidence/phase2-3-ci.json) records the exact revision. The subsequent documentation-only closeout commit does not change runtime/test code.

Non-blocking CI notice: the pinned checkout action targets deprecated Node 20 and GitHub currently runs it with Node 24. Updating the action pin and remaining dependency deprecations is tracked as maintenance, not hidden as a passing security audit.

## Deferred deployment work

External SMTP delivery/TLS/sender validation, production callback/origin configuration, HTTPS, rate limits, infrastructure hardening and broad multi-browser accessibility remain staging/MVP gates. These are not covered by local acceptance. Views/RPC authorization and full Realtime row-change behavior remain Phase 4/6.

The local demo at `/app-test` uses only synthetic data and public project configuration; it is not the production application's frontend. See [browser instructions](browser-acceptance.md), [Phase 2 report](phase2-report.md), and [Phase 3 report](phase3-report.md).
