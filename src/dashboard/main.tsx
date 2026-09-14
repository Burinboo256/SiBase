import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import ControlApp from './control/ControlApp';
import AuthCallback from './control/AuthCallback';
import './style.css';

createRoot(document.getElementById('root')!).render(
    <StrictMode>
        {import.meta.env.VITE_SIBASE_PHASE === '2' ? (
            window.location.pathname === '/auth/callback' ? (
                <AuthCallback />
            ) : (
                <ControlApp />
            )
        ) : (
            <App />
        )}
    </StrictMode>,
);
