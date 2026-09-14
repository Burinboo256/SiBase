import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ControlApp from '../control/ControlApp';
import { api } from '../control/api';

vi.mock('../control/api', () => ({ api: vi.fn(), setCsrf: vi.fn() }));
const mock = vi.mocked(api);
const project = {
    id: 'p1',
    ref: 'p_123',
    name: 'Operations',
    endpoint: 'http://localhost/project',
    status: 'failed',
    desired: 'ready',
    restore_until: null,
    job: { state: 'failed', checkpoint: 'database', attempts: 3, error: 'provisioning_failed' },
};

function respond(role = 'owner', projects = [project]) {
    mock.mockImplementation(async (path) => {
        if (path === '/me' || path === '/login')
            return { email: 'owner@sibase.local', csrf: 'token' };
        if (path === '/workspaces') return [{ id: 'w1', name: 'Internal team', role }];
        if (path.endsWith('/projects')) return projects;
        if (path.endsWith('/members'))
            return [{ id: 'user1', email: 'owner@sibase.local', role: 'owner' }];
        if (path.endsWith('/audit'))
            return [{ id: 'a1', action: 'project.created', target: 'p1', created: 1 }];
        return [];
    });
}

beforeEach(() => {
    mock.mockReset();
});

describe('Phase 2 control dashboard', () => {
    it('shows platform login and safe login failures', async () => {
        mock.mockRejectedValue(new Error('Invalid credentials'));
        render(<ControlApp />);
        await userEvent.type(await screen.findByLabelText('Email'), 'owner@sibase.local');
        await userEvent.type(screen.getByLabelText('Password'), 'test-password');
        await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
        expect(await screen.findByRole('alert')).toHaveTextContent('Invalid credentials');
        expect(mock).toHaveBeenCalledWith('/login', 'POST', {
            email: 'owner@sibase.local',
            password: 'test-password',
        });
    });

    it('shows real failed job state and retry control', async () => {
        respond();
        render(<ControlApp />);
        await userEvent.click(await screen.findByRole('button', { name: /Operations/ }));
        expect(screen.getByText('http://localhost/project')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'retry' })).toBeInTheDocument();
        expect(screen.getByText(/provisioning_failed/)).toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'Create server key' })).toBeInTheDocument();
    });

    it('does not offer privileged actions to Viewer', async () => {
        respond('viewer');
        render(<ControlApp />);
        await userEvent.click(await screen.findByRole('button', { name: /Operations/ }));
        expect(screen.queryByRole('button', { name: /Create project/ })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'retry' })).not.toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'Create server key' })).not.toBeInTheDocument();
        expect(
            screen.getByText('Only Owner and Admin can manage project keys.'),
        ).toBeInTheDocument();
    });

    it('shows empty state, membership and audit views', async () => {
        respond('owner', []);
        render(<ControlApp />);
        expect(await screen.findByText('Your first project starts here.')).toBeInTheDocument();
        await userEvent.click(screen.getByRole('button', { name: 'Team' }));
        expect(screen.getByText('Workspace members')).toBeInTheDocument();
        await userEvent.click(screen.getByRole('button', { name: 'Audit log' }));
        await waitFor(() => expect(screen.getByText('project.created')).toBeInTheDocument());
    });
});
