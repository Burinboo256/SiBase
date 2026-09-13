export interface Service {
    id: string;
    name: string;
    status: 'up' | 'down';
    latency_ms: number;
    detail: string;
}

export interface Project {
    ref: string;
    name: string;
    endpoint: string;
    status: 'healthy' | 'degraded';
    services: Service[];
}

export interface Overview {
    environment: string;
    phase: number;
    checked_at: string;
    platform: Service;
    projects: Project[];
}

export async function fetchOverview(signal: AbortSignal): Promise<Overview> {
    const response = await fetch('/api/v1/overview', { signal });
    if (!response.ok) throw new Error('Control API unavailable');
    return response.json() as Promise<Overview>;
}
