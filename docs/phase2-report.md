# Phase 2 — Local verification report

Date: 2026-09-14. Scope: internal-team local pilot, not production acceptance.

## Delivered

- Separate platform GoTrue authentication and opaque server sessions, CSRF/origin checks, workspace creation, live membership and Owner/Admin/Developer/Viewer permissions.
- Project metadata, one-time opaque API keys, atomic rotation/revocation and append-only management audit grants.
- Durable async jobs, three-attempt retry, immutable resource identities, encrypted project credentials and a separately privileged worker.
- Real per-project PostgreSQL roles/databases and Auth/REST/Storage/Realtime/S3 services; database-backed HTTP/WebSocket gateway routing.
- Dashboard login, workspace selector/create, Project List/Create/Overview, job status/retry, keys, membership/ownership transfer and audit views.
- Suspend/archive, seven-day soft-delete/restore, immediate new-request denial and existing-WebSocket revocation checks. Physical purge is deliberately unavailable.

## Verified locally

| Check | Result / evidence |
| --- | --- |
| Backend unit/regression tests | 69 passed; statement coverage 92.68% (threshold 80%) |
| Dashboard component tests | 11 passed: seven existing + four Phase 2 |
| Type checking and build | Python strict mypy and Dashboard TypeScript/Vite passed |
| Two real projects, keys, lifecycle, persistence and live SQL grants | [HTTP evidence](evidence/phase2-http.json) |
| Real platform logins for all roles and live membership revocation | [RBAC evidence](evidence/phase2-rbac.json) |
| SDK Auth/REST/Storage/signed URLs/Realtime and revocation | [10 SDK checks](evidence/phase2-sdk.json), Supabase JS 2.116.0 |
| Worker process crash after external database step | [Recovery evidence](evidence/phase2-recovery.json): exit 91, stranded running job recovered, unchanged database OIDs/container IDs |
| Full control-plane stop/dev cycle | [Restart evidence](evidence/phase2-restart.json): original rows and S3 objects retained in both projects |
| Phase 1 smoke regression | Existing Dashboard/modules/proxy and both Alpha/Beta projects passed |
| Credential audit / contributor guide | No generated credentials found in Git-visible files; `AGENTS.md` SHA-256 unchanged |
| Browser visual check | Safari Project Overview/Team/Audit reviewed; follow-up Chromium desktop/mobile E2E covers login, project/Auth overview, settings mutation, key creation/revocation and logout. [Browser evidence](evidence/phase3-browser.json) |
| Fresh-checkout GitHub CI | [Run 34808678414](https://github.com/Burinboo256/SiBase/actions/runs/34808678414) passed all jobs, including provisioning, lifecycle, SDK, Auth/RLS, browser acceptance, secret audit and crash recovery |

The actual projects are Operations and Inventory. During testing, S3 endpoint/bucket naming, already-owned bucket retries, asynchronous PostgREST schema reload, Realtime key translation and worker restart reconciliation were corrected. Two generated Storage containers were replaced to apply the bucket-name correction; their databases and volumes were retained. No Phase 0–1 data or `AGENTS.md` was modified.

## Local acceptance and deployment limits

- Local UI and fresh-checkout CI gates are closed. The fresh runner exposed missing service-image preload and a credential-audit file-permission issue; both were corrected and verified. See [combined closeout](phase2-3-acceptance.md).
- Production work is not included: TLS, invitations/SMTP/recovery UI, high availability, master-key/internal JWT rotation, physical purge and stronger project network isolation. See [operational limits](phase2-development.md#security-and-operational-limits).

Phase 2 is accepted for local development. Phase 3 adds opt-in project email verification/RLS and project signing-key rotation; see [its report](phase3-report.md). The counts above record the Phase 2 baseline; the combined suite now has 87 backend and 18 frontend tests. Code was committed/pushed with user authorization; no deployment was performed.
