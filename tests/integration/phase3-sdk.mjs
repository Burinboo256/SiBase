import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';

const require = createRequire(new URL('../../poc/phase0/package.json', import.meta.url));
const { createClient } = require('@supabase/supabase-js');
const owner = JSON.parse(await readFile('/workspace/.local/sibase-control/initial-owner.json', 'utf8'));
const origin = 'http://127.0.0.1:58400';
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const clients = [];
const checks = [];
let key, base, control;
let stage = 'platform login';
function passed(name) { checks.push(name); console.log('PASS:', name); }

try {
    const login = await fetch('http://api:8000/api/v2/login', { method: 'POST', headers: { Origin: origin, 'Content-Type': 'application/json' }, body: JSON.stringify(owner) });
    assert.equal(login.status, 200);
    const session = await login.json();
    const headers = { Origin: origin, Cookie: login.headers.getSetCookie().map(c => c.split(';')[0]).join('; '), 'X-CSRF-Token': session.csrf, 'Content-Type': 'application/json' };
    control = (path, method = 'GET', body) => fetch('http://api:8000/api/v2' + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
    const workspaces = await (await control('/workspaces')).json();
    const wid = workspaces.find(w => w.name === 'Internal team').id;
    const projects = await (await control(`/workspaces/${wid}/projects`)).json();
    const project = projects.find(p => p.name === 'Auth Sandbox');
    assert.equal(project.status, 'ready');
    base = `/workspaces/${wid}/projects/${project.id}`;
    const config = await (await control(base + '/auth')).json();
    assert.ok(config.enabled && config.settings.signing_epoch > 1, 'Run Phase 3 signing-rotation test first');
    const issued = await control(base + '/keys', 'POST', { role: 'anon' });
    assert.equal(issued.status, 201);
    key = await issued.json();
    const url = 'http://gateway:8000/p/' + project.ref;
    const run = randomUUID().slice(0, 8);
    for (const name of ['alice', 'bob']) {
        stage = name + ' signup';
        const client = createClient(url, key.key, { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } });
        clients.push(client);
        const email = `sdk-${name}-${run}@example.com`;
        const password = randomUUID() + 'aA1!';
        const signup = await client.auth.signUp({ email, password });
        assert.equal(signup.error, null);
        assert.equal(signup.data.session, null);
        stage = name + ' confirmation email';
        let tokenHash;
        for (let i = 0; i < 30 && !tokenHash; i++) {
            const inbox = await (await fetch('http://mailpit:8025/api/v1/search?query=' + encodeURIComponent('to:' + email))).json();
            for (const item of inbox.messages ?? []) {
                const message = await (await fetch('http://mailpit:8025/api/v1/message/' + item.ID)).json();
                for (const link of (message.Text ?? '').match(/https?:\/\/[^\s<>"\)]+/g) ?? []) {
                    const parsed = new URL(link.replaceAll('&amp;', '&'));
                    if (parsed.pathname === `/p/${project.ref}/auth/v1/verify` && parsed.searchParams.get('type') === 'signup') tokenHash = parsed.searchParams.get('token');
                }
            }
            if (!tokenHash) await delay(1000);
        }
        assert.ok(tokenHash, 'Confirmation email missing');
        stage = name + ' verifyOtp';
        const verified = await client.auth.verifyOtp({ token_hash: tokenHash, type: 'signup' });
        if (verified.error) console.error('Provider verification status:', verified.error.status, 'code:', verified.error.code);
        assert.equal(verified.error, null);
        assert.ok(verified.data.session);
    }
    passed('SDK signup and email verification for two users after signing rotation');
    const [alice, bob] = clients;
    stage = 'owner-row and refresh';
    const inserted = await alice.from('phase3_tasks').insert({ title: 'sdk-' + run }).select().single();
    assert.equal(inserted.error, null);
    const denied = await bob.from('phase3_tasks').select('*').eq('id', inserted.data.id);
    assert.equal(denied.error, null);
    assert.deepEqual(denied.data, []);
    assert.equal((await alice.auth.refreshSession()).error, null);
    assert.equal((await alice.from('phase3_tasks').select('*').eq('id', inserted.data.id)).data.length, 1);
    passed('SDK owner-row isolation and refreshSession');

    let delivered = false;
    stage = 'Realtime';
    const channel = alice.channel('phase3-' + run, { config: { broadcast: { self: true } } })
        .on('broadcast', { event: 'proof' }, event => { delivered = event.payload.value === run; });
    await new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Realtime subscribe timeout')), 20000);
        channel.subscribe(status => {
            if (status === 'SUBSCRIBED') { clearTimeout(timeout); resolve(); }
            if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT') { clearTimeout(timeout); reject(new Error('Realtime subscribe failed')); }
        });
    });
    assert.equal(await channel.send({ type: 'broadcast', event: 'proof', payload: { value: run } }), 'ok');
    for (let i = 0; i < 30 && !delivered; i++) await delay(100);
    assert.ok(delivered, 'Realtime message missing after signing rotation');
    await alice.removeChannel(channel);
    passed('Authenticated SDK Realtime subscribe and broadcast after signing rotation');
    assert.equal((await alice.auth.signOut()).error, null);
    assert.equal((await bob.auth.signOut()).error, null);
    assert.equal((await alice.auth.getSession()).data.session, null);
    passed('SDK signOut clears app sessions');
    await writeFile('/workspace/docs/evidence/phase3-sdk.json', JSON.stringify({ sdk: '2.116.0', checks }, null, 4) + '\n');
} catch (error) {
    console.error('FAIL: Phase 3 SDK contract', stage, error.name, checks.length, 'checks passed');
    process.exitCode = 1;
} finally {
    for (const client of clients) await client.removeAllChannels();
    if (key?.id && control && base) await control(base + '/keys/' + key.id, 'DELETE');
}
process.exit(process.exitCode ?? 0);
