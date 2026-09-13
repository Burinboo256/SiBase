import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import App from '../App';
import type { Overview } from '../api';

const service = {
    id: 'database',
    name: 'PostgreSQL',
    status: 'up' as const,
    latency_ms: 2,
    detail: 'Probe succeeded',
};
const overview: Overview = {
    environment: 'test',
    phase: 1,
    checked_at: '2026-09-13T00:00:00Z',
    platform: { ...service, id: 'platform' },
    projects: [
        {
            ref: 'alpha',
            name: 'Alpha',
            endpoint: 'http://127.0.0.1:58201',
            status: 'healthy',
            services: [service],
        },
        {
            ref: 'beta',
            name: 'Beta',
            endpoint: 'http://127.0.0.1:58202',
            status: 'degraded',
            services: [{ ...service, status: 'down' }],
        },
    ],
};

function respond(data = overview) {
    return vi.fn().mockResolvedValue({ ok: true, json: async () => data });
}

describe('Dashboard foundation', () => {
    it('shows loading then actual API results', async () => {
        const fetch = respond();
        vi.stubGlobal('fetch', fetch);
        render(<App />);
        expect(screen.getByRole('status')).toBeInTheDocument();
        expect(await screen.findByText('All systems operational')).toBeInTheDocument();
        expect(screen.getByText('http://127.0.0.1:58201')).toBeInTheDocument();
        expect(fetch).toHaveBeenCalledWith(
            '/api/v1/overview',
            expect.objectContaining({ signal: expect.any(AbortSignal) }),
        );
    });

    it('switches projects and displays degraded status', async () => {
        vi.stubGlobal('fetch', respond());
        render(<App />);
        await screen.findByText('All systems operational');
        await userEvent.selectOptions(screen.getByLabelText('Project'), 'beta');
        expect(screen.getByText('Needs attention')).toBeInTheDocument();
        expect(screen.getByText('Unavailable')).toBeInTheDocument();
        expect(screen.getByText('http://127.0.0.1:58202')).toBeInTheDocument();
    });

    it('handles API failure and retry', async () => {
        const fetch = vi
            .fn()
            .mockRejectedValueOnce(new Error('offline'))
            .mockImplementation(respond());
        vi.stubGlobal('fetch', fetch);
        render(<App />);
        expect(await screen.findByRole('alert')).toHaveTextContent('เชื่อมต่อ Control API ไม่ได้');
        await userEvent.click(screen.getByRole('button', { name: /Refresh status/ }));
        expect(await screen.findByText('All systems operational')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });

    it('does not present stale data as newly verified', async () => {
        const fetch = respond().mockRejectedValueOnce(new Error('offline'));
        fetch.mockReset().mockImplementationOnce(respond()).mockRejectedValue(new Error('offline'));
        vi.stubGlobal('fetch', fetch);
        render(<App />);
        await screen.findByText('All systems operational');
        await userEvent.click(screen.getByRole('button', { name: /Refresh status/ }));
        await screen.findByRole('alert');
        expect(screen.getByText('Unverified')).toBeInTheDocument();
    });

    it('distinguishes future pages from working features', async () => {
        vi.stubGlobal('fetch', respond());
        render(<App />);
        await screen.findByText('All systems operational');
        await userEvent.click(screen.getByRole('button', { name: 'Database' }));
        expect(screen.getByText('Database is on the roadmap')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Create table' })).not.toBeInTheDocument();
        await userEvent.click(screen.getByRole('button', { name: 'API Docs' }));
        expect(screen.getByRole('link', { name: /Open Control API docs/ })).toHaveAttribute(
            'href',
            '/api/docs',
        );
    });

    it('handles an empty project configuration', async () => {
        vi.stubGlobal('fetch', respond({ ...overview, projects: [] }));
        render(<App />);
        expect(await screen.findByText('ยังไม่มีโปรเจกต์ใน configuration')).toBeInTheDocument();
        expect(screen.getByLabelText('Project')).toBeDisabled();
    });

    it('handles HTTP error responses', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
        render(<App />);
        await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    });
});
