import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import AuthCallback from '../control/AuthCallback';

it('clears callback secrets without starting a platform session', () => {
    window.history.replaceState(null, '', '/auth/callback?error=private#access_token=private');
    render(<AuthCallback />);
    expect(window.location.search).toBe('');
    expect(window.location.hash).toBe('');
    expect(screen.getByRole('heading').textContent).toBe('Application authentication callback');
    expect(screen.queryByText('private')).toBeNull();
    window.history.replaceState(null, '', '/');
});
