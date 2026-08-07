// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Where the setup checklist gets its answer.
 *
 * It used to work it out here, from hard-coded secret names ORed across every
 * provider a capability has. The backend already answers the same question per
 * provider, against the provider dispatch actually resolves, and the two
 * disagreed on the live deployment in both directions:
 *
 *   - `redactionConfigured = isConfigured('REDACTION_PROVIDER')`. That secret
 *     is empty on a town that never opened the card, because `resolve_provider`
 *     infers the detector from the moderation and AI settings. The page said
 *     photo redaction was not set up while it was blurring every photo.
 *   - `kmsConfigured` ORed KMS_KEY_ID, AZURE_KEYVAULT_URL and AWS_KMS_KEY_ID.
 *     All three are empty when the Google key is on its defaults, so the page
 *     said PII encryption was not set up while Google Cloud KMS was wrapping
 *     the data key.
 *   - `aiConfigured` and `translationConfigured` both ORed AWS_REGION, a key
 *     SES, SNS, Bedrock, AWS KMS and AWS Translate all share. Configuring email
 *     over SES would have ticked AI and translation for a town with neither.
 *
 * These tests pin the direction of trust: the server's per-capability answer
 * decides, and a stored secret name on its own decides nothing.
 */

const providerStatus: { value: Record<string, unknown> } = { value: {} };

vi.mock('../services/api', () => {
    const shapes: Record<string, unknown> = {
        getConfig: { public_origin: 'https://town.gov' },
        getConnectorHealth: { connectors: [] },
        getCloudIdentity: null,
        getStorageStatus: { secrets: { store: 'google', count: 0, reachable: true }, pii: {} },
        getProviderCatalog: {
            capability: 'ai', current_provider: 'vertex', providers: [], configured: {},
        },
        getCloudProfile: {
            profile: 'google', managed: false, profiles: [],
            components: { identity: 'auth0' }, maps: { label: 'Google Maps' },
        },
    };
    const listish = /^(list|get)[A-Za-z]*(s|List|Configs|Layers|Errors|Catalog)$/;
    const api: any = new Proxy({}, {
        get: (_t, prop: string) => vi.fn().mockImplementation(() => Promise.resolve(
            prop === 'getProviderStatus' ? providerStatus.value
                : prop in shapes ? shapes[prop]
                : listish.test(prop) ? [] : {},
        )),
    });
    return { default: api, api };
});

let host: HTMLDivElement;
let root: Root;

/** One capability's entry as /providers/status serves it. */
const cap = (provider: string | null, ready: boolean) => ({
    current_provider: provider,
    configured: provider ? { [provider]: ready } : {},
    ready,
});

const NOTHING_READY = {
    identity: cap('auth0', false), maps: cap('google', false), ai: cap('vertex', false),
    translation: cap('google', false), kms: cap('google', false),
    redaction: cap('local', false), email: cap('smtp', false), sms: cap(null, false),
};

const secret = (key_name: string) => ({ key_name, is_configured: true, key_value: null });

async function mount(props: Record<string, unknown> = {}) {
    const { default: Page } = await import('./SetupIntegrationsPage');
    const all: any = {
        secrets: [],
        onSaveSecret: vi.fn().mockResolvedValue(undefined),
        onRefresh: vi.fn(),
        modules: { ai_analysis: false },
        onUpdateModules: vi.fn().mockResolvedValue(undefined),
        ...props,
    };
    // Inside DialogProvider, as App.tsx mounts it: the town-systems section
    // calls useDialog, which throws without the provider.
    const { DialogProvider } = await import('./DialogProvider');
    await act(async () => {
        root.render(React.createElement(DialogProvider, null, React.createElement(Page, all)));
    });
    return host.textContent || '';
}

/** How many of the checklist items the page counts as done. */
function completed(text: string): number {
    const m = text.match(/(\d+) of (\d+) integrations configured/);
    if (!m) throw new Error('the setup progress line is not on the page');
    return Number(m[1]);
}

beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
    providerStatus.value = NOTHING_READY;
});
afterEach(() => {
    act(() => root.unmount());
    host.remove();
    vi.clearAllMocks();
});

describe('what the setup checklist counts as configured', () => {

    it('counts nothing when the server says nothing is ready', async () => {
        expect(completed(await mount())).toBe(0);
    });

    it('counts a capability the server reports ready, with no secret of its name stored', async () => {
        /* The redaction false negative. `REDACTION_PROVIDER` is empty and the
         * detector is running: the selection is inferred, not stored. */
        providerStatus.value = { ...NOTHING_READY, redaction: cap('google', true) };
        expect(completed(await mount({ secrets: [] }))).toBe(1);
    });

    it('counts PII encryption from the server rather than from a key name', async () => {
        /* KMS_KEY_ID, AZURE_KEYVAULT_URL and AWS_KMS_KEY_ID are all empty when
         * the Google key sits on its defaults, and Google Cloud KMS is wrapping
         * the data key regardless. */
        providerStatus.value = { ...NOTHING_READY, kms: cap('google', true) };
        expect(completed(await mount({ secrets: [] }))).toBe(1);
    });

    it('does not count a capability because some other one shares a credential', async () => {
        /* AWS_REGION belongs to SES, SNS, Bedrock, AWS KMS and AWS Translate at
         * once. Setting up email over SES used to tick AI and translation. */
        const text = await mount({ secrets: [secret('AWS_REGION'), secret('SES_FROM_EMAIL')] });
        expect(completed(text)).toBe(0);
    });

    it('does not count text messages that are switched off', async () => {
        /* Off is an answer, and it is not "set up". The server reports
         * ready:false for it, and no provider selected. */
        providerStatus.value = { ...NOTHING_READY, sms: cap(null, false) };
        expect(completed(await mount())).toBe(0);
    });

    it('treats an unanswered request as unfinished rather than as done', async () => {
        /* The safe direction. The cost of being wrong here is asking about
         * something already done; the other way round, an item nobody opens. */
        providerStatus.value = {};
        expect(completed(await mount())).toBe(0);
    });
});

describe('seedAnswersFrom', () => {
    /* Five questionnaire answers began at Google/Auth0/Google on every page
     * load, on a town that might have been on Azure and Entra for a year --
     * while /providers/status had reported the real ones all along. The guide
     * asked a question it could have answered, then computed "done" against its
     * own default.
     *
     * Not cosmetic: `redactionProvider` falls back to the cloud answer, so a
     * fresh load evaluated the blurring task against Google's credentials on an
     * Azure town and insisted a finished setup was unfinished. */

    const azureTown = {
        identity: cap('entra', true), maps: cap('azure', true), ai: cap('azure', true),
        translation: cap('azure', true), kms: cap('azure', true),
        redaction: cap('azure', true), email: cap('acs', true), sms: cap('acs', true),
        secrets: cap('azure', true),
    } as any;

    it('takes every answer from what the server reports', async () => {
        const { seedAnswersFrom } = await import('./SetupIntegrationsPage');
        expect(seedAnswersFrom(azureTown)).toEqual({
            cloud: 'azure', idp: 'entra', maps: 'azure',
            email: 'acs', sms: 'acs', redaction: 'azure',
        });
    });

    it('leaves every answer alone when the response never arrived', async () => {
        const { seedAnswersFrom } = await import('./SetupIntegrationsPage');
        expect(seedAnswersFrom(null)).toEqual({
            cloud: null, idp: null, maps: null, email: null, sms: null, redaction: null,
        });
    });

    it('does not seed the text-message answer when texting is off', async () => {
        // `none` is a real state and not one of the options that question
        // offers; seeding it would have to invent an answer.
        const { seedAnswersFrom } = await import('./SetupIntegrationsPage');
        expect(seedAnswersFrom({ ...azureTown, sms: cap(null, false) }).sms).toBeNull();
    });

    it('reads the cloud from the secret store, falling back to key management', async () => {
        // Neither is "the cloud" as such -- the cloud is wherever the
        // credentials are, and the secret store answers that most directly.
        const { seedAnswersFrom } = await import('./SetupIntegrationsPage');
        expect(seedAnswersFrom({ secrets: cap('aws', true), kms: cap('azure', true) } as any).cloud)
            .toBe('aws');
        expect(seedAnswersFrom({ secrets: cap('database', true), kms: cap('azure', true) } as any).cloud)
            .toBe('azure');
    });

    it('ignores a provider the questionnaire has no option for', async () => {
        // "database" is a real secret-store provider and not a cloud. Seeding
        // it would leave the picker showing nothing selected.
        const { seedAnswersFrom } = await import('./SetupIntegrationsPage');
        expect(seedAnswersFrom({ secrets: cap('database', true) } as any).cloud).toBeNull();
    });

    it('ignores a value the server invented', async () => {
        const { seedAnswersFrom } = await import('./SetupIntegrationsPage');
        expect(seedAnswersFrom({ identity: cap('something-new', true) } as any).idp).toBeNull();
    });
});
