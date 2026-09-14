import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
const require = createRequire(new URL('../../poc/phase0/package.json', import.meta.url));
const { createClient } = require('@supabase/supabase-js');
const state = JSON.parse(await readFile('/workspace/.local/sibase-control/sdk-fixture.json', 'utf8'));
const owner = JSON.parse(await readFile('/workspace/.local/sibase-control/initial-owner.json', 'utf8'));
const origin = 'http://127.0.0.1:58400';
const checks = [];
const clients = [];
const run = randomUUID().slice(0, 8);
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function passed(name) { checks.push(name); console.log('PASS:', name); }
function client(project, key) {
    const result = createClient('http://gateway:8000/p/' + project.ref, key, { auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false } });
    clients.push(result);
    return result;
}

try {
    for (const project of state.projects) {
        const anon = client(project, project.anon_key);
        const server = client(project, project.service_key);
        const { data, error } = await anon.from('phase2_probe').select('*');
        assert.equal(error, null);
        assert.equal(data[0].marker, project.ref);
        const signup = await anon.auth.signUp({ email: `phase2-${run}@example.com`, password: randomUUID() + 'aA1!' });
        assert.equal(signup.error, null);
        assert.ok(signup.data.session?.access_token);
        passed(project.name + ': SDK REST and app Auth signup');
        const other = state.projects.find(p => p.ref !== project.ref);
        const wrong = await fetch('http://gateway:8000/p/' + other.ref + '/rest/v1/phase2_probe', { headers: { apikey: other.anon_key, Authorization: 'Bearer ' + signup.data.session.access_token } });
        assert.equal(wrong.status, 401);
        passed(project.name + ': app JWT rejected by another project');

        const bucket = 'phase2-' + run;
        assert.equal((await server.storage.createBucket(bucket, { public: false })).error, null);
        assert.equal((await server.storage.from(bucket).upload('proof.txt', 'retained phase2 proof', { contentType: 'text/plain' })).error, null);
        const download = await server.storage.from(bucket).download('proof.txt');
        assert.equal(download.error, null);
        assert.equal(await download.data.text(), 'retained phase2 proof');
        const signed = await server.storage.from(bucket).createSignedUrl('proof.txt', 60);
        assert.equal(signed.error, null);
        const object = await fetch(signed.data.signedUrl);
        assert.equal(object.status, 200);
        assert.equal(await object.text(), 'retained phase2 proof');
        passed(project.name + ': SDK private Storage upload/download and signed URL');

        const realtime = client(project, project.anon_key);
        let delivered = false;
        let closed = false;
        const channel = realtime.channel('phase2-' + run, { config: { broadcast: { self: true } } })
            .on('broadcast', { event: 'proof' }, event => { delivered = event.payload.value === run; });
        await new Promise((resolve, reject) => {
            const timeout = setTimeout(() => reject(new Error('Realtime subscribe timeout')), 20000);
            channel.subscribe(status => {
                if (status === 'SUBSCRIBED') { clearTimeout(timeout); resolve(); }
                if (status === 'CLOSED' || status === 'CHANNEL_ERROR') closed = true;
            });
        });
        assert.equal(await channel.send({ type: 'broadcast', event: 'proof', payload: { value: run } }), 'ok');
        for (let i = 0; i < 30 && !delivered; i++) await delay(100);
        assert.ok(delivered, 'Realtime message not delivered');
        passed(project.name + ': SDK anonymous Realtime subscribe and broadcast');

        const login = await fetch('http://api:8000/api/v2/login', { method: 'POST', headers: { 'Content-Type': 'application/json', Origin: origin }, body: JSON.stringify(owner) });
        assert.equal(login.status, 200);
        const session = await login.json();
        const cookie = login.headers.getSetCookie().map(c => c.split(';')[0]).join('; ');
        const revoke = await fetch(`http://api:8000/api/v2/workspaces/${state.workspace_id}/projects/${project.id}/keys/${project.key_id}`, { method: 'DELETE', headers: { Origin: origin, Cookie: cookie, 'X-CSRF-Token': session.csrf } });
        assert.equal(revoke.status, 200);
        for (let i = 0; i < 60 && !closed; i++) await delay(100);
        assert.ok(closed, 'Revoked key did not close the existing Realtime connection');
        assert.equal((await fetch('http://gateway:8000/p/' + project.ref + '/rest/v1/', { headers: { apikey: project.anon_key } })).status, 401);
        await realtime.removeChannel(channel);
        await anon.auth.signOut();
        passed(project.name + ': revoke closes existing Realtime connection and denies HTTP');
    }
    await writeFile('/workspace/docs/evidence/phase2-sdk.json', JSON.stringify({ sdk: '2.116.0', checks }, null, 4) + '\n');
} catch (error) {
    // SDK errors may carry request credentials. Emit only our assertion category.
    console.error('FAIL: SDK contract test', error.name, checks.length, 'checks passed');
    process.exitCode = 1;
} finally {
    for (const c of clients) await c.removeAllChannels();
}
