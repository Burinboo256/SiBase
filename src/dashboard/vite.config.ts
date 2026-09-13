import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        strictPort: true,
        proxy: {
            '/api/': { target: process.env.SIBASE_API_PROXY || 'http://127.0.0.1:58210' },
            '/health/': { target: process.env.SIBASE_API_PROXY || 'http://127.0.0.1:58210' },
        },
    },
    test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], restoreMocks: true },
});
