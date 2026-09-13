# Repository Guidelines

## Project Structure & Module Organization

This repository is currently a clean scaffold with no application source, tests, assets, or build configuration. As the project grows, keep production code under `src/`, tests under `tests/` (mirroring `src/` paths where practical), and static assets under `assets/` or the framework-specific public directory. Keep scripts and one-off maintenance tools in `scripts/`; place project documentation at the repository root or in `docs/`.

## Build, Test, and Development Commands

No build or development commands are defined yet. When adding a toolchain, document the canonical commands here and expose them through the project’s standard task runner (for example, `npm run dev`, `npm test`, `make build`, or `pytest`). Commands should be reproducible from a fresh checkout and should clearly distinguish formatting, linting, unit tests, integration tests, and production builds.

## Coding Style & Naming Conventions

Follow the formatter and linter selected for the project, and run them before submitting changes. Use four spaces for indentation unless the language ecosystem requires another standard; never mix tabs and spaces. Name files and directories consistently (`kebab-case` for general-purpose paths is preferred), use descriptive `camelCase` or `snake_case` identifiers according to the language, and reserve `PascalCase` for types and classes. Keep modules focused and avoid unrelated refactors.

## Testing Guidelines

Every behavior change should include or update automated tests once the test framework is established. Name tests after the behavior they verify (for example, `tests/user-authentication.test.*`). Include regression coverage for fixed bugs, keep tests deterministic, and run the full suite plus relevant focused tests locally. Record any required coverage threshold in this guide when one is adopted.

## Commit & Pull Request Guidelines

There is no commit history yet, so no existing message convention can be inferred. Use concise imperative subjects, preferably in Conventional Commit form such as `feat: add ...`, `fix: handle ...`, or `docs: update ...`. Pull requests should explain the change and validation performed, link related issues, identify configuration or migration requirements, and include screenshots or recordings for UI changes. Keep each PR focused and reviewable.

## Security & Configuration Tips

Do not commit credentials, tokens, private keys, generated secrets, or local environment files. Provide sanitized examples such as `.env.example`, document required configuration, and update ignore rules when introducing generated or machine-specific files.
