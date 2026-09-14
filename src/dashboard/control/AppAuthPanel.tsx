import { useEffect, useState } from 'react';
import { api } from './api';

type AuthState = {
    enabled: boolean;
    settings: { jwt_exp: number; site_url: string; signing_epoch: number } | null;
    snapshot: {
        collected: number;
        error: string | null;
        users?: {
            id: string;
            email: string;
            email_confirmed_at: string | null;
            last_sign_in_at: string | null;
        }[];
        sessions?: { id: string; user_id: string; created_at: string; not_after: string | null }[];
        tables?: { name: string; rls: boolean; force_rls: boolean }[];
        policies?: {
            tablename: string;
            policyname: string;
            cmd: string;
            qual: string;
            with_check: string;
        }[];
        roles?: { name: string; superuser: boolean; bypass_rls: boolean }[];
    } | null;
};

export default function AppAuthPanel({ base }: { base: string }) {
    const [data, setData] = useState<AuthState | null>(null);
    const [view, setView] = useState('Users');
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState('');
    const [revision, setRevision] = useState(0);
    useEffect(() => {
        let active = true;
        let timer: ReturnType<typeof setTimeout>;
        async function load() {
            try {
                const result = await api<AuthState>(base + '/auth');
                if (active) setData(result);
            } catch (e) {
                if (active) setError((e as Error).message);
            }
            if (active) timer = setTimeout(load, 10000);
        }
        void load();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [base, revision]);

    return (
        <section className="control-card" aria-label="Application authentication">
            <div className="control-section-title">
                <h2>Application authentication</h2>
                <span className="control-role">PHASE 3</span>
            </div>
            <p>
                Application users are separate from workspace members. Passwords and tokens are
                never shown here.
            </p>
            {error && (
                <p role="alert" className="control-error">
                    {error}
                </p>
            )}
            {notice && <p role="status">{notice}</p>}
            {!data ? (
                <p>Loading authentication settings…</p>
            ) : (
                <>
                    {!data.enabled && (
                        <p>
                            Not enabled for this project. Enabling requires email verification and
                            forces RLS on public tables. Existing policies and data are retained;
                            tables without policies become inaccessible to application users.
                        </p>
                    )}
                    <div className="control-actions">
                        {['Users', 'Sessions', 'Auth Settings', 'Permission preview'].map((tab) => (
                            <button
                                key={tab}
                                aria-pressed={view === tab}
                                onClick={() => setView(tab)}
                            >
                                {tab}
                            </button>
                        ))}
                    </div>
                    {data.snapshot?.error && (
                        <p role="alert">
                            Live metadata unavailable. The worker will retry; no stale snapshot is
                            presented as current.
                        </p>
                    )}
                    {data.snapshot && (
                        <small>
                            Snapshot: {new Date(data.snapshot.collected * 1000).toLocaleString()} ·
                            up to 100 records per category · polls every 10 seconds; collection may
                            wait while provisioning jobs run
                        </small>
                    )}
                    {data.snapshot && Date.now() / 1000 - data.snapshot.collected > 30 && (
                        <p role="status">
                            Snapshot is older than 30 seconds. Check its collection time before
                            relying on these results.
                        </p>
                    )}
                    {view === 'Users' && (
                        <div>
                            <h3>Application users</h3>
                            {!data.snapshot?.users?.length && (
                                <p>No users in the current snapshot.</p>
                            )}
                            {data.snapshot?.users?.map((user) => (
                                <div className="control-member" key={user.id}>
                                    <span>{user.email}</span>
                                    <span>
                                        {user.email_confirmed_at
                                            ? 'Confirmed'
                                            : 'Awaiting confirmation'}
                                    </span>
                                    <code>{user.id}</code>
                                </div>
                            ))}
                        </div>
                    )}
                    {view === 'Sessions' && (
                        <div>
                            <h3>Application sessions</h3>
                            <p>
                                Read-only provider session metadata. Refresh tokens are not exposed.
                                Users sign out through their app; access JWTs remain valid until
                                expiry.
                            </p>
                            {!data.snapshot?.sessions?.length && (
                                <p>No sessions in the current snapshot.</p>
                            )}
                            {data.snapshot?.sessions?.map((session) => (
                                <div className="control-event" key={session.id}>
                                    <code>{session.id}</code>
                                    <span>User: {session.user_id}</span>
                                    <time>{session.created_at}</time>
                                </div>
                            ))}
                        </div>
                    )}
                    {view === 'Auth Settings' && (
                        <div>
                            <h3>Email and session settings</h3>
                            <p>
                                Email confirmation is required. Refresh rotation is enabled with a
                                zero-second grace window; the provider may still accept the
                                immediate parent token as a retry.
                            </p>
                            <form
                                key={data.settings?.jwt_exp + ':' + data.settings?.site_url}
                                onSubmit={(event) => {
                                    event.preventDefault();
                                    const form = new FormData(event.currentTarget);
                                    if (
                                        !window.confirm(
                                            'Apply Auth settings and enforce RLS? Tables without policies will deny application access. Services briefly restart; data is retained.',
                                        )
                                    )
                                        return;
                                    setBusy(true);
                                    setError('');
                                    setNotice('');
                                    void api(base + '/auth', 'PUT', {
                                        jwt_exp: Number(form.get('jwt_exp')),
                                        site_url: form.get('site_url'),
                                    })
                                        .then(() => {
                                            setNotice(
                                                'Settings queued. Wait for the project to return to ready.',
                                            );
                                            setRevision((r) => r + 1);
                                        })
                                        .catch((e) => setError(e.message))
                                        .finally(() => setBusy(false));
                                }}
                            >
                                <label>
                                    Access token lifetime (seconds)
                                    <input
                                        name="jwt_exp"
                                        type="number"
                                        min={300}
                                        max={3600}
                                        defaultValue={data.settings?.jwt_exp ?? 900}
                                        required
                                    />
                                </label>
                                <label>
                                    Application callback URL
                                    <input
                                        name="site_url"
                                        type="url"
                                        defaultValue={
                                            data.settings?.site_url ??
                                            'http://127.0.0.1:58400/auth/callback'
                                        }
                                        required
                                    />
                                </label>
                                <button className="control-primary" disabled={busy}>
                                    {data.enabled
                                        ? 'Apply Auth settings'
                                        : 'Enable verified Auth and RLS'}
                                </button>
                            </form>
                            <p>
                                Local test inbox:{' '}
                                <a href="http://127.0.0.1:58425" target="_blank" rel="noreferrer">
                                    Mailpit
                                </a>
                                . Email links are sensitive; keep this port private. SMTP
                                credentials are operator-managed, never editable in the browser.
                            </p>
                            {data.enabled && (
                                <>
                                    <h3>Signing key rotation</h3>
                                    <p>
                                        Current generation: {data.settings?.signing_epoch}. Rotation
                                        invalidates existing access JWTs and restarts services.
                                        Opaque API keys remain unchanged; refresh sessions are not
                                        revoked.
                                    </p>
                                    <button
                                        disabled={busy}
                                        onClick={() => {
                                            if (
                                                !window.confirm(
                                                    'Rotate the project signing key? Existing access JWTs stop working and services restart. This does not sign out refresh sessions.',
                                                )
                                            )
                                                return;
                                            setBusy(true);
                                            setError('');
                                            void api(base + '/auth/rotate-signing-key', 'POST')
                                                .then(() => {
                                                    setNotice(
                                                        'Signing rotation queued. Wait for ready before reconnecting.',
                                                    );
                                                    setRevision((r) => r + 1);
                                                })
                                                .catch((e) => setError(e.message))
                                                .finally(() => setBusy(false));
                                        }}
                                    >
                                        Rotate project signing key
                                    </button>
                                </>
                            )}
                        </div>
                    )}
                    {view === 'Permission preview' && (
                        <div>
                            <h3>Database policy inventory</h3>
                            <p>
                                This shows installed policies, not a guarantee for arbitrary
                                queries. The <code>phase3_tasks</code> template permits
                                authenticated users to CRUD their own rows only; server keys
                                deliberately bypass RLS.
                            </p>
                            {data.snapshot?.tables?.map((table) => (
                                <div className="control-member" key={table.name}>
                                    <code>{table.name}</code>
                                    <span>
                                        {table.rls && table.force_rls
                                            ? 'RLS enabled + forced'
                                            : 'Attention: RLS not forced'}
                                    </span>
                                </div>
                            ))}
                            {data.snapshot?.policies?.map((policy) => (
                                <div
                                    className="control-event"
                                    key={policy.tablename + policy.policyname}
                                >
                                    <strong>
                                        {policy.tablename}.{policy.policyname}
                                    </strong>
                                    <span>{policy.cmd}</span>
                                    <code>
                                        USING: {policy.qual ?? 'none'} / CHECK:{' '}
                                        {policy.with_check ?? 'none'}
                                    </code>
                                </div>
                            ))}
                            {data.snapshot?.roles?.map((role) => (
                                <div className="control-member" key={role.name}>
                                    <code>{role.name}</code>
                                    <span>
                                        {role.bypass_rls
                                            ? 'Privileged server role'
                                            : 'Subject to RLS'}
                                        {role.superuser ? ' / SUPERUSER' : ''}
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}
                </>
            )}
        </section>
    );
}
