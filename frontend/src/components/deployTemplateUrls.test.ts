import { describe, expect, it } from 'vitest';

import {
    awsDeployUrl,
    azureDeployUrl,
    INSTANCE_TEMPLATE_PATH,
    isPubliclyReachable,
    PUBLISHED_TEMPLATE_BASE_URL,
    templateBase,
} from './deployTemplateUrls';

/**
 * The deploy buttons hand a URL to somebody else's servers.
 *
 * That is the whole reason this is worth testing rather than eyeballing: the
 * page never fetches these URLs, so a wrong one looks completely fine here and
 * fails inside Azure's portal, where the message is "the template could not be
 * loaded" and there is no indication of whose URL it was.
 */

describe('which host the cloud is sent to', () => {
    it('serves from the town\'s own install when the address is one a cloud can reach', () => {
        const from = templateBase('https://311.westfield.gov');
        expect(from.source).toBe('instance');
        expect(from.base).toBe(`https://311.westfield.gov${INSTANCE_TEMPLATE_PATH}`);
    });

    it('does not double the slash when the origin carries a trailing one', () => {
        expect(templateBase('https://311.westfield.gov/').base)
            .toBe(`https://311.westfield.gov${INSTANCE_TEMPLATE_PATH}`);
    });

    it.each([
        ['nothing configured at all', null],
        ['an empty string', ''],
        ['the developer machine', 'http://localhost:3000'],
        ['loopback by address', 'http://127.0.0.1:8000'],
        ['a bare hostname only the town network resolves', 'https://pinpoint'],
        ['an mDNS name', 'http://townhall.local'],
        ['a private class A address', 'http://10.0.0.7:3000'],
        ['a private class B address', 'https://172.20.1.4'],
        ['a private class C address', 'http://192.168.1.50'],
        ['a link-local address', 'http://169.254.1.1'],
        ['a carrier-grade NAT address', 'http://100.90.1.1'],
        ['something that is not a URL', 'town hall'],
    ])('falls back to the published copy for %s', (_why, origin) => {
        const from = templateBase(origin);
        expect(from.source).toBe('published');
        expect(from.base).toBe(PUBLISHED_TEMPLATE_BASE_URL);
    });

    it('does not demote a public address that merely looks unusual', () => {
        // The denylist must never grow into a de-facto allowlist. A town on a
        // real public address being quietly served templates from a repository
        // it may have forked away from is the failure this direction protects.
        for (const origin of ['https://311.co.union.nj.us', 'http://8.8.8.8',
                              'https://pinpoint.town.gov:8443', 'https://311.localhost.gov']) {
            expect(isPubliclyReachable(origin), origin).toBe(true);
        }
    });
});

describe('the URLs the providers are actually given', () => {
    const base = templateBase('https://311.westfield.gov').base;

    it('hands Azure a portal link with the template URL encoded into the fragment', () => {
        const url = azureDeployUrl(base);
        expect(url.startsWith('https://portal.azure.com/#create/Microsoft.Template/uri/')).toBe(true);
        // Encoded, not raw: the template URL lives inside a fragment path
        // segment, and an unencoded `/` there is read as portal navigation.
        expect(url).toContain(encodeURIComponent(`${base}/azure/pinpoint-311.json`));
        expect(url).not.toContain(`${base}/azure`);
    });

    it('hands CloudFormation the review screen, so nothing is created before it is read', () => {
        const url = awsDeployUrl(base);
        expect(url).toContain('/stacks/create/review?templateURL=');
        expect(url).toContain(encodeURIComponent(`${base}/aws/pinpoint-311.yaml`));
        expect(url).toContain('stackName=pinpoint-311');
    });

    it('points at the same two files whichever host it fell back to', () => {
        for (const origin of ['https://311.westfield.gov', 'http://10.0.0.7:3000']) {
            const b = templateBase(origin).base;
            expect(azureDeployUrl(b)).toContain(encodeURIComponent('/azure/pinpoint-311.json'));
            expect(awsDeployUrl(b)).toContain(encodeURIComponent('/aws/pinpoint-311.yaml'));
        }
    });
});
