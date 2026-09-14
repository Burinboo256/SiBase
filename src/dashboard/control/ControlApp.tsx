import { useCallback, useEffect, useState } from 'react';
import {
    api,
    setCsrf,
    type Workspace,
    type Project,
    type Member,
    type Key,
    type Event,
} from './api';
import './control.css';
import AppAuthPanel from './AppAuthPanel';

export default function ControlApp() {
    const [email, setEmail] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);
    const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
    const [wid, setWid] = useState('');
    const [tab, setTab] = useState('Projects');
    const [projects, setProjects] = useState<Project[]>([]);
    const [selected, setSelected] = useState('');
    const [members, setMembers] = useState<Member[]>([]);
    const [events, setEvents] = useState<Event[]>([]);
    const [keys, setKeys] = useState<Key[]>([]);
    const [revealed, setRevealed] = useState('');
    const workspace = workspaces.find((w) => w.id === wid);
    const project = projects.find((p) => p.id === selected);
    const manage = ['owner', 'admin'].includes(workspace?.role ?? '');
    const base = '/workspaces/' + wid;

    useEffect(() => {
        const signout = () => {
            setEmail(null);
            setCsrf('');
            setRevealed('');
            setProjects([]);
            setKeys([]);
            setMembers([]);
            setEvents([]);
            setWorkspaces([]);
        };
        window.addEventListener('sibase-signout', signout);
        api<{ email: string; csrf: string }>('/me')
            .then((result) => {
                setCsrf(result.csrf);
                setEmail(result.email);
            })
            .catch(() => {})
            .finally(() => setLoading(false));
        return () => window.removeEventListener('sibase-signout', signout);
    }, []);

    const refreshWorkspaces = useCallback(async () => {
        const result = await api<Workspace[]>('/workspaces');
        setWorkspaces(result);
        setWid((current) =>
            result.some((w) => w.id === current) ? current : (result[0]?.id ?? ''),
        );
    }, []);
    useEffect(() => {
        if (email) void refreshWorkspaces().catch((e) => setError(String(e.message)));
    }, [email, refreshWorkspaces]);

    const refresh = useCallback(async () => {
        if (!wid) return;
        const [p, m, a] = await Promise.all([
            api<Project[]>(base + '/projects'),
            api<Member[]>(base + '/members'),
            api<Event[]>(base + '/audit'),
        ]);
        setProjects(p);
        setMembers(m);
        setEvents(a);
    }, [wid, base]);
    useEffect(() => {
        if (!email || !wid) return;
        let active = true;
        let timer: ReturnType<typeof setTimeout>;
        const poll = async () => {
            try {
                if (active) await refresh();
            } catch (e) {
                if (active) setError((e as Error).message);
            }
            if (active) timer = setTimeout(poll, 3000);
        };
        void poll();
        return () => {
            active = false;
            clearTimeout(timer);
        };
    }, [email, wid, refresh]);
    useEffect(() => {
        let active = true;
        setKeys([]);
        setRevealed('');
        if (selected && manage)
            void api<Key[]>(base + '/projects/' + selected + '/keys')
                .then((k) => {
                    if (active) setKeys(k);
                })
                .catch((e) => {
                    if (active) setError(e.message);
                });
        return () => {
            active = false;
        };
    }, [selected, base, manage]);

    async function act(task: () => Promise<void>) {
        setBusy(true);
        setError('');
        try {
            await task();
        } catch (e) {
            setError((e as Error).message);
        } finally {
            setBusy(false);
        }
    }
    async function lifecycle(action: string) {
        if (
            !project ||
            !window.confirm(
                `${action}: ${project.name}? Data is retained; deletion has a 7-day restore window.`,
            )
        )
            return;
        await act(async () => {
            await api(base + '/projects/' + project.id + '/lifecycle', 'POST', { action });
            await refresh();
        });
    }
    async function changeKey(action: string, id?: string, role = 'anon') {
        if (!project) return;
        await act(async () => {
            const path = base + '/projects/' + project.id + '/keys';
            if (action === 'revoke') {
                if (
                    !window.confirm(
                        'Revoke this key? Applications using it will lose access immediately.',
                    )
                )
                    return;
                await api(path + '/' + id, 'DELETE');
                setRevealed('');
            } else {
                if (
                    action === 'rotate' &&
                    !window.confirm('Rotate this key? The previous key stops working immediately.')
                )
                    return;
                const result = await api<{ key: string }>(
                    path + (id ? '/' + id + '/rotate' : ''),
                    'POST',
                    { role },
                );
                setRevealed(result.key);
            }
            setKeys(await api<Key[]>(path));
            await refresh();
        });
    }

    if (loading)
        return (
            <main className="control-app">
                <p role="status">Connecting to SiBase…</p>
            </main>
        );
    if (!email)
        return (
            <main className="control-app control-login">
                <section className="control-card">
                    <div className="control-eyebrow">SiBase / CONTROL PLANE</div>
                    <h1>
                        Your team’s backend,
                        <br />
                        in one place.
                    </h1>
                    <p>
                        Sign in with your platform account. Application-user accounts are separate.
                    </p>
                    {error && (
                        <p role="alert" className="control-error">
                            {error}
                        </p>
                    )}
                    <form
                        onSubmit={(e) => {
                            e.preventDefault();
                            const data = new FormData(e.currentTarget);
                            void act(async () => {
                                const result = await api<{ email: string; csrf: string }>(
                                    '/login',
                                    'POST',
                                    { email: data.get('email'), password: data.get('password') },
                                );
                                setCsrf(result.csrf);
                                setEmail(result.email);
                            });
                        }}
                    >
                        <label>
                            Email
                            <input
                                name="email"
                                type="email"
                                autoComplete="username"
                                required
                                placeholder="owner@sibase.local"
                            />
                        </label>
                        <label>
                            Password
                            <input
                                name="password"
                                type="password"
                                autoComplete="current-password"
                                required
                            />
                        </label>
                        <button className="control-primary" disabled={busy}>
                            {busy ? 'Signing in…' : 'Sign in'}
                        </button>
                    </form>
                    <small>Local pilot · An operator provisions platform accounts.</small>
                </section>
            </main>
        );

    return (
        <div className="control-app">
            <header className="control-header">
                <a href="/" className="control-logo">
                    SiBase<span>Control plane</span>
                </a>
                <span className="control-local">LOCAL PILOT / PHASE 2</span>
                <span>{email}</span>
                <button
                    disabled={busy}
                    onClick={() =>
                        void act(async () => {
                            await api('/logout', 'POST');
                            window.dispatchEvent(new window.Event('sibase-signout'));
                        })
                    }
                >
                    Sign out
                </button>
            </header>
            <div className="control-layout">
                <aside>
                    <label>
                        Workspace
                        <select
                            aria-label="Workspace"
                            value={wid}
                            onChange={(e) => {
                                setWid(e.target.value);
                                setSelected('');
                                setRevealed('');
                            }}
                        >
                            {workspaces.map((w) => (
                                <option key={w.id} value={w.id}>
                                    {w.name}
                                </option>
                            ))}
                        </select>
                    </label>
                    <span className="control-role">{workspace?.role ?? 'No workspace'}</span>
                    <nav>
                        {['Projects', 'Team', 'Audit log'].map((t) => (
                            <button
                                className={tab === t ? 'active' : ''}
                                key={t}
                                onClick={() => {
                                    setTab(t);
                                    setRevealed('');
                                }}
                            >
                                {t}
                            </button>
                        ))}
                    </nav>
                    <details>
                        <summary>New workspace</summary>
                        <form
                            onSubmit={(e) => {
                                e.preventDefault();
                                const form = e.currentTarget;
                                const name = new FormData(form).get('name');
                                void act(async () => {
                                    const w = await api<Workspace>('/workspaces', 'POST', { name });
                                    await refreshWorkspaces();
                                    setWid(w.id);
                                    setSelected('');
                                    form.reset();
                                });
                            }}
                        >
                            <label>
                                Name
                                <input name="name" required maxLength={80} />
                            </label>
                            <button disabled={busy}>Create workspace</button>
                        </form>
                    </details>
                    <p className="control-sidebar-note">
                        Database, Auth, Storage & Realtime.
                        <br />
                        Private infrastructure for your internal team.
                    </p>
                </aside>
                <main>
                    <div className="control-eyebrow">
                        {workspace?.name ?? 'GET STARTED'} / {tab.toUpperCase()}
                    </div>
                    <h1>
                        {tab === 'Projects'
                            ? 'Build your next internal tool.'
                            : tab === 'Team'
                              ? 'A place for your team.'
                              : 'Every change, accounted for.'}
                    </h1>
                    <p className="control-subtitle">
                        {tab === 'Projects'
                            ? 'Isolated databases. A shared home for your applications.'
                            : tab === 'Team'
                              ? 'Workspace permissions are checked on every management request.'
                              : 'The latest 100 workspace events. Credentials are never recorded.'}
                    </p>
                    {error && (
                        <div role="alert" className="control-error">
                            {error}
                            <button onClick={() => setError('')}>Dismiss</button>
                        </div>
                    )}
                    {tab === 'Projects' && (
                        <>
                            {manage && (
                                <form
                                    className="control-inline"
                                    onSubmit={(e) => {
                                        e.preventDefault();
                                        const form = e.currentTarget;
                                        const name = new FormData(form).get('name');
                                        const requestId =
                                            form.dataset.requestId || crypto.randomUUID();
                                        form.dataset.requestId = requestId;
                                        void act(async () => {
                                            const p = await api<Project>(
                                                base + '/projects',
                                                'POST',
                                                { name },
                                                { 'Idempotency-Key': requestId },
                                            );
                                            delete form.dataset.requestId;
                                            form.reset();
                                            await refresh();
                                            setSelected(p.id);
                                        });
                                    }}
                                >
                                    <label>
                                        Project name
                                        <input
                                            name="name"
                                            placeholder="e.g. Operations portal"
                                            maxLength={80}
                                            required
                                            onChange={(e) => {
                                                delete e.currentTarget.form?.dataset.requestId;
                                            }}
                                        />
                                    </label>
                                    <button className="control-primary" disabled={busy || !wid}>
                                        + Create project
                                    </button>
                                </form>
                            )}
                            {!projects.length && (
                                <section className="control-empty">
                                    <h2>Your first project starts here.</h2>
                                    <p>
                                        {manage
                                            ? 'Create a project to provision a database and its services. This usually takes a few minutes.'
                                            : 'Ask a workspace Owner or Admin to create a project.'}
                                    </p>
                                </section>
                            )}
                            <div className="control-projects">
                                {projects.map((p) => (
                                    <button
                                        key={p.id}
                                        className={
                                            'control-project ' +
                                            (selected === p.id ? 'selected' : '')
                                        }
                                        onClick={() => setSelected(p.id)}
                                    >
                                        <div className="control-project-top">
                                            <span className="control-project-icon">▤</span>
                                            <span className={'control-status ' + p.status}>
                                                {p.status}
                                            </span>
                                        </div>
                                        <h2>{p.name}</h2>
                                        <code>{p.ref}</code>
                                        <p>
                                            {p.job.checkpoint} · attempt {p.job.attempts}
                                        </p>
                                        <span>Open project ↗</span>
                                    </button>
                                ))}
                            </div>
                            {project && (
                                <section className="control-card control-overview">
                                    <div className="control-section-title">
                                        <h2>{project.name}</h2>
                                        <span className={'control-status ' + project.status}>
                                            {project.status}
                                        </span>
                                    </div>
                                    <label>
                                        Project endpoint
                                        <code className="control-code">{project.endpoint}</code>
                                    </label>
                                    <p>
                                        Provisioning: {project.job.state} / {project.job.checkpoint}
                                        {project.job.error && ` — ${project.job.error}`}
                                    </p>
                                    {project.restore_until && (
                                        <p>
                                            Restore before{' '}
                                            {new Date(
                                                project.restore_until * 1000,
                                            ).toLocaleString()}
                                            . Physical deletion is operator-reviewed.
                                        </p>
                                    )}
                                    {manage && (
                                        <div className="control-actions">
                                            {(project.desired === 'deleted'
                                                ? ['restore']
                                                : [
                                                      'suspend',
                                                      'resume',
                                                      'archive',
                                                      'delete',
                                                      ...(project.status === 'failed'
                                                          ? ['retry']
                                                          : []),
                                                  ]
                                            ).map((action) => (
                                                <button
                                                    disabled={busy}
                                                    key={action}
                                                    onClick={() => void lifecycle(action)}
                                                >
                                                    {action}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                    <h3>API keys</h3>
                                    <p>
                                        Keys are shown once. Keep service-role keys on trusted
                                        servers only.
                                    </p>
                                    {manage ? (
                                        <>
                                            <div className="control-actions">
                                                <button
                                                    disabled={busy}
                                                    onClick={() => void changeKey('create')}
                                                >
                                                    Create anon key
                                                </button>
                                                <button
                                                    disabled={busy}
                                                    onClick={() =>
                                                        void changeKey(
                                                            'create',
                                                            undefined,
                                                            'service_role',
                                                        )
                                                    }
                                                >
                                                    Create server key
                                                </button>
                                            </div>
                                            {revealed && (
                                                <div role="status" className="control-reveal">
                                                    <strong>
                                                        Save this key now — it cannot be displayed
                                                        again.
                                                    </strong>
                                                    <code>{revealed}</code>
                                                    <button onClick={() => setRevealed('')}>
                                                        I saved it · Hide
                                                    </button>
                                                </div>
                                            )}
                                            {keys.map((k) => (
                                                <div key={k.id} className="control-key">
                                                    <code>{k.prefix}…</code>
                                                    <span>
                                                        {k.role} ·{' '}
                                                        {k.revoked ? 'revoked' : 'active'}
                                                    </span>
                                                    {!k.revoked && (
                                                        <>
                                                            <button
                                                                disabled={busy}
                                                                onClick={() =>
                                                                    void changeKey('rotate', k.id)
                                                                }
                                                            >
                                                                Rotate
                                                            </button>
                                                            <button
                                                                disabled={busy}
                                                                onClick={() =>
                                                                    void changeKey('revoke', k.id)
                                                                }
                                                            >
                                                                Revoke
                                                            </button>
                                                        </>
                                                    )}
                                                </div>
                                            ))}
                                        </>
                                    ) : (
                                        <p>Only Owner and Admin can manage project keys.</p>
                                    )}
                                    {manage && (
                                        <AppAuthPanel
                                            key={project.id}
                                            base={base + '/projects/' + project.id}
                                        />
                                    )}
                                    <p className="control-note">
                                        Table editor and file browser are planned for later phases.
                                    </p>
                                </section>
                            )}
                        </>
                    )}
                    {tab === 'Team' && (
                        <section className="control-card">
                            <h2>Workspace members</h2>
                            <p>
                                Owner / Admin manage projects and membership. Developer / Viewer
                                have read-only control-plane access in this phase.
                            </p>
                            {members.map((m) => (
                                <div className="control-member" key={m.id}>
                                    <span>{m.email}</span>
                                    <span className="control-role">{m.role}</span>
                                    {manage && m.role !== 'owner' && (
                                        <button
                                            disabled={busy}
                                            onClick={() => {
                                                if (
                                                    window.confirm(
                                                        'Remove workspace access for ' +
                                                            m.email +
                                                            '?',
                                                    )
                                                )
                                                    void act(async () => {
                                                        await api(
                                                            base + '/members/' + m.id,
                                                            'DELETE',
                                                        );
                                                        await refresh();
                                                        await refreshWorkspaces();
                                                    });
                                            }}
                                        >
                                            Remove
                                        </button>
                                    )}
                                    {workspace?.role === 'owner' && m.role !== 'owner' && (
                                        <button
                                            disabled={busy}
                                            onClick={() => {
                                                if (
                                                    window.confirm(
                                                        'Transfer ownership to ' +
                                                            m.email +
                                                            '? You will become an Admin.',
                                                    )
                                                )
                                                    void act(async () => {
                                                        await api(
                                                            base + '/transfer/' + m.id,
                                                            'POST',
                                                        );
                                                        await refresh();
                                                        await refreshWorkspaces();
                                                    });
                                            }}
                                        >
                                            Make Owner
                                        </button>
                                    )}
                                </div>
                            ))}
                            {manage && (
                                <form
                                    className="control-inline"
                                    onSubmit={(e) => {
                                        e.preventDefault();
                                        const form = e.currentTarget;
                                        const data = new FormData(form);
                                        void act(async () => {
                                            await api(base + '/members', 'PUT', {
                                                email: data.get('email'),
                                                role: data.get('role'),
                                            });
                                            form.reset();
                                            await refresh();
                                            await refreshWorkspaces();
                                        });
                                    }}
                                >
                                    <label>
                                        Account email
                                        <input name="email" type="email" required />
                                    </label>
                                    <label>
                                        Role
                                        <select name="role">
                                            <option value="viewer">Viewer</option>
                                            <option value="developer">Developer</option>
                                            <option value="admin">Admin</option>
                                        </select>
                                    </label>
                                    <button disabled={busy}>Add / update member</button>
                                </form>
                            )}
                            <p className="control-note">
                                An operator must create the account first:{' '}
                                <code>
                                    python3 scripts/phase2.py user --email teammate@example.com
                                </code>
                            </p>
                        </section>
                    )}
                    {tab === 'Audit log' && (
                        <section className="control-card">
                            {!events.length && <p>No events yet.</p>}
                            {events.map((a) => (
                                <div className="control-event" key={a.id}>
                                    <time>{new Date(a.created * 1000).toLocaleString()}</time>
                                    <strong>{a.action}</strong>
                                    <code>{a.target}</code>
                                </div>
                            ))}
                        </section>
                    )}
                </main>
            </div>
        </div>
    );
}
