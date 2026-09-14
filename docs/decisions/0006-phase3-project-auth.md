# ADR 0006 — Opt-in project Auth hardening

Date: 2026-09-14 · Status: accepted for local development; deployment limits remain in Phase 3 report

## Context

Phase 2 projects auto-confirm application users for local contract tests. Enforcing email verification and RLS across those projects silently would change working application behavior. Platform membership must remain separate from app identities.

## Decision

- Store project Auth configuration in control metadata (`control_0002`); Owner/Admin changes queue a durable generation-based reconciliation job and audit event.
- Opt in per project. Install forced public-table RLS and required email confirmation together before returning a project to ready. Preserve existing data/policies; fail on reserved template-table collisions.
- Keep per-project symmetric signing secrets encrypted in the worker vault and the existing trusted gateway route envelope. A signing epoch change regenerates internal anon/server JWTs and updates Auth, REST, Storage and Realtime configuration. DB passwords, Storage encryption keys and object volumes do not rotate.
- Use short-lived app JWTs with strict issuer/audience/project validation. Key rotation is disruptive, not a zero-downtime overlap protocol. Refresh sessions survive; opaque routing keys are independent.
- Worker reads allowlisted Auth user metadata, read-only upstream sessions and PostgreSQL policy catalogs. API/Dashboard see bounded snapshots, never credentials. Sessions adapter is pinned-version-specific; upgrades require integration tests.
- Pin local Mailpit `v1.31.1` by digest in the runtime. Keep inbox loopback-only; staging SMTP credentials are private operator configuration.

## Consequences

Existing projects require explicit hardening. Forced RLS does not repair permissive policies or make trusted administrators untrusted. Logout does not revoke unexpired access JWTs. Policy preview is inspection, not a general authorization simulator. Browser application callbacks, origins and production SMTP need explicit deployment configuration. See [development contract](../phase3-development.md).
