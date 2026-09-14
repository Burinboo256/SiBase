# Phase 2–3 browser acceptance

Run after the local stack and Phase 2/3 integration fixtures are ready:

```sh
make phase3-e2e
```

This uses pinned Playwright 1.63.0/Chromium in a test-only Docker container, without a host browser installation. The image and npm lockfile match. It exercises real services, not mocked responses. Container-local forwarding preserves the actual `127.0.0.1:58400` Dashboard and `58420` gateway URLs, including CORS and email redirects. See [official Docker guidance](https://playwright.dev/docs/docker).

## Covered workflow

- Owner login → Auth Sandbox → apply Auth settings → wait for durable reconciliation.
- Users/Sessions/Auth Settings/Permission preview, Team/Audit and 1280×900 / 390×844 layouts.
- Create/show-once/hide an anon key through Dashboard.
- Two independent browser contexts: signup → real Mailpit confirmation → callback → owner-row isolation → refresh.
- Logout → recovery email → change password → reject old password → accept new password → reject reused recovery link.
- Revoke the test key through Dashboard → deny app requests → platform logout.

The runner changes only Auth Sandbox's callback setting to the local default, adds synthetic app accounts/tasks, and creates/revokes one anon key. Do not run it against production or external SMTP. Failure output records only a stage and error class. No traces, HAR, video or credential dumps are emitted. Screenshots remain gitignored under `.local/sibase-control/browser/`; sanitized results go to `docs/evidence/phase3-browser.json`.

## Try the app manually

Open `http://127.0.0.1:58400/app-test`, enter Auth Sandbox's project reference and a newly created **anon** key. Public configuration is stored in localStorage; passwords/access/refresh tokens are not. Configure the project's callback as `http://127.0.0.1:58400/auth/callback` and open email links on the same browser origin.

The callback clears query/fragment secrets immediately and loads the test app when its public configuration exists; otherwise it shows the safe landing page. The demo is loopback-only, has no automatic refresh or persistent sessions, and reload requires signing in. “Forget project” clears local configuration; use “Sign out of app” first to revoke refresh sessions. This is an acceptance fixture, not the production application UI.
