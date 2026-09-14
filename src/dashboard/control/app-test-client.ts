export type AppConfig = { ref: string; key: string };
export type AppSession = { access_token: string; refresh_token: string };
const CONFIG_KEY = 'sibase.local-app-test';

export function validConfig(value: unknown): value is AppConfig {
    if (!value || typeof value !== 'object') return false;
    const config = value as AppConfig;
    return /^p_[a-f0-9]{16}$/.test(config.ref) && /^sb_anon_[A-Za-z0-9_-]{30,}$/.test(config.key);
}

export function readConfig(): AppConfig | null {
    try {
        const value: unknown = JSON.parse(localStorage.getItem(CONFIG_KEY) ?? 'null');
        return validConfig(value) ? value : null;
    } catch {
        return null;
    }
}

export function saveConfig(config: AppConfig | null) {
    if (config) localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
    else localStorage.removeItem(CONFIG_KEY);
}

export function consumeCallback(): { session: AppSession | null; failed: boolean } {
    if (window.location.pathname !== '/auth/callback') return { session: null, failed: false };
    const params = new URLSearchParams(window.location.hash.slice(1));
    const access_token = params.get('access_token');
    const refresh_token = params.get('refresh_token');
    window.history.replaceState(null, '', readConfig() ? '/app-test' : '/auth/callback');
    return {
        session: access_token && refresh_token ? { access_token, refresh_token } : null,
        failed: params.has('error') || params.has('error_code'),
    };
}

export async function appRequest<T>(
    config: AppConfig,
    path: string,
    method = 'GET',
    body?: object,
    session?: AppSession | null,
): Promise<T> {
    if (!['127.0.0.1', 'localhost'].includes(window.location.hostname))
        throw new Error('This test application is loopback-only.');
    const endpoint = `http://${window.location.hostname}:58420/p/${config.ref}`;
    const response = await fetch(endpoint + path, {
        method,
        credentials: 'omit',
        headers: {
            apikey: config.key,
            'Content-Type': 'application/json',
            Prefer: 'return=representation',
            ...(session ? { Authorization: 'Bearer ' + session.access_token } : {}),
        },
        body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) throw new Error(`Application request rejected (${response.status}).`);
    if (response.status === 204) return undefined as T;
    return response.json();
}
