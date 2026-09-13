# SiBase — Development Guide

## Prerequisites and local startup

Install Docker Engine/Desktop with Compose v2+ and Python 3.11+ for the launcher. The backend runs Python 3.13 in Docker; the Dashboard uses pinned Node 22. No host Node or Python packages are required. Allocate about 8 GB RAM to Docker as the initial development target, not a measured production capacity.

From the repository root:

~~~sh
make setup
make dev
make status
~~~

Dashboard: http://127.0.0.1:58200

Control API docs: http://127.0.0.1:58210/api/docs

Alpha/Beta data APIs: ports 58201/58202.

The launcher creates the separate sibase-dev Compose project and its volumes. The Phase 0 stack, credentials, ports and data are preserved. API and Dashboard source changes reload automatically; dependency or migration changes may require rebuilding with make dev.

## Commands

| Command | Purpose |
| --- | --- |
| make setup | Generate private local configuration and build the Python toolchain |
| make dev | Start services/migrations; wait for API/project health, Dashboard HTML/JS and its API proxy |
| make lint / make format | Check or apply Ruff and frontend formatting/lint rules |
| make typecheck | Run strict mypy and TypeScript checking |
| make test | Run backend pytest with ≥80% coverage and frontend Vitest tests |
| make build | Build the development API image and Dashboard static assets |
| make check | Lint, types, unit tests and build; does not require live databases |
| make integration | Run cross-service/isolation contracts against the running stack |
| make smoke | Check Dashboard HTTP proxy, health, OpenAPI and read-only responses |
| make lifecycle | After integration, seed sentinels, stop/start this stack, and verify retained rows/objects |
| make logs / make stop | Read sanitized recent logs or stop containers without deleting volumes |

Without Make, use python3 scripts/phase1.py followed by the same command. CI runs the same checks on a fresh runner. Do not claim CI has passed remotely merely because local checks passed.

## Structure and conventions

Backend: src/sibase/. Dashboard: src/dashboard/. Backend tests: tests/backend/. Frontend tests: src/dashboard/tests/. Runtime: scripts/phase1.py and infra/. See [migration boundaries](../migrations/README.md).

Use four spaces, snake_case in Python, camelCase for TypeScript values and PascalCase for React components/types. Ruff and Prettier own formatting. Test observable behavior, including permission denial and unavailable services. Future navigation placeholders must not imply functioning mutations.

## Configuration and secrets

Optional non-secret port overrides are documented in [.env.example](../.env.example). Defaults require no editing. Environment variables override .env. Published ports always bind to loopback.

Each stack keeps its bindings in its generated Compose file. Existing setup/dev commands reuse these ports unless explicitly overridden; smoke/lifecycle always read the selected stack's saved ports, ignoring current shell port overrides. For an independent local stack:

~~~sh
SIBASE_DASHBOARD_PORT=58300 SIBASE_API_PORT=58310 SIBASE_PROJECT_PORT_BASE=58301 python3 scripts/phase1.py dev --stack sibase-review
python3 scripts/phase1.py smoke --stack sibase-review
python3 scripts/phase1.py stop --stack sibase-review
~~~

A stopped selected stack must fail smoke even if another SiBase stack is healthy. Do not edit generated port bindings manually or reuse an occupied port.

The .local/sibase-dev/ directory is mode 0700 and gitignored. State/env files are 0600; individually mounted service configuration files are 0644 inside that private directory for non-root Linux container access. This is local file protection, not encryption or a secrets vault. Docker administrators can inspect service environment values.

Never publish this directory, Docker inspect environment output, or fully resolved Compose configuration. Never discard secrets while keeping matching volumes. The API receives only monitor/reader credentials; the browser receives none.

## Dependency updates

Python direct pins live in requirements.in and requirements-dev.in; hash-locked transitive dependencies live in the corresponding .lock files. Regenerate with pip-tools 7.6.1 in the pinned Python tooling container. Frontend versions and transitive packages are pinned by package.json/package-lock.json.

The selected TypeScript 5.9.3 satisfies typescript-eslint's supported peer range; do not use force/legacy-peer-deps to hide conflicts. Keep the locked runtime and development dependency sets compatible and rerun all gates after updates.

Framework references: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/), [Vite setup](https://vite.dev/guide/), [Alembic configuration](https://alembic.sqlalchemy.org/en/latest/api/config.html), [Compose service lifecycle](https://docs.docker.com/reference/compose-file/services/).
