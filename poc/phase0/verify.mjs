import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { createClient } from '@supabase/supabase-js';
import pg from 'pg';
import { S3Client, CreateBucketCommand, PutObjectCommand, GetObjectCommand } from '@aws-sdk/client-s3';

const state = JSON.parse(await readFile('/state/secrets.json', 'utf8'));
const report = { started_at: new Date().toISOString(), runtime_label: process.env.POC_RUN_LABEL || 'default', topology: 'two databases / one PostgreSQL cluster', checks: [] };
const clients = [];
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const run = randomUUID().slice(0, 8);

async function check(name, fn) {
    const start = Date.now();
    try {
        await fn();
        report.checks.push({ name, status: 'passed', duration_ms: Date.now() - start });
        console.log(`PASS ${name}`);
    } catch (error) {
        report.checks.push({ name, status: 'failed', error: String(error.message).slice(0, 600) });
        throw error;
    }
}

async function until(fn, description, timeout = 180000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
        try { if (await fn()) return; } catch { /* Service/migrations may still be starting. */ }
        await delay(1000);
    }
    throw new Error(`Timed out waiting for ${description}`);
}

async function sql(database, query, params = [], user = 'postgres', password = state.admin_password, host = 'db') {
    const db = new pg.Client({ host, port: 5432, database, user, password, connectionTimeoutMillis: 3000 });
    try { await db.connect(); return await db.query(query, params); } finally { await db.end(); }
}

function sdk(name, key = state.projects[name].anon_key) {
    const c = createClient(`http://gateway:${name === 'alpha' ? 8001 : 8002}`, key, {
        auth: { persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
    });
    clients.push(c);
    return c;
}

function ok(result) {
    assert.equal(result.error, null, result.error?.message);
    return result.data;
}

function s3(credentials) {
    return new S3Client({ endpoint: 'http://s3:8333', region: 'us-east-1', forcePathStyle: true, credentials,
        requestChecksumCalculation: 'WHEN_REQUIRED', responseChecksumValidation: 'WHEN_REQUIRED' });
}

async function main() {
    await check('All project services complete migrations', async () => {
        for (const [name, config] of Object.entries(state.projects)) {
            await until(async () => {
                const responses = await Promise.all([
                    fetch(`http://auth-${name}:9999/health`), fetch(`http://storage-${name}:5000/status`),
                    fetch(`http://realtime-${name}:4000/api/tenants/realtime-${name}/health`, { headers: { Authorization: `Bearer ${config.anon_key}` } }),
                ]);
                const migrations = await sql(name, 'SELECT max(version)::text AS version FROM realtime.schema_migrations');
                return responses.every((r) => r.ok) && migrations.rows[0].version === '20260714120000';
            }, `${name} service readiness`);
        }
    });
    await check('Initialize two application schemas with owner RLS', async () => {
        for (const name of Object.keys(state.projects)) {
            await sql(name, `
                CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql STABLE AS $$
                    SELECT COALESCE(NULLIF(current_setting('request.jwt.claim.sub', true), ''),
                        NULLIF(current_setting('request.jwt.claims', true), '')::jsonb->>'sub')::uuid;
                $$;
                ALTER FUNCTION auth.uid() OWNER TO ${name}_auth;
                CREATE TABLE IF NOT EXISTS public.tasks (
                    id uuid PRIMARY KEY DEFAULT gen_random_uuid(), owner_id uuid NOT NULL REFERENCES auth.users(id),
                    title text NOT NULL, deleted_at timestamptz
                );
                ALTER TABLE public.tasks OWNER TO ${name}_owner;
                ALTER TABLE public.tasks ENABLE ROW LEVEL SECURITY;
                GRANT SELECT, INSERT, UPDATE, DELETE ON public.tasks TO authenticated;
                GRANT ALL ON public.tasks TO service_role;
                DROP POLICY IF EXISTS task_owner ON public.tasks;
                CREATE POLICY task_owner ON public.tasks TO authenticated USING (owner_id = auth.uid()) WITH CHECK (owner_id = auth.uid());
                DO $$ BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_publication_tables WHERE pubname = 'supabase_realtime' AND tablename = 'tasks') THEN
                        ALTER PUBLICATION supabase_realtime ADD TABLE public.tasks;
                    END IF;
                END $$;
                DROP POLICY IF EXISTS own_files ON storage.objects;
                CREATE POLICY own_files ON storage.objects TO authenticated
                    USING (bucket_id = 'private-files' AND (storage.foldername(name))[1] = auth.uid()::text)
                    WITH CHECK (bucket_id = 'private-files' AND (storage.foldername(name))[1] = auth.uid()::text);
                NOTIFY pgrst, 'reload schema';
            `);
        }
        await delay(1500);
    });
    await check('Create S3 buckets and deny cross-project S3 credentials', async () => {
        const admin = s3({ accessKeyId: 'poc-admin', secretAccessKey: state.s3_admin });
        await until(async () => {
            for (const name of Object.keys(state.projects)) {
                try { await admin.send(new CreateBucketCommand({ Bucket: `sibase-${name}` })); }
                catch (e) { if (!['BucketAlreadyExists', 'BucketAlreadyOwnedByYou'].includes(e.name)) throw e; }
            }
            return true;
        }, 'S3 buckets');
        for (const [name, config] of Object.entries(state.projects)) {
            const client = s3({ accessKeyId: config.s3_key, secretAccessKey: config.s3_secret });
            await client.send(new PutObjectCommand({ Bucket: `sibase-${name}`, Key: `probe-${run}`, Body: name }));
            client.destroy();
        }
        for (const [name, config] of Object.entries(state.projects)) {
            const client = s3({ accessKeyId: config.s3_key, secretAccessKey: config.s3_secret });
            await assert.rejects(client.send(new GetObjectCommand({ Bucket: `sibase-${name === 'alpha' ? 'beta' : 'alpha'}`, Key: `probe-${run}` })),
                (e) => e.$metadata?.httpStatusCode === 403);
            client.destroy();
        }
        admin.destroy();
    });
    await check('Every project DB credential cannot connect to other project/platform', async () => {
        for (const [name, config] of Object.entries(state.projects)) {
            for (const role of Object.keys(config.passwords ?? { auth: 0, rest: 0, storage: 0, realtime: 0, owner: 0 })) {
                await sql(name, 'select current_database()', [], `${name}_${role}`, config.passwords?.[role] ?? config.password);
                for (const target of [name === 'alpha' ? 'beta' : 'alpha', 'postgres']) {
                    await assert.rejects(sql(target, 'select 1', [], `${name}_${role}`, config.passwords?.[role] ?? config.password), (e) => e.code === '42501');
                }
            }
        }
    });
    await check('REST/owner roles cannot elevate to project service or cluster admin roles', async () => {
        for (const [name, config] of Object.entries(state.projects)) {
            const roles = await sql(name, 'select rolname, rolsuper, rolcreaterole, rolcreatedb from pg_roles where rolname like $1', [`${name}_%`]);
            assert(roles.rows.every((r) => !r.rolsuper && !r.rolcreaterole && !r.rolcreatedb));
            for (const role of ['rest', 'owner']) {
                for (const target of ['postgres', `${name === 'alpha' ? 'beta' : 'alpha'}_owner`, `${name}_storage`]) {
                    await assert.rejects(sql(name, `SET ROLE ${target}`, [], `${name}_${role}`, config.passwords?.[role] ?? config.password), (e) => e.code === '42501');
                }
            }
        }
    });
    if (Object.values(state.projects).every((p) => p.passwords)) {
        await check('Phase 1: platform reader is read-only and project logins cannot enter platform DB', async () => {
            const platform = JSON.parse(await readFile('/state/platform-secrets.json', 'utf8'));
            const reader = (query) => sql('platform', query, [], 'platform_reader', platform.reader, 'platform-db');
            assert.equal((await reader('SELECT name FROM installation WHERE id = 1')).rows[0].name, 'SiBase local development');
            assert.equal((await reader('SELECT version_num FROM alembic_version')).rows[0].version_num, '0001');
            for (const query of [
                "INSERT INTO installation VALUES (2, 'forbidden')",
                'CREATE TABLE public.forbidden (id int)',
                'SET ROLE platform_owner',
            ]) await assert.rejects(reader(query), (e) => e.code === '42501');
            await assert.rejects(sql('platform', 'SELECT 1', [], 'platform_owner', platform.reader, 'platform-db'), (e) => e.code === '28P01');
            for (const [name, config] of Object.entries(state.projects)) {
                await assert.rejects(sql(name, 'SELECT 1', [], 'platform_reader', platform.reader), (e) => e.code === '28P01');
                for (const [role, password] of Object.entries(config.passwords)) {
                    await assert.rejects(
                        sql('platform', 'SELECT 1', [], `${name}_${role}`, password, 'platform-db'),
                        (e) => e.code === '28P01',
                    );
                }
            }
        });
        await check('Phase 1: passwords cannot impersonate any other project role', async () => {
            const passwords = Object.values(state.projects).flatMap((p) => Object.values(p.passwords));
            assert.equal(new Set(passwords).size, passwords.length);
            for (const [name, config] of Object.entries(state.projects)) {
                for (const [source, password] of Object.entries(config.passwords)) {
                    for (const target of Object.keys(config.passwords)) {
                        if (source !== target) {
                            await assert.rejects(
                                sql(name, 'select 1', [], `${name}_${target}`, password),
                                (e) => e.code === '28P01',
                            );
                        }
                    }
                }
            }
        });
    }
    const users = {};
    for (const name of Object.keys(state.projects)) {
        users[name] = [];
        await check(`${name}: real Auth signup/password login/refresh`, async () => {
            for (let i = 0; i < 2; i++) {
                const client = sdk(name);
                const email = `poc-${run}-${i}@example.com`;
                const password = `Poc-${randomUUID()}!`;
                const signedUp = ok(await client.auth.signUp({ email, password }));
                assert(signedUp.user.id);
                const signedIn = ok(await client.auth.signInWithPassword({ email, password }));
                assert(signedIn.session.access_token);
                const refreshed = ok(await client.auth.refreshSession());
                users[name].push({ client, id: refreshed.user.id, token: refreshed.session.access_token });
            }
            assert.notEqual(users[name][0].id, users[name][1].id);
        });
        await check(`${name}: REST access with same-project RLS and owner-spoof denial`, async () => {
            const [a, b] = users[name];
            const rows = ok(await a.client.from('tasks').insert({ owner_id: a.id, title: `private-${run}` }).select());
            a.task = rows[0];
            assert.equal(ok(await a.client.from('tasks').select('*').eq('id', a.task.id)).length, 1);
            assert.deepEqual(ok(await b.client.from('tasks').select('*').eq('id', a.task.id)), []);
            assert.deepEqual(ok(await b.client.from('tasks').update({ title: 'stolen' }).eq('id', a.task.id).select()), []);
            assert((await b.client.from('tasks').insert({ owner_id: a.id, title: 'spoof' })).error);
            assert((await a.client.from('tasks').update({ owner_id: b.id }).eq('id', a.task.id)).error);
            const anonymous = sdk(name);
            assert((await anonymous.from('tasks').select('*')).error);
            const privateSchema = await fetch(`http://rest-${name}:3000/users`, { headers: { Authorization: `Bearer ${a.token}`, 'Accept-Profile': 'auth' } });
            assert.equal(privateSchema.status, 406);
        });
        await check(`${name}: private upload/download/sign and same-project file denial`, async () => {
            const admin = sdk(name, state.projects[name].service_key);
            const exists = await admin.storage.getBucket('private-files');
            if (exists.error) ok(await admin.storage.createBucket('private-files', { public: false, fileSizeLimit: 10485760 }));
            const [a, b] = users[name];
            const path = `${a.id}/${run}.txt`;
            const bytes = new TextEncoder().encode(`private ${name} ${run}`);
            ok(await a.client.storage.from('private-files').upload(path, bytes, { contentType: 'text/plain' }));
            assert.equal(await ok(await a.client.storage.from('private-files').download(path)).text(), `private ${name} ${run}`);
            assert((await b.client.storage.from('private-files').download(path)).error);
            assert((await b.client.storage.from('private-files').upload(`${a.id}/spoof-${run}.txt`, bytes)).error);
            const signed = ok(await a.client.storage.from('private-files').createSignedUrl(path, 2));
            const valid = await fetch(signed.signedUrl);
            assert.equal(valid.status, 200);
            await delay(3100);
            const expired = await fetch(signed.signedUrl);
            assert(expired.status >= 400);
            a.file = path;
        });
    }
    await check('JWT and API-key isolation both directions across REST/Auth/Storage', async () => {
        for (const name of ['alpha', 'beta']) {
            const other = name === 'alpha' ? 'beta' : 'alpha';
            const token = users[name][0].token;
            const port = other === 'alpha' ? 8001 : 8002;
            for (const path of ['/rest/v1/tasks', '/auth/v1/user', `/storage/v1/object/authenticated/private-files/${users[other][0].file}`]) {
                const validKeyWrongJWT = await fetch(`http://gateway:${port}${path}`, { headers: { apikey: state.projects[other].anon_key, Authorization: `Bearer ${token}` } });
                assert([400, 401, 403].includes(validKeyWrongJWT.status), `${other} ${path}: ${validKeyWrongJWT.status}`);
                const wrongKey = await fetch(`http://gateway:${port}${path}`, { headers: { apikey: state.projects[name].anon_key, Authorization: `Bearer ${users[other][0].token}` } });
                assert.equal(wrongKey.status, 401);
            }
        }
    });
    let subscriptionsReady = 0;
    let releaseBoth;
    const bothReady = new Promise((resolve) => { releaseBoth = resolve; });
    const realtimeResults = await Promise.allSettled(['alpha', 'beta'].map(async (name) => {
        await check(`${name}: Realtime delivers REST and SQL updates only to owner`, async () => {
            const [a, b] = users[name];
            const receivedA = [], receivedB = [];
            const channelA = a.client.channel(`${run}-owner`).on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'tasks' }, (p) => receivedA.push(p));
            const channelB = b.client.channel(`${run}-other`).on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'tasks' }, (p) => receivedB.push(p));
            const ready = [false, false];
            for (const [index, channel] of [channelA, channelB].entries()) {
                channel.on('system', {}, (payload) => {
                    if (payload.status === 'ok') ready[index] = true;
                    if (payload.status === 'error') console.log(`Realtime system ${name}: ${payload.message}`);
                });
            }
            await Promise.all([channelA, channelB].map((channel) => new Promise((resolve, reject) => {
                const timeout = setTimeout(() => reject(new Error('Realtime subscribe timeout')), 30000);
                channel.subscribe((status, error) => {
                    if (status === 'SUBSCRIBED') { clearTimeout(timeout); resolve(); }
                    if (['CHANNEL_ERROR', 'TIMED_OUT'].includes(status)) { clearTimeout(timeout); reject(new Error(`Realtime ${status}: ${error?.message || ''}`)); }
                });
            })));
            await until(() => ready.every(Boolean), `${name} Postgres Changes readiness`, 30000);
            if (++subscriptionsReady === 2) releaseBoth();
            let barrierTimeout;
            try {
                await Promise.race([bothReady, new Promise((_, reject) => { barrierTimeout = setTimeout(() => reject(new Error('Concurrent project barrier timed out')), 30000); })]);
            } finally { clearTimeout(barrierTimeout); }
            const slots = await sql(name, 'SELECT slot_name, database, active FROM pg_replication_slots ORDER BY slot_name');
            assert(['alpha', 'beta'].every((project) => slots.rows.some((s) => s.database === project && s.active && s.slot_name === `supabase_realtime_replication_slot_${project}`)));
            report.replication_slots = slots.rows;
            ok(await a.client.from('tasks').update({ title: `via-rest-${run}` }).eq('id', a.task.id));
            await until(() => receivedA.some((p) => p.new.title === `via-rest-${run}`), 'REST realtime event', 10000);
            await sql(name, 'UPDATE public.tasks SET title = $1 WHERE id = $2', [`via-sql-${run}`, a.task.id]);
            await until(() => receivedA.some((p) => p.new.title === `via-sql-${run}`), 'SQL realtime event', 10000);
            await delay(1200);
            assert.equal(receivedB.length, 0, 'Other user received private event');
            await Promise.all([a.client.removeChannel(channelA), b.client.removeChannel(channelB)]);
        });
        await check(`${name}: Realtime rejects token from the other project`, async () => {
            const other = name === 'alpha' ? 'beta' : 'alpha';
            const client = sdk(name);
            await client.realtime.setAuth(users[other][0].token);
            const channel = client.channel(`${run}-cross`).on('postgres_changes', { event: '*', schema: 'public', table: 'tasks' }, () => assert.fail('Cross-project event leak'));
            await new Promise((resolve, reject) => {
                const timeout = setTimeout(() => reject(new Error('No explicit cross-project rejection')), 15000);
                channel.subscribe((status) => {
                    if (status === 'CHANNEL_ERROR') { clearTimeout(timeout); resolve(); }
                    if (status === 'SUBSCRIBED') { clearTimeout(timeout); reject(new Error('Cross-project token subscribed')); }
                });
            });
            await client.removeChannel(channel);
        });
    }));
    const realtimeFailure = realtimeResults.find((result) => result.status === 'rejected');
    if (realtimeFailure) throw realtimeFailure.reason;
    await check('SDK logout completes for all four end users', async () => {
        for (const group of Object.values(users)) for (const user of group) ok(await user.client.auth.signOut());
    });
}

try {
    await main();
    report.status = 'passed';
} catch (error) {
    report.status = 'failed';
    console.error(`FAIL ${error.message}`);
    process.exitCode = 1;
} finally {
    for (const client of clients) { await client.removeAllChannels(); client.realtime.disconnect(); }
    report.finished_at = new Date().toISOString();
    await writeFile('/state/test-report.json', JSON.stringify(report, null, 4) + '\n', { mode: 0o600 });
    await writeFile(`/state/test-report-${run}.json`, JSON.stringify(report, null, 4) + '\n', { mode: 0o600 });
    console.log(`${report.checks.filter((c) => c.status === 'passed').length}/${report.checks.length} checks passed; report: test-report.json in the selected runtime directory`);
}
