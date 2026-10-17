import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * The open request is replaced by a fresh copy on a 30-second (or 5-second)
 * refresh and on every edit. The effect that scrolls the detail panel to the
 * top and focuses its heading must run when a different request is opened,
 * not on every refresh -- otherwise the panel jumps to the top, and focus
 * leaves a half-typed comment, while staff are using it.
 */
describe('the request detail panel', () => {
    const src = readFileSync(resolve(__dirname, 'StaffDashboard.tsx'), 'utf8');

    it('scrolls to the top only when the open request id changes', () => {
        const start = src.indexOf('const openRequestId = selectedRequest?.service_request_id;');
        expect(start).toBeGreaterThan(-1);
        const effect = src.slice(start, src.indexOf('}, [openRequestId, currentView, updateHash, updateTitle]);', start));
        expect(effect).toContain("scrollTo({ top: 0");
        expect(src).not.toContain('}, [selectedRequest, currentView, updateHash, updateTitle]);');
    });
});
