import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
    plugins: [react()],
    server: {
        host: '0.0.0.0',
        port: 5173,
        allowedHosts: true, // Allow any host (for custom domains)
        proxy: {
            '/api': {
                target: 'http://backend:8000',
                changeOrigin: true,
            },
        },
    },
    build: {
        outDir: 'dist',
        sourcemap: true,
    },
    test: {
        // Vitest's default is 5s, and the setup-page tests mount the whole
        // integrations page -- several hundred nodes, a dozen mocked fetches,
        // framer-motion -- which lands close enough to that ceiling that adding
        // any test file elsewhere in the suite pushes it over. The failure then
        // reads as a broken page rather than as a busy machine.
        testTimeout: 20000,
    },
})
