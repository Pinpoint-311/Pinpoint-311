import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
    plugins: [react()],
    build: {
        outDir: 'dist-probe',
        sourcemap: false,
        rollupOptions: {
            input: { main: 'index.html', probe: 'src/__probe_isolation.ts' },
        },
    },
})
