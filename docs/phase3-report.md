# Phase 3 — Local verification report

Date: 2026-09-14. Scope: application Auth and row-level permissions for the internal-team local pilot. Not production/staging acceptance.

## Delivered

- Per-project, Owner/Admin-managed Auth configuration with required email confirmation, password recovery, refresh rotation and explicit logout semantics.
- Local Mailpit inbox pinned by image digest, plus private operator SMTP configuration. No real SMTP provider was contacted.
- JWT lifetime/issuer/audience/project binding and hard-cut signing rotation, including Realtime tenant-key updates. Existing refresh sessions and opaque API keys survive signing rotation.
- Forced RLS migration/event trigger for public tables and an owner-row `phase3_tasks` template. Existing data/policies are retained; projects opt in individually.
- Worker-only, allowlisted Users/Sessions/policy snapshots; Dashboard Users, Sessions, Auth Settings and Permission preview. Local callback clears URL secrets without creating a platform session.
- Repeatable `make phase3-*` commands and an additional Phase 3 integration step in the existing control-plane CI job.

## Verified locally

| Check | Result / evidence |
| --- | --- |
| Backend unit/regression suite | 82 passed; statement coverage 92.52%, threshold 80% |
| Dashboard component suite | 14 passed, including Auth tabs, callback secret removal and empty-workspace regression |
| Static/build checks | Ruff, strict mypy (15 source files), ESLint, Prettier and TypeScript/Vite passed |
| Real Auth/RLS integration | [10 checks](evidence/phase3-auth.json): two email confirmations, unconfirmed login denial, owner-row CRUD/spoof protection, expiry/issuer/audience/cross-project denial, default-deny future tables, refresh reuse, logout, recovery replay, snapshots and signing rotation |
| JavaScript SDK after signing rotation | [4 checks](evidence/phase3-sdk.json): signup/verifyOtp for two users, owner-row isolation/refreshSession, authenticated Realtime subscribe/broadcast and signOut |
| Phase 2 regression after Phase 3 changes | Full HTTP lifecycle/grants, real-account RBAC and 10 Auth/REST/Storage/Realtime SDK checks rerun successfully; [HTTP](evidence/phase2-http.json), [RBAC](evidence/phase2-rbac.json), [SDK](evidence/phase2-sdk.json) |
| WebSocket JWT validation | Unit tests reject expired/wrong-issuer/wrong-audience/privileged-role JWTs before forwarding join frames; supports object and Phoenix array frames |
| Safari, logged-in owner | Project Overview, Users, Sessions, Auth Settings and Permission preview checked against real Auth Sandbox metadata; Auth Settings screenshot inspected. Team and Audit log also displayed correctly |
| Contributor guide / secrets | `AGENTS.md` SHA-256 unchanged; no full JWTs or opaque API keys found in Git-visible files |

Testing caught and fixed an Auth panel mounted under Team instead of Project Overview, which broke an empty workspace. Live UI review also exposed that metadata can lag during provisioning: the panel now shows collection time, distinguishes polling from collection and warns on snapshots older than 30 seconds.

Auth Sandbox is separate from Operations/Inventory; no automatic hardening was applied to the Phase 2 projects. All three projects finished `ready` / `healthy` with no job error. Synthetic users, task rows and inbox messages are retained for inspection. Test-created containers may be recreated for configuration changes; no project databases or object volumes were deleted.

## Remaining acceptance and limits

- GitHub CI is configured but **not run for this worktree**. Fresh-checkout reproducibility remains a release gate. No commit/push/deployment in this round.
- Safari checks covered navigation/read-only data, not a complete responsive or mutation-flow browser E2E. Existing component/API tests cover those mutations separately.
- Configure an actual app callback and gateway origin allowlist before browser-app integration. The default callback is deliberately a local landing page, not an end-user recovery UI.
- Validate real staging SMTP/TLS/sender/delivery and rate limits before sending real email. Local Mailpit contains sensitive one-time links and must remain private.
- Policy preview is a bounded inventory, not a general permission simulator. Forced RLS preserves existing permissive policies; views/RPC and detailed Realtime row-event authorization remain Phase 4/6 work.
- Logout revokes refresh tokens, not unexpired access JWTs. Refresh immediate-parent retry is an upstream exception even with zero grace. Read-only sessions adapter is pinned-version-specific.
- Upstream deprecation warnings remain (Starlette test client, npm transitive uuid). SDK warns about SiBase's opaque key format; the recorded contracts pass, not a claim of full Supabase compatibility.

Implementation and core local Auth/RLS checks are complete; Phase 3 is not marked fully accepted until the applicable gates above are resolved. See [developer contract](phase3-development.md) and [ADR 0006](decisions/0006-phase3-project-auth.md).
