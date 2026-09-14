# Phase 2 — Control Plane Development

## Start and verify

Requires Python 3.11+, Docker with Compose, and approximately 8 GB allocated to Docker. All ports bind to loopback. No host Python packages or Node installation is required.

```sh
make phase2-dev
make phase2-check
make phase2-integration
make phase2-recovery
make phase2-status
make phase2-stop
```

Dashboard: `http://127.0.0.1:58400`; Control API: `58410`; gateway: `58420/p/<ref>`. Ports are fixed in this local launcher. Phase 0–1 continue to use their existing commands and ports. `phase2-dev` runs migrations and seeds the initial account; reruns preserve credentials. The worker reconciles previously-ready projects after restart.

The initial account is `owner@sibase.local`; read its generated password locally from `.local/sibase-control/initial-owner.json`. Platform sessions are HttpOnly, SameSite=Strict cookies, expire within one hour, and require signing in again. The provider access token is never returned to the browser. Logout revokes the local session immediately. Public platform signup is disabled.

## Accounts and workspace permissions

```sh
python3 scripts/phase2.py user --email teammate@example.com
```

The command prints the private credential-file path, not its contents. An Owner/Admin then adds that existing account from **Team**. Email invitations, SSO and password recovery UI are not included in this phase.

| Management action | Owner | Admin | Developer | Viewer |
| --- | --- | --- | --- | --- |
| Read workspace/projects/audit | Yes | Yes | Yes | Yes |
| Create projects; retry/lifecycle | Yes | Yes | No | No |
| Create/rotate/revoke API keys | Yes | Yes | No | No |
| Manage non-Owner membership | Yes | Yes | No | No |
| Transfer ownership | Yes | No | No | No |

Any enabled platform account can create a workspace. Ownership cannot be removed or demoted directly; transfer it to an existing member. Workspace deletion is not exposed. Developer schema/policy editing belongs to later phases; its management permissions currently equal Viewer.

## Project and key lifecycle

Create requests require an `Idempotency-Key` header (8–64 ASCII letters, digits, `-`, `_`). Reusing it with the same name returns the original project; changing the request gives 409. The global pilot quota is five projects, including retained/deleted projects.

Provisioning is asynchronous: `pending → provisioning → ready`, with three automatic attempts before `failed`. Retry is available to Owner/Admin. Credentials are persisted encrypted before external resources are created. The worker uses immutable references, database identity markers, ownership labels and checkpoints to converge after lost acknowledgements.

Create keys in Project Overview; plaintext is returned once, while only a SHA-256 digest is stored. Rotation creates a replacement and revokes the previous key atomically. Existing Realtime connections are rechecked every second and closed on revocation or suspension; new HTTP requests check the database immediately. Requests already in flight may finish.

Suspend/archive stop services and retain databases/volumes. Delete is soft deletion with a seven-day restore window. After expiry, contact an operator: **there is no automatic physical purge**. Restore/resume reuses the same resources. Never run `down -v` against a stack whose data you need.

## Tests and fixtures

Backend tests cover RBAC, sessions/CSRF, idempotency, keys, lifecycle, gateway, and worker reconciliation. Dashboard tests cover login, failed jobs, role-gated controls and empty/team/audit views. `phase2-integration` uses real GoTrue accounts, PostgreSQL grants and Supabase SDK `2.116.0` for two pilot projects, **Operations** and **Inventory**. It creates synthetic rows, users and private objects, retaining them for inspection. Four `phase2-<role>@sibase.local` accounts are test fixtures; their passwords remain in `.local`.

SDK tests revoke their temporary anon keys. Create a fresh key in the Dashboard for your own application. The SDK currently warns about SiBase's opaque key format but sends it correctly; tested contracts do not imply full Supabase API compatibility. Evidence JSON under `docs/evidence/phase2-*.json` contains no credentials.

Browser CORS currently allows the two Dashboard origins (`127.0.0.1:58400` / `localhost:58400`) only. Additional application origins require configuring the gateway allowlist; do not widen the management API's trusted origins or expose this stack publicly.

## Security and operational limits

Only the local worker mounts the Docker socket and receives data-cluster administrator credentials. The API cannot read the project-secret or route tables; gateway has read-only metadata grants. Project secrets use a worker-only Fernet key; gateway routing tokens use a different key. Keep `.local/sibase-control` private and back up its keys together with database and object volumes. Losing encryption keys makes stored secrets unrecoverable.

Docker administrators can inspect runtime environment variables. Socket access is effectively host-administrator access; this design is **not** a hardened multi-tenant production deployment. Networks separate management from application services, but application projects share a data network and PostgreSQL cluster. Master-key rotation, internal JWT renewal (one-year lifetime), TLS, SMTP, rate-limit hardening, HA/fencing and physical purge need separate operator/release work. Application-user password recovery, refresh policy and RLS management are Phase 3+ work.
