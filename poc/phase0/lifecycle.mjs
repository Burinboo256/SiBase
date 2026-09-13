// Phase 1-only persistence sentinel. Synthetic rows/objects are retained.
import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import pg from 'pg';
import { S3Client, PutObjectCommand, GetObjectCommand } from '@aws-sdk/client-s3';

const state = JSON.parse(await readFile('/state/secrets.json', 'utf8'));
const mode = process.argv[2];
assert(['seed', 'verify'].includes(mode));
const path = '/state/lifecycle-manifest.json';
const manifest = mode === 'seed' ? [] : JSON.parse(await readFile(path, 'utf8'));
for (const [name, config] of Object.entries(state.projects)) {
    const db = new pg.Client({ host: 'db', database: name, user: 'postgres',
        password: state.admin_password, connectionTimeoutMillis: 5000 });
    const s3 = new S3Client({ endpoint: 'http://s3:8333', region: 'us-east-1', forcePathStyle: true,
        credentials: { accessKeyId: config.s3_key, secretAccessKey: config.s3_secret },
        requestChecksumCalculation: 'WHEN_REQUIRED', responseChecksumValidation: 'WHEN_REQUIRED' });
    try {
        await db.connect();
        if (mode === 'seed') {
            const id = randomUUID();
            const title = 'lifecycle-' + id;
            const user = (await db.query('SELECT id FROM auth.users ORDER BY created_at LIMIT 1')).rows[0];
            assert(user, 'Run integration before lifecycle');
            await db.query('INSERT INTO public.tasks(id, owner_id, title) VALUES ($1, $2, $3)', [id, user.id, title]);
            await s3.send(new PutObjectCommand({ Bucket: 'sibase-' + name, Key: title, Body: title }));
            manifest.push({ name, id, title });
        } else {
            const item = manifest.find((entry) => entry.name === name);
            assert(item);
            assert.equal((await db.query('SELECT title FROM tasks WHERE id=$1', [item.id])).rows[0].title, item.title);
            const deadline = Date.now() + 30000;
            let object;
            while (!object) {
                try {
                    object = await s3.send(new GetObjectCommand({ Bucket: 'sibase-' + name, Key: item.title }));
                } catch (error) {
                    if (error.$metadata?.httpStatusCode < 500 || Date.now() >= deadline) throw error;
                    await new Promise((resolve) => setTimeout(resolve, 1000));
                }
            }
            assert.equal(await object.Body.transformToString(), item.title);
        }
    } finally {
        await db.end();
        s3.destroy();
    }
}
if (mode === 'seed') await writeFile(path, JSON.stringify(manifest, null, 4) + '\n', { mode: 0o600 });
console.log('PASS lifecycle ' + mode + ': two database rows and two S3 objects');
