// Real headless Chromium acceptance against the local Compose services.
// Never emit browser traces, network bodies, credentials or raw exception text.
import assert from 'node:assert/strict';
import { createServer, request as httpRequest } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { chromium } from 'playwright';

const origin = 'http://127.0.0.1:58400';
const checks = [], proxies = [];
let stage = 'setup', browser, key, base, control;
const errors = [];
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const passed = name => { checks.push(name); console.log('PASS:', name); };

// Preserve real public callback/origin URLs inside the isolated test container.
async function proxy(port, hostname, upstreamPort) {
    const server = createServer((req, res) => {
        const upstream = httpRequest({ hostname, port: upstreamPort, path: req.url, method: req.method, headers: req.headers }, response => {
            res.writeHead(response.statusCode, response.headers); response.pipe(res);
        });
        upstream.on('error', () => { res.writeHead(502); res.end(); });
        req.pipe(upstream);
    });
    await new Promise(resolve => server.listen(port, '127.0.0.1', resolve));
    proxies.push(server);
}

async function mailboxLink(email, kind, ref) {
    for (let i = 0; i < 30; i++) {
        const found = await (await fetch('http://mailpit:8025/api/v1/search?query=' + encodeURIComponent('to:' + email))).json();
        for (const item of found.messages ?? []) {
            const message = await (await fetch('http://mailpit:8025/api/v1/message/' + item.ID)).json();
            for (const link of (message.Text ?? '').match(/https?:\/\/[^\s<>"\)]+/g) ?? []) {
                const url = new URL(link.replaceAll('&amp;', '&'));
                if (url.origin === 'http://127.0.0.1:58420' && url.pathname === `/p/${ref}/auth/v1/verify` && url.searchParams.get('type') === kind) return url.href;
            }
        }
        await delay(1000);
    }
    throw new Error('Expected local email missing');
}

async function visible(locator) { await locator.waitFor({ state: 'visible', timeout: 30000 }); }
async function screenshot(page, name) {
    await page.screenshot({ path: '/workspace/.local/sibase-control/browser/' + name + '.png', fullPage: true });
}
async function noOverflow(page) {
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'Horizontal overflow');
}

try {
    await mkdir('/workspace/.local/sibase-control/browser', { recursive: true, mode: 0o700 });
    await proxy(58400, 'dashboard', 5173);
    await proxy(58420, 'gateway', 8000);
    const owner = JSON.parse(await readFile('/workspace/.local/sibase-control/initial-owner.json', 'utf8'));
    const login = await fetch('http://api:8000/api/v2/login', { method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: JSON.stringify(owner) });
    assert.equal(login.status, 200);
    const logged = await login.json();
    const headers = { Origin: origin, Cookie: login.headers.getSetCookie().map(c => c.split(';')[0]).join('; '), 'Content-Type': 'application/json', 'X-CSRF-Token': logged.csrf };
    control = (path, method = 'GET', body) => fetch('http://api:8000/api/v2' + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const workspaces = await (await control('/workspaces')).json();
    const wid = workspaces.find(w => w.name === 'Internal team').id;
    const projectPath = `/workspaces/${wid}/projects`;
    const projects = await (await control(projectPath)).json();
    const project = projects.find(p => p.name === 'Auth Sandbox');
    assert.equal(project.status, 'ready');
    base = projectPath + '/' + project.id;
    async function ready() {
        for (let i = 0; i < 120; i++) {
            const current = (await (await control(projectPath)).json()).find(p => p.id === project.id);
            if (current.status === 'ready') return;
            assert.notEqual(current.status, 'failed');
            await delay(2000);
        }
        throw new Error('Project did not become ready');
    }
    browser = await chromium.launch({ headless: true });
    const adminContext = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const admin = await adminContext.newPage();
    admin.setDefaultTimeout(30000);
    admin.on('pageerror', () => errors.push('admin'));
    stage = 'owner dashboard login';
    await admin.goto(origin);
    await admin.getByLabel('Email', { exact: true }).fill(owner.email);
    await admin.getByLabel('Password', { exact: true }).fill(owner.password);
    await admin.getByRole('button', { name: 'Sign in', exact: true }).click();
    await admin.getByRole('button', { name: /Auth Sandbox.*Open project/ }).click();
    await visible(admin.getByRole('heading', { name: 'Application authentication', exact: true }));
    await noOverflow(admin);
    passed('Platform owner browser login and project/Auth overview');

    stage = 'Auth settings mutation';
    await admin.getByRole('button', { name: 'Auth Settings', exact: true }).click();
    await admin.getByLabel('Application callback URL').fill(origin + '/auth/callback');
    admin.once('dialog', dialog => dialog.accept());
    const configured = admin.waitForResponse(response => response.url().endsWith(base + '/auth') && response.request().method() === 'PUT');
    await admin.getByRole('button', { name: 'Apply Auth settings', exact: true }).click();
    assert.equal((await configured).status(), 202);
    await ready();
    for (const tab of ['Users', 'Sessions', 'Permission preview', 'Auth Settings']) {
        await admin.getByRole('button', { name: tab, exact: true }).click();
        await noOverflow(admin);
    }
    await screenshot(admin, 'auth-desktop');
    await admin.setViewportSize({ width: 390, height: 844 });
    await noOverflow(admin);
    await screenshot(admin, 'auth-mobile');
    for (const tab of ['Team', 'Audit log', 'Projects']) {
        await admin.getByRole('button', { name: tab, exact: true }).click();
        await noOverflow(admin);
    }
    await admin.setViewportSize({ width: 1280, height: 900 });
    passed('Auth Settings apply/reconcile, all Auth tabs, Team/Audit and mobile layout');

    stage = 'one-time project key creation';
    const issued = admin.waitForResponse(response => response.url().endsWith(base + '/keys') && response.request().method() === 'POST');
    await admin.getByRole('button', { name: 'Create anon key', exact: true }).click();
    const keyResponse = await issued;
    assert.equal(keyResponse.status(), 201);
    key = await keyResponse.json();
    await visible(admin.getByText('Save this key now — it cannot be displayed again.'));
    await admin.getByRole('button', { name: 'I saved it · Hide' }).click();
    passed('Dashboard creates and hides a one-time anon project key');

    const run = randomUUID().slice(0, 8);
    const accounts = [];
    for (const name of ['alice', 'bob']) {
        stage = name + ' browser signup and confirmation';
        const context = await browser.newContext({ viewport: name === 'bob' ? { width: 390, height: 844 } : { width: 1280, height: 900 } });
        const page = await context.newPage();
        page.setDefaultTimeout(30000);
        page.on('pageerror', () => errors.push(name));
        const account = { email: `browser-${name}-${run}@example.com`, password: randomUUID() + 'aA1!', page };
        accounts.push(account);
        await page.goto(origin + '/app-test');
        await page.getByLabel('Project reference', { exact: true }).fill(project.ref);
        await page.getByLabel('Public anon key', { exact: true }).fill(key.key);
        await page.getByRole('button', { name: 'Connect project', exact: true }).click();
        await page.getByLabel('Email', { exact: true }).fill(account.email);
        await page.getByLabel('Password', { exact: true }).fill(account.password);
        await page.getByRole('button', { name: 'Create app account', exact: true }).click();
        await visible(page.getByText('Check the local inbox to confirm your email, then sign in.'));
        const link = await mailboxLink(account.email, 'signup', project.ref);
        await page.goto(link);
        await visible(page.getByTestId('app-user').filter({ hasText: account.email }));
        assert.equal(new URL(page.url()).hash, '');
        assert.equal(new URL(page.url()).search, '');
        await noOverflow(page);
    }
    passed('Desktop/mobile app signup, real email links and secret-free callback URLs');

    const [alice, bob] = accounts;
    const task = 'browser-task-' + run;
    stage = 'browser owner-row permissions and refresh';
    await alice.page.getByLabel('Task title').fill(task);
    await alice.page.getByRole('button', { name: 'Add my task', exact: true }).click();
    await visible(alice.page.getByRole('list', { name: 'My tasks' }).getByText(task, { exact: true }));
    await bob.page.getByRole('button', { name: 'Load my tasks', exact: true }).click();
    await bob.page.waitForFunction(() => !document.querySelector('button:disabled'));
    assert.equal(await bob.page.getByRole('list', { name: 'My tasks' }).getByText(task, { exact: true }).count(), 0);
    await alice.page.getByRole('button', { name: 'Refresh session', exact: true }).click();
    await visible(alice.page.getByText('Application session refreshed.'));
    await screenshot(bob.page, 'app-mobile');
    passed('Browser owner-row isolation and refresh-session action');

    stage = 'browser logout, recovery and password change';
    await alice.page.getByRole('button', { name: 'Sign out of app', exact: true }).click();
    await visible(alice.page.getByRole('heading', { name: 'Account access', exact: true }));
    await alice.page.getByLabel('Recovery email').fill(alice.email);
    await alice.page.getByRole('button', { name: 'Send recovery email', exact: true }).click();
    await visible(alice.page.getByText('If the account exists, a recovery email has been sent to the local inbox.'));
    const recovery = await mailboxLink(alice.email, 'recovery', project.ref);
    await alice.page.goto(recovery);
    await visible(alice.page.getByTestId('app-user').filter({ hasText: alice.email }));
    const replacement = randomUUID() + 'bB2!';
    await alice.page.getByLabel('New password', { exact: true }).fill(replacement);
    await alice.page.getByRole('button', { name: 'Update app password', exact: true }).click();
    await visible(alice.page.getByText('Password updated. Sign out and sign in with the new password.'));
    await alice.page.getByRole('button', { name: 'Sign out of app', exact: true }).click();
    await visible(alice.page.getByRole('heading', { name: 'Account access', exact: true }));
    await alice.page.getByLabel('Email', { exact: true }).fill(alice.email);
    await alice.page.getByLabel('Password', { exact: true }).fill(alice.password);
    await alice.page.getByRole('button', { name: 'Sign in to app', exact: true }).click();
    await visible(alice.page.getByRole('alert'));
    await alice.page.getByLabel('Email', { exact: true }).fill(alice.email);
    await alice.page.getByLabel('Password', { exact: true }).fill(replacement);
    await alice.page.getByRole('button', { name: 'Sign in to app', exact: true }).click();
    await visible(alice.page.getByTestId('app-user').filter({ hasText: alice.email }));
    await alice.page.getByRole('button', { name: 'Sign out of app', exact: true }).click();
    await alice.page.goto(recovery);
    await visible(alice.page.getByText('Verification link rejected or expired.'));
    assert.equal(new URL(alice.page.url()).hash, '');
    passed('Browser recovery/password update, old-password denial, new-password login and replay denial');

    stage = 'revoke key and platform logout';
    const row = admin.locator('.control-key').filter({ hasText: key.prefix });
    admin.once('dialog', dialog => dialog.accept());
    await row.getByRole('button', { name: 'Revoke', exact: true }).click();
    await visible(row.getByText(/revoked/));
    await bob.page.getByRole('button', { name: 'Load my tasks', exact: true }).click();
    await visible(bob.page.getByRole('alert'));
    await admin.getByRole('button', { name: 'Sign out', exact: true }).click();
    await visible(admin.getByRole('button', { name: 'Sign in', exact: true }));
    passed('Dashboard key revocation denies app requests; platform logout returns to login');
    assert.equal(errors.length, 0, 'Uncaught browser errors');
    await writeFile('/workspace/docs/evidence/phase3-browser.json', JSON.stringify({ browser: 'Chromium / Playwright 1.63.0', viewports: ['1280x900', '390x844'], checks, uncaught_page_errors: errors.length }, null, 4) + '\n');
} catch (error) {
    console.error('FAIL: browser acceptance at', stage, 'category:', error.name, 'completed checks:', checks.length);
    process.exitCode = 1;
} finally {
    if (key?.id && control && base) await control(base + '/keys/' + key.id, 'DELETE').catch(() => {});
    if (browser) await browser.close();
    for (const server of proxies) server.closeAllConnections();
    for (const server of proxies) await new Promise(resolve => server.close(resolve));
}
