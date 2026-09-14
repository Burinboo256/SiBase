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
| Backend unit/regression suite | 87 passed; statement coverage 92.53%, threshold 80% |
| Dashboard component suite | 18 passed, including Auth tabs, callback secret removal, public-only demo configuration and empty-workspace regression |
| Static/build checks | Ruff, strict mypy (15 source files), ESLint, Prettier and TypeScript/Vite passed |
| Real Auth/RLS integration | [10 checks](evidence/phase3-auth.json): two email confirmations, unconfirmed login denial, owner-row CRUD/spoof protection, expiry/issuer/audience/cross-project denial, default-deny future tables, refresh reuse, logout, recovery replay, snapshots and signing rotation |
| JavaScript SDK after signing rotation | [4 checks](evidence/phase3-sdk.json): signup/verifyOtp for two users, owner-row isolation/refreshSession, authenticated Realtime subscribe/broadcast and signOut |
| Phase 2 regression after Phase 3 changes | Full HTTP lifecycle/grants, real-account RBAC and 10 Auth/REST/Storage/Realtime SDK checks rerun successfully; [HTTP](evidence/phase2-http.json), [RBAC](evidence/phase2-rbac.json), [SDK](evidence/phase2-sdk.json) |
| WebSocket JWT validation | Unit tests reject expired/wrong-issuer/wrong-audience/privileged-role JWTs before forwarding join frames; supports object and Phoenix array frames |
| Safari, logged-in owner | Project Overview, Users, Sessions, Auth Settings and Permission preview checked against real Auth Sandbox metadata; Auth Settings screenshot inspected. Team and Audit log also displayed correctly |
| Chromium browser E2E | [7 groups](evidence/phase3-browser.json): actual desktop/mobile login, settings mutation, key creation/revocation, two-user email flows, RLS, refresh, recovery/password change/replay and logout; [runner contract](browser-acceptance.md) |
| Contributor guide / secrets | `AGENTS.md` SHA-256 unchanged; no full JWTs or opaque API keys found in Git-visible files |
| Fresh-checkout GitHub CI | [Run 34808678414](https://github.com/Burinboo256/SiBase/actions/runs/34808678414) passed both jobs, including browser acceptance, secret audit and worker crash recovery |

Testing caught and fixed an Auth panel mounted under Team instead of Project Overview, which broke an empty workspace. Live UI review also exposed that metadata can lag during provisioning: the panel now shows collection time, distinguishes polling from collection and warns on snapshots older than 30 seconds.

Auth Sandbox is separate from Operations/Inventory; no automatic hardening was applied to the Phase 2 projects. All three projects finished `ready` / `healthy` with no job error. Synthetic users, task rows and inbox messages are retained for inspection. Test-created containers may be recreated for configuration changes; no project databases or object volumes were deleted.

## Deployment limits and later-phase work

- Local acceptance and fresh-checkout CI gates are closed for code revision `62165be`; see [combined closeout](phase2-3-acceptance.md). Code was committed/pushed with authorization; no deployment was performed.
- The principal local responsive/mutation flows now pass Chromium E2E; exhaustive all-browser accessibility and every management action remain broader MVP acceptance work.
- A loopback-only `/app-test` now handles real confirmation/recovery callbacks for local acceptance; configure the production application's callback and gateway origin allowlist before staging.
- Validate real staging SMTP/TLS/sender/delivery and rate limits before sending real email. Local Mailpit contains sensitive one-time links and must remain private.
- Policy preview is a bounded inventory, not a general permission simulator. Forced RLS preserves existing permissive policies; views/RPC and detailed Realtime row-event authorization remain Phase 4/6 work.
- Logout revokes refresh tokens, not unexpired access JWTs. Refresh immediate-parent retry is an upstream exception even with zero grace. Read-only sessions adapter is pinned-version-specific.
- Upstream deprecation warnings remain (Starlette test client, npm transitive uuid). SDK warns about SiBase's opaque key format; the recorded contracts pass, not a claim of full Supabase compatibility.

Phase 3 is accepted for local development. External SMTP and production infrastructure are deliberately deferred deployment gates, not claims covered by this acceptance. See [developer contract](phase3-development.md) and [ADR 0006](decisions/0006-phase3-project-auth.md).
