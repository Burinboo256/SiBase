# Migration boundaries

Three independent migration streams must remain separate:

| Stream | Location / runner | Credentials |
| --- | --- | --- |
| Platform | platform/ via Alembic; platform-migrate container | platform_owner, only the platform database |
| Project bootstrap | projects/bootstrap.sql via PostgreSQL first-volume initialization | Bootstrap administrator; never the Control API |
| Upstream services | Pinned Auth/Storage/Realtime images run their own migrations | Their project's individually scoped service login |

After Auth is healthy, project-migrate applies projects/0001_auth_claims.sql using the Auth schema owner. This compatibility function is idempotent; future project migrations need a version ledger before provisioning in Phase 2.

The platform migration creates only an installation marker and Alembic history. It does not create workspaces, memberships or project registry records yet. The API uses platform_reader with SELECT-only grants; it cannot migrate.

Application tasks and private-files policies in the contract test are synthetic test fixtures, not tables automatically provisioned for future user projects.

PostgreSQL initialization SQL runs only on empty volumes. Changing bootstrap source or a generated password does not migrate existing databases. Never delete the local secrets directory while retaining its volumes; stop the stack and plan a coordinated credential/schema migration instead.

Upgrade upstream images only with fresh bootstrap, isolation, compatibility and stop/start tests. Do not edit upstream migration history to bypass failures.
