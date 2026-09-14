import { afterEach, expect, it, vi } from 'vitest';
import {
    appRequest,
    consumeCallback,
    readConfig,
    saveConfig,
    validConfig,
} from '../control/app-test-client';

const config = { ref: 'p_' + 'a'.repeat(16), key: 'sb_anon_' + 'x'.repeat(40) };

afterEach(() => {
    localStorage.clear();
    window.history.replaceState(null, '', '/');
    vi.unstubAllGlobals();
});

it('stores only validated public project configuration and rejects privileged keys', () => {
    expect(validConfig(config)).toBe(true);
    expect(validConfig({ ...config, key: 'sb_service_role_' + 'x'.repeat(40) })).toBe(false);
    expect(validConfig({ ...config, ref: '../platform' })).toBe(false);
    expect(readConfig()).toBeNull();
    saveConfig(config);
    expect(readConfig()).toEqual(config);
    saveConfig(null);
    expect(readConfig()).toBeNull();
});

it('captures callback credentials once without storing them or leaving them in the URL', () => {
    saveConfig(config);
    window.history.replaceState(
        null,
        '',
        '/auth/callback?private=value#access_token=test-access&refresh_token=test-refresh',
    );
    expect(consumeCallback()).toEqual({
        session: { access_token: 'test-access', refresh_token: 'test-refresh' },
        failed: false,
    });
    expect(window.location.pathname).toBe('/app-test');
    expect(window.location.hash + window.location.search).toBe('');
    expect(JSON.stringify(localStorage)).not.toContain('test-access');
    expect(consumeCallback().session).toBeNull();
});

it('clears rejected callback details even without a saved project', () => {
    window.history.replaceState(
        null,
        '',
        '/auth/callback#error=access_denied&error_description=private',
    );
    expect(consumeCallback()).toEqual({ session: null, failed: true });
    expect(window.location.hash).toBe('');
    expect(window.location.pathname).toBe('/auth/callback');
});

it('omits platform cookies and suppresses upstream error bodies', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });
    vi.stubGlobal('fetch', fetch);
    await expect(appRequest(config, '/auth/v1/user')).rejects.toThrow(
        'Application request rejected (401).',
    );
    expect(fetch.mock.calls[0][1].credentials).toBe('omit');
    expect(fetch.mock.calls[0][1].headers.apikey).toBe(config.key);
});
