export type Workspace = { id: string; name: string; role: string };
export type Project = {
    id: string;
    name: string;
    ref: string;
    endpoint: string;
    status: string;
    desired: string;
    restore_until: number | null;
    job: { state: string; checkpoint: string; attempts: number; error: string | null };
};
export type Member = { id: string; email: string; role: string };
export type Key = { id: string; prefix: string; role: string; revoked: number | null };
export type Event = { id: string; action: string; target: string; created: number };
let csrf = '';
export function setCsrf(value: string) {
    csrf = value;
}
export async function api<T>(
    path: string,
    method = 'GET',
    body?: object,
    extra?: Record<string, string>,
): Promise<T> {
    const response = await fetch('/api/v2' + path, {
        method,
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf, ...extra },
        body: body ? JSON.stringify(body) : undefined,
    });
    const result = await response.json();
    if (!response.ok) {
        if (response.status === 401) window.dispatchEvent(new Event('sibase-signout'));
        throw new Error(
            typeof result.detail === 'string' ? result.detail : 'Please check the form values.',
        );
    }
    return result as T;
}
