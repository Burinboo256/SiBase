# ADR 0005 — Isolated local control plane and durable provisioning

Status: implemented for the local pilot, 2026-09-14.

## Decision

Keep Phase 0–1 intact. Add a separate control metadata database and migration stream, platform GoTrue instance, management API, gateway and worker. Compose starts shared infrastructure; the Docker SDK provisions project Auth/PostgREST/Storage/Realtime and one SeaweedFS instance per project. Application databases remain separate databases/roles on one shared PostgreSQL cluster.

Use upstream [GoTrue](https://github.com/supabase/auth) for password authentication rather than a new password store. The BFF validates the provider token and issues a short, opaque server-side session. Membership is checked live, independently of application identities.

A durable job row records each project's desired state and generation. One local worker holds a PostgreSQL [session advisory lock](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS). External effects are idempotent and checkpointed; startup reclaims running jobs and rechecks ready projects. This is a serial local worker, not a distributed lease/fencing system.

The API cannot provision infrastructure or decrypt project secrets. [Fernet](https://cryptography.io/en/latest/fernet/) protects worker secrets at rest with a separate key from gateway tokens. External API keys are opaque and stored only as hashes. Gateway checks current key/project state before forwarding, and its [WebSocket client](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html) proxies Realtime with a revocation watchdog.

## Tradeoffs

Per-project SeaweedFS simplifies idempotent bucket credentials and suspension at the cost of more local processes. It does not change the Phase 0 S3-backend decision. Worker Docker privileges and unencrypted container runtime environments remain trusted-host boundaries. The control API has no data-network attachment; gateway and worker bridge the networks.

Soft deletion keeps resources for a seven-day user restore window; no automated purge is implemented. Internal routing JWT renewal, production secret management, distributed workers and complete Supabase SDK compatibility remain explicit follow-up work.
