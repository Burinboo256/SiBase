# ADR 0004 — Local control-plane foundation

Date: 2026-09-13 · Scope: Phase 1 local development

## Decision

Keep Phase 0 as a reproducible legacy PoC and generate a separate sibase-dev stack. Reuse the tested data-plane generator with explicit output directory, port range and independent role passwords. Do not mutate old secrets/volumes to perform an implicit migration.

Use a separate PostgreSQL instance for platform metadata. platform_owner runs Alembic; platform_reader serves read-only readiness. Project databases remain on a shared data-plane cluster; each has six distinct login passwords, including a SELECT-1-only monitor connection with no application-table grants.

FastAPI provides liveness, readiness and an allowlisted overview response. It probes fixed operator-configured service URLs, not client-supplied destinations. React/Vite uses a same-origin /api proxy; no backend credentials are bundled or returned.

## Consequences

- More containers locally, but no port or volume collision with Phase 0.
- Platform identity and authorization remain Phase 2 work. All published endpoints must stay loopback-only.
- A successful health probe is not proof of all service operations or RLS; integration tests remain a separate gate.
- Dashboard future pages are explicitly planned placeholders. Only overview/health and Control API reference work in Phase 1.
- App logs allowlist request ID, method, known route, status and duration. They exclude headers, body, query strings and raw upstream exceptions.
- File-backed local configuration is not an encrypted secrets manager. Before staging, add platform identity, TLS, rate limits, rotation and a reviewed network boundary.
