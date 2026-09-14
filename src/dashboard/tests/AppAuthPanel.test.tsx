import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import AppAuthPanel from '../control/AppAuthPanel';
import { api } from '../control/api';

vi.mock('../control/api', () => ({ api: vi.fn() }));
const response = {
    enabled: true,
    settings: { jwt_exp: 900, site_url: 'https://app.example.com', signing_epoch: 1 },
    snapshot: {
        collected: 1,
        error: null,
        users: [{ id: 'alice', email: 'alice@example.com', email_confirmed_at: '2026-09-14' }],
        sessions: [{ id: 'session1', user_id: 'alice', created_at: '2026-09-14' }],
        tables: [{ name: 'phase3_tasks', rls: true, force_rls: true }],
        policies: [],
        roles: [],
    },
};

describe('Application auth panel', () => {
    it('shows separate app users, sessions and policy metadata', async () => {
        vi.mocked(api).mockResolvedValue(response);
        render(<AppAuthPanel base="/project" />);
        expect(await screen.findByText('alice@example.com')).toBeInTheDocument();
        await userEvent.click(screen.getByRole('button', { name: 'Sessions' }));
        expect(screen.getByText('session1')).toBeInTheDocument();
        await userEvent.click(screen.getByRole('button', { name: 'Permission preview' }));
        expect(screen.getByText('RLS enabled + forced')).toBeInTheDocument();
        await userEvent.click(screen.getByRole('button', { name: 'Auth Settings' }));
        expect(screen.getByLabelText('Access token lifetime (seconds)')).toHaveValue(900);
        expect(
            screen.getByRole('button', { name: 'Rotate project signing key' }),
        ).toBeInTheDocument();
    });

    it('warns before enabling and displays worker snapshot errors', async () => {
        vi.mocked(api).mockResolvedValue({
            enabled: false,
            settings: null,
            snapshot: { collected: 1, error: 'unavailable' },
        });
        render(<AppAuthPanel base="/project" />);
        expect(await screen.findByText(/Not enabled for this project/)).toBeInTheDocument();
        expect(screen.getByRole('alert')).toHaveTextContent('Live metadata unavailable');
        await userEvent.click(screen.getByRole('button', { name: 'Auth Settings' }));
        expect(
            screen.getByRole('button', { name: 'Enable verified Auth and RLS' }),
        ).toBeInTheDocument();
    });
});
