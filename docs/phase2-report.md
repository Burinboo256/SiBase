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
| Browser visual check | Safari login screen verified in Phase 2; Phase 3 follow-up verified logged-in Project Overview, Team and Audit views. Responsive/mutation walkthrough remains pending |

The actual projects are Operations and Inventory. During testing, S3 endpoint/bucket naming, already-owned bucket retries, asynchronous PostgREST schema reload, Realtime key translation and worker restart reconciliation were corrected. Two generated Storage containers were replaced to apply the bucket-name correction; their databases and volumes were retained. No Phase 0–1 data or `AGENTS.md` was modified.

## Remaining acceptance / release checks

- Complete responsive and mutation-flow visual acceptance. The Phase 3 follow-up checked Project Overview/Team/Audit after login; component tests are not a replacement for the remaining end-to-end flows.
- Run the new Phase 2 GitHub CI job from a fresh checkout after authorization to commit/push. It is configured, **not yet remotely verified**. The first local bootstrap required a search-path correction; the launcher now includes it, but a fully fresh Phase 2 CI run remains the reproducibility gate.
- Production work is not included: TLS, invitations/SMTP/recovery UI, high availability, master-key/internal JWT rotation, physical purge and stronger project network isolation. See [operational limits](phase2-development.md#security-and-operational-limits).

Implementation and core local acceptance tests are complete; Phase 2 is not marked fully accepted while the above UI/CI checks remain. Phase 3 subsequently added opt-in project email verification/RLS and project signing-key rotation; see [its report](phase3-report.md). The counts above record the Phase 2 baseline. No commit, push or deployment was performed for this phase.
