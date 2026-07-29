import { defineConfig } from 'vitest/config';

/**
 * The project had no frontend test runner at all, which left two modules
 * holding real logic completely unverified: maps/geo.ts (ray-casting, bounds,
 * line-fraction maths) and maps/popup.ts, which is the escaping boundary
 * between resident-supplied text and the DOM.
 *
 * jsdom rather than a browser because that is enough to assert what actually
 * matters — that untrusted values become text nodes and never markup.
 */
export default defineConfig({
    test: {
        environment: 'jsdom',
        include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    },
});
