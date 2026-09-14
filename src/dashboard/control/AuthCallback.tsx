import { useEffect } from 'react';

export default function AuthCallback() {
    useEffect(() => {
        // This local landing page deliberately does not create a platform session.
        // Application callbacks must use their own project SDK and redirect URL.
        window.history.replaceState(null, '', '/auth/callback');
    }, []);
    return (
        <main className="control-card">
            <h1>Application authentication callback</h1>
            <p>
                This is the local test callback, not the SiBase administrator login. Tokens and
                error details have been removed from this address and are not saved.
            </p>
            <p>
                Return to your application to sign in. For password recovery, configure your
                application's callback URL in Auth Settings and request a new recovery email there.
                Your application must handle the recovery session and password update with its
                project SDK.
            </p>
            <a href="/">Open platform dashboard</a>
        </main>
    );
}
