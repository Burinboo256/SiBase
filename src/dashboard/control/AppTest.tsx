import { useEffect, useState } from 'react';
import {
    appRequest,
    consumeCallback,
    readConfig,
    saveConfig,
    validConfig,
} from './app-test-client';
import type { AppConfig, AppSession } from './app-test-client';

// Capture once before StrictMode effects run; never persist callback credentials.
const callback = consumeCallback();
type Task = { id: string; title: string };

export default function AppTest() {
    const [config, setConfig] = useState<AppConfig | null>(readConfig);
    const [session, setSession] = useState<AppSession | null>(callback.session);
    const [email, setEmail] = useState('');
    const [tasks, setTasks] = useState<Task[]>([]);
    const [notice, setNotice] = useState(
        callback.failed ? 'Verification link rejected or expired.' : '',
    );
    const [error, setError] = useState('');
    const [busy, setBusy] = useState(false);

    useEffect(() => {
        callback.session = null;
    }, []);

    useEffect(() => {
        if (!config || !session) return;
        let active = true;
        void appRequest<{ email: string }>(config, '/auth/v1/user', 'GET', undefined, session)
            .then((user) => {
                if (active) setEmail(user.email);
            })
            .catch(() => {
                if (active) {
                    setSession(null);
                    setError('Application session is invalid. Sign in again.');
                }
            });
        return () => {
            active = false;
        };
    }, [config, session]);

    async function act(action: () => Promise<void>) {
        setBusy(true);
        setError('');
        setNotice('');
        try {
            await action();
        } catch (e) {
            setError(e instanceof Error ? e.message : 'Application request failed.');
        } finally {
            setBusy(false);
        }
    }

    async function loadTasks() {
        if (config && session)
            setTasks(
                await appRequest<Task[]>(
                    config,
                    '/rest/v1/phase3_tasks?select=id,title&order=title',
                    'GET',
                    undefined,
                    session,
                ),
            );
    }

    return (
        <div className="control-app">
            <main className="control-card app-test">
                <h1>SiBase application test</h1>
                <p>
                    Local acceptance app — separate from platform administration. Use synthetic data
                    only.
                </p>
                <p>
                    Only the public project reference and anon key are saved locally. Passwords and
                    session tokens stay in memory; reloading requires sign-in.
                </p>
                {error && <p role="alert">{error}</p>}
                {notice && <p role="status">{notice}</p>}
                {!config ? (
                    <form
                        onSubmit={(event) => {
                            event.preventDefault();
                            const form = new FormData(event.currentTarget);
                            const next = {
                                ref: String(form.get('ref')),
                                key: String(form.get('key')),
                            };
                            if (!validConfig(next)) {
                                setError(
                                    'Enter a valid project reference and anon key. Never use a server key.',
                                );
                                return;
                            }
                            saveConfig(next);
                            setConfig(next);
                            setError('');
                        }}
                    >
                        <label>
                            Project reference
                            <input name="ref" required />
                        </label>
                        <label>
                            Public anon key
                            <input name="key" required autoComplete="off" />
                        </label>
                        <button>Connect project</button>
                    </form>
                ) : (
                    <>
                        <p>
                            Project: <code>{config.ref}</code>
                        </p>
                        <button
                            disabled={busy}
                            onClick={() => {
                                saveConfig(null);
                                setConfig(null);
                                setSession(null);
                                setEmail('');
                                setTasks([]);
                            }}
                        >
                            Forget project
                        </button>
                        {!session ? (
                            <>
                                <h2>Account access</h2>
                                <form
                                    onSubmit={(event) => {
                                        event.preventDefault();
                                        const form = new FormData(event.currentTarget);
                                        const account = {
                                            email: String(form.get('email')),
                                            password: String(form.get('password')),
                                        };
                                        const action =
                                            (
                                                event.nativeEvent as SubmitEvent
                                            ).submitter?.getAttribute('value') ?? 'login';
                                        event.currentTarget.reset();
                                        void act(async () => {
                                            if (action === 'signup') {
                                                await appRequest(
                                                    config,
                                                    '/auth/v1/signup',
                                                    'POST',
                                                    account,
                                                );
                                                setNotice(
                                                    'Check the local inbox to confirm your email, then sign in.',
                                                );
                                            } else {
                                                const result = await appRequest<AppSession>(
                                                    config,
                                                    '/auth/v1/token?grant_type=password',
                                                    'POST',
                                                    account,
                                                );
                                                setSession(result);
                                                setEmail(account.email);
                                                setTasks([]);
                                                setNotice('Signed in to the application.');
                                            }
                                        });
                                    }}
                                >
                                    <label>
                                        Email
                                        <input
                                            name="email"
                                            type="email"
                                            autoComplete="off"
                                            required
                                        />
                                    </label>
                                    <label>
                                        Password
                                        <input
                                            name="password"
                                            type="password"
                                            minLength={12}
                                            autoComplete="off"
                                            required
                                        />
                                    </label>
                                    <div className="control-actions">
                                        <button disabled={busy} value="login">
                                            Sign in to app
                                        </button>
                                        <button disabled={busy} value="signup">
                                            Create app account
                                        </button>
                                    </div>
                                </form>
                                <h2>Password recovery</h2>
                                <form
                                    onSubmit={(event) => {
                                        event.preventDefault();
                                        const recoveryEmail = String(
                                            new FormData(event.currentTarget).get('email'),
                                        );
                                        event.currentTarget.reset();
                                        void act(async () => {
                                            await appRequest(config, '/auth/v1/recover', 'POST', {
                                                email: recoveryEmail,
                                            });
                                            setNotice(
                                                'If the account exists, a recovery email has been sent to the local inbox.',
                                            );
                                        });
                                    }}
                                >
                                    <label>
                                        Recovery email
                                        <input
                                            name="email"
                                            type="email"
                                            autoComplete="off"
                                            required
                                        />
                                    </label>
                                    <button disabled={busy}>Send recovery email</button>
                                </form>
                            </>
                        ) : (
                            <>
                                <h2>Application session</h2>
                                <p data-testid="app-user">
                                    Signed in as {email || 'verifying user…'}
                                </p>
                                <div className="control-actions">
                                    <button
                                        disabled={busy}
                                        onClick={() =>
                                            void act(async () => {
                                                setSession(
                                                    await appRequest<AppSession>(
                                                        config,
                                                        '/auth/v1/token?grant_type=refresh_token',
                                                        'POST',
                                                        { refresh_token: session.refresh_token },
                                                    ),
                                                );
                                                setNotice('Application session refreshed.');
                                            })
                                        }
                                    >
                                        Refresh session
                                    </button>
                                    <button
                                        disabled={busy}
                                        onClick={() =>
                                            void act(async () => {
                                                await appRequest(
                                                    config,
                                                    '/auth/v1/logout?scope=global',
                                                    'POST',
                                                    undefined,
                                                    session,
                                                );
                                                setSession(null);
                                                setEmail('');
                                                setTasks([]);
                                                setNotice(
                                                    'Signed out. Refresh tokens revoked; issued access tokens expire normally.',
                                                );
                                            })
                                        }
                                    >
                                        Sign out of app
                                    </button>
                                </div>
                                <h2>Own-row tasks</h2>
                                <button disabled={busy} onClick={() => void act(loadTasks)}>
                                    Load my tasks
                                </button>
                                <form
                                    onSubmit={(event) => {
                                        event.preventDefault();
                                        const title = String(
                                            new FormData(event.currentTarget).get('title'),
                                        );
                                        event.currentTarget.reset();
                                        void act(async () => {
                                            await appRequest(
                                                config,
                                                '/rest/v1/phase3_tasks',
                                                'POST',
                                                { title },
                                                session,
                                            );
                                            await loadTasks();
                                            setNotice('Task saved with owner-row permissions.');
                                        });
                                    }}
                                >
                                    <label>
                                        Task title
                                        <input name="title" maxLength={500} required />
                                    </label>
                                    <button disabled={busy}>Add my task</button>
                                </form>
                                <ul aria-label="My tasks">
                                    {tasks.map((task) => (
                                        <li key={task.id}>{task.title}</li>
                                    ))}
                                </ul>
                                <h2>Set a new password</h2>
                                <p>
                                    Use a fresh recovery session. Older sessions may require
                                    reauthentication.
                                </p>
                                <form
                                    onSubmit={(event) => {
                                        event.preventDefault();
                                        const password = String(
                                            new FormData(event.currentTarget).get('password'),
                                        );
                                        event.currentTarget.reset();
                                        void act(async () => {
                                            await appRequest(
                                                config,
                                                '/auth/v1/user',
                                                'PUT',
                                                { password },
                                                session,
                                            );
                                            setNotice(
                                                'Password updated. Sign out and sign in with the new password.',
                                            );
                                        });
                                    }}
                                >
                                    <label>
                                        New password
                                        <input
                                            name="password"
                                            type="password"
                                            minLength={12}
                                            autoComplete="off"
                                            required
                                        />
                                    </label>
                                    <button disabled={busy}>Update app password</button>
                                </form>
                            </>
                        )}
                    </>
                )}
                <p>
                    <a href="/">Platform dashboard</a> ·{' '}
                    <a href="http://127.0.0.1:58425" rel="noreferrer" target="_blank">
                        Local inbox
                    </a>
                </p>
            </main>
        </div>
    );
}
