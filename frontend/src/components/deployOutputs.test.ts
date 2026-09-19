import { describe, it, expect } from 'vitest';

import { DEPLOY_OUTPUTS, outputsToValues, parseDeployOutputs } from './deployOutputs';

/**
 * The other half of the deploy button.
 *
 * The template ran and the cloud printed seven values; until this existed the
 * operator then found four cards and retyped them. What is tested here is not
 * the parsing for its own sake but the three promises the step makes: nothing
 * is saved that was not shown, an output nothing wanted is reported rather than
 * dropped, and a value the deployment did not produce is named rather than left
 * as an empty box.
 */

const AZURE_PORTAL = JSON.stringify({
    keyVaultUrl: { type: 'String', value: 'https://pinpoint311.vault.azure.net/' },
    keyName: { type: 'String', value: 'pinpoint-pii' },
    directoryTenantId: { type: 'String', value: '00000000-1111-2222-3333-444444444444' },
    azureOpenAiEndpoint: { type: 'String', value: 'https://pp311-openai.openai.azure.com/' },
    azureOpenAiDeploymentName: { type: 'String', value: 'gpt-4o-mini' },
    aiServicesEndpoint: { type: 'String', value: 'https://pp311-ai.cognitiveservices.azure.com/' },
    translatorRegion: { type: 'String', value: 'eastus' },
    readMeFirst: { type: 'String', value: 'Endpoints and names only.' },
});

describe('reading what the deployment gave back', () => {
    it('matches every Azure output to the boxes it fills', () => {
        const parsed = parseDeployOutputs('azure', AZURE_PORTAL);

        expect(parsed.error).toBeNull();
        expect(parsed.matched.map(m => m.output)).toEqual([
            'keyVaultUrl', 'keyName', 'directoryTenantId',
            'azureOpenAiEndpoint', 'azureOpenAiDeploymentName',
            'aiServicesEndpoint', 'translatorRegion',
        ]);
        expect(parsed.absent).toEqual([]);
        // The template's own covering note is not drift.
        expect(parsed.unmatched).toEqual([]);
    });

    it('distributes one endpoint to both boxes that need it', () => {
        const values = outputsToValues(parseDeployOutputs('azure', AZURE_PORTAL).matched);

        expect(values.AZURE_KEYVAULT_URL).toBe('https://pinpoint311.vault.azure.net/');
        expect(values.AZURE_OPENAI_DEPLOYMENT).toBe('gpt-4o-mini');
        // One multi-service account serves Vision and Face both, which is why
        // the template creates one account rather than three.
        expect(values.AZURE_VISION_ENDPOINT).toBe('https://pp311-ai.cognitiveservices.azure.com/');
        expect(values.AZURE_FACE_ENDPOINT).toBe(values.AZURE_VISION_ENDPOINT);
        expect(values.AZURE_TRANSLATOR_REGION).toBe('eastus');
    });

    it('names what this deployment did not create rather than leaving a blank box', () => {
        // A town that ticked only the vault: the AI toggles were off.
        const parsed = parseDeployOutputs('azure', JSON.stringify({
            keyVaultUrl: { value: 'https://v.vault.azure.net/' },
            keyName: { value: 'pinpoint-311-pii' },
            directoryTenantId: { value: '42affcd0-98cd-4c54-8e94-5ae059ac29c7' },
            translatorRegion: { value: 'eastus' },
        }));

        expect(parsed.matched).toHaveLength(4);
        expect(parsed.absent.map(a => a.output)).toEqual([
            'azureOpenAiEndpoint', 'azureOpenAiDeploymentName', 'aiServicesEndpoint',
        ]);
    });

    it('reports an output no box wanted instead of dropping it', () => {
        const parsed = parseDeployOutputs('azure', JSON.stringify({
            keyVaultUrl: { value: 'https://v.vault.azure.net/' },
            somethingNewTheTemplateEmits: { value: 'x' },
        }));

        // Drift between the template and the catalogs is a bug worth surfacing,
        // not a value to swallow.
        expect(parsed.unmatched).toEqual([{ output: 'somethingNewTheTemplateEmits', value: 'x' }]);
    });

    it('reads CloudFormation, from the console and from describe-stacks', () => {
        const fromConsole = JSON.stringify([
            { OutputKey: 'PinpointBoxAwsRegion', OutputValue: 'us-east-2' },
            { OutputKey: 'PinpointBoxKeyIdOrArn', OutputValue: 'abcd-1234' },
            { OutputKey: 'RoleArnToAttach', OutputValue: 'arn:aws:iam::1:role/pp' },
        ]);
        const fromCli = JSON.stringify({
            Stacks: [{ StackName: 'pinpoint-311', Outputs: JSON.parse(fromConsole) }],
        });

        for (const blob of [fromConsole, fromCli]) {
            const parsed = parseDeployOutputs('aws', blob);
            expect(parsed.error).toBeNull();
            expect(outputsToValues(parsed.matched)).toEqual({
                AWS_REGION: 'us-east-2',
                AWS_KMS_KEY_ID: 'abcd-1234',
            });
            // The role ARN is for the operator, not for a box, and saying "no
            // box for this" about it on every paste would train them to ignore
            // the line that means something.
            expect(parsed.unmatched).toEqual([]);
        }
    });

    it('accepts a plain name-to-value object typed by hand', () => {
        const parsed = parseDeployOutputs('aws', '{"PinpointBoxAwsRegion": "eu-west-1"}');
        expect(outputsToValues(parsed.matched)).toEqual({ AWS_REGION: 'eu-west-1' });
    });

    it('does not fail a correct paste on a capital letter', () => {
        const parsed = parseDeployOutputs('azure', '{"KeyVaultUrl": {"value": "https://v/"}}');
        expect(outputsToValues(parsed.matched)).toEqual({ AZURE_KEYVAULT_URL: 'https://v/' });
    });

    it('says what is wrong rather than half-reading it', () => {
        /* The error no longer says "that is not JSON", and must not: JSON is
           one accepted shape of several, and the Azure portal's Outputs tab
           offers none. Telling a reader to go and find a blob that screen does
           not have is the advice this whole path had to stop giving. What is
           asserted is the property -- a clear error, and nothing half-read --
           rather than a sentence that has since become untrue. */
        const garbage = parseDeployOutputs('azure', 'not json at all');
        expect(garbage.error).toBeTruthy();
        expect(garbage.error).not.toContain('not JSON');
        expect(garbage.matched).toEqual([]);
        expect(parseDeployOutputs('azure', '{"deployment": "succeeded"}').error).toContain('Outputs');
        // Nothing typed yet is not an error.
        expect(parseDeployOutputs('azure', '   ').error).toBeNull();
    });
});

describe('what the outputs deliberately do not include', () => {
    it('names every key still to be copied by hand, and where it lives', () => {
        const azure = DEPLOY_OUTPUTS.azure;
        const stillManual = azure.manual.map(m => m.key);

        // Both templates emit no secret, so these cannot arrive in a paste.
        expect(stillManual).toContain('AZURE_OPENAI_API_KEY');
        expect(stillManual).toContain('AZURE_TRANSLATOR_KEY');
        expect(stillManual).toContain('AZURE_VISION_KEY');
        expect(stillManual).toContain('AZURE_FACE_KEY');
        expect(stillManual).toContain('AZURE_KEYVAULT_CLIENT_SECRET');
        for (const m of azure.manual) expect(m.where.length).toBeGreaterThan(0);
    });

    it('claims nothing outstanding on AWS, because the stack creates no key', () => {
        expect(DEPLOY_OUTPUTS.aws.manual).toEqual([]);
    });

    it('never lists a credential as both pasteable and hand-copied', () => {
        for (const spec of Object.values(DEPLOY_OUTPUTS)) {
            const pasted = new Set(spec.mappings.flatMap(m => m.keys));
            for (const m of spec.manual) expect(pasted.has(m.key)).toBe(false);
        }
    });
});

describe('the portal Outputs tab, copied as it appears', () => {
    /* Verbatim from an operator's own deployment, stacked exactly as the Azure
     * portal renders it: one line for the name, the next for the value, and no
     * JSON anywhere on that screen to copy instead. This shape used to answer
     * "That is not JSON", which was both the only thing they could paste and
     * the only thing rejected. */
    const PORTAL_PASTE = `readMeFirst
Endpoints and names only. No key is emitted here on purpose: deployment outputs are kept in this resource group's deployment history and can be read by anyone with access to it.
keyVaultUrl
https://pp311-kv-3b7eeuxuhnsby.vault.azure.net/
keyName
pinpoint-311-pii
directoryTenantId
42affcd0-98cd-4c54-8e94-5ae059ac29c7
translatorRegion
eastus`;

    it('reads the values a real deployment printed', () => {
        const parsed = parseDeployOutputs('azure', PORTAL_PASTE);
        expect(parsed.error).toBeNull();
        const values = outputsToValues(parsed.matched);
        expect(values.AZURE_KEYVAULT_URL).toBe('https://pp311-kv-3b7eeuxuhnsby.vault.azure.net/');
        expect(values.AZURE_KEYVAULT_KEY).toBe('pinpoint-311-pii');
        expect(values.AZURE_TENANT_ID).toBe('42affcd0-98cd-4c54-8e94-5ae059ac29c7');
        expect(values.AZURE_TRANSLATOR_REGION).toBe('eastus');
    });

    it('does not read a bare value as the name of the next one', () => {
        /* `eastus` is shaped exactly like an output name. Pairing by shape
         * rather than against the names this cloud declares would take it as a
         * key and drop the region. */
        const parsed = parseDeployOutputs('azure', PORTAL_PASTE);
        expect(parsed.unmatched.map(u => u.output)).not.toContain('eastus');
    });

    it('keeps a wrapped prose value in one piece and still ignores it', () => {
        const parsed = parseDeployOutputs('azure', PORTAL_PASTE);
        expect(parsed.unmatched.map(u => u.output.toLowerCase())).not.toContain('readmefirst');
    });

    it('reads name: value on one line too', () => {
        const parsed = parseDeployOutputs('azure',
            'keyVaultUrl: https://x.vault.azure.net/\nkeyName = pinpoint-311-pii');
        const values = outputsToValues(parsed.matched);
        expect(values.AZURE_KEYVAULT_URL).toBe('https://x.vault.azure.net/');
        expect(values.AZURE_KEYVAULT_KEY).toBe('pinpoint-311-pii');
    });

    it('still says so when the paste is from the wrong screen', () => {
        const parsed = parseDeployOutputs('azure', 'Succeeded\nEast US\n2 minutes ago');
        expect(parsed.error).toBeTruthy();
        expect(parsed.matched).toHaveLength(0);
    });
});

describe('a deployment that created no model', () => {
    /* Verbatim from the deployment that followed unpinning the model name. The
     * template creates the OpenAI account and no deployment, so Azure emits
     * `azureOpenAiDeploymentName` with nothing after it -- a name line followed
     * immediately by the next name line. The paste must read the six values that
     * are there, report the one that is not as still needed, and not save an
     * empty string over anything. */
    const REAL_PASTE = `readMeFirst
Endpoints and names only. No key is emitted here on purpose.
keyVaultUrl
https://pp311-kv-3b7eeuxuhnsby.vault.azure.net/
keyName
pinpoint-311-pii
directoryTenantId
42affcd0-98cd-4c54-8e94-5ae059ac29c7
azureOpenAiEndpoint
https://pinpoint311-openai-3b7eeuxuhnsby.openai.azure.com/
azureOpenAiDeploymentName
aiServicesEndpoint
https://pinpoint311-ai-3b7eeuxuhnsby.cognitiveservices.azure.com/
translatorRegion
eastus`;

    it('reads every value that is there', () => {
        const parsed = parseDeployOutputs('azure', REAL_PASTE);
        expect(parsed.error).toBeNull();
        const values = outputsToValues(parsed.matched);
        expect(values.AZURE_KEYVAULT_URL).toBe('https://pp311-kv-3b7eeuxuhnsby.vault.azure.net/');
        expect(values.AZURE_KEYVAULT_KEY).toBe('pinpoint-311-pii');
        expect(values.AZURE_TENANT_ID).toBe('42affcd0-98cd-4c54-8e94-5ae059ac29c7');
        expect(values.AZURE_OPENAI_ENDPOINT).toBe('https://pinpoint311-openai-3b7eeuxuhnsby.openai.azure.com/');
        expect(values.AZURE_VISION_ENDPOINT).toBe('https://pinpoint311-ai-3b7eeuxuhnsby.cognitiveservices.azure.com/');
        expect(values.AZURE_FACE_ENDPOINT).toBe(values.AZURE_VISION_ENDPOINT);
        expect(values.AZURE_TRANSLATOR_REGION).toBe('eastus');
    });

    it('does not save an empty deployment name over anything', () => {
        const parsed = parseDeployOutputs('azure', REAL_PASTE);
        const values = outputsToValues(parsed.matched);
        expect(values.AZURE_OPENAI_DEPLOYMENT).toBeUndefined();
        expect(parsed.absent.map(a => a.output)).toContain('azureOpenAiDeploymentName');
    });

    it('does not read the next output name as the missing value', () => {
        /* `azureOpenAiDeploymentName` is followed immediately by
         * `aiServicesEndpoint`. Pairing by position would take that name as the
         * value and then lose the endpoint entirely. */
        const parsed = parseDeployOutputs('azure', REAL_PASTE);
        const values = outputsToValues(parsed.matched);
        expect(values.AZURE_VISION_ENDPOINT).toContain('cognitiveservices.azure.com');
    });
});

describe('an output that is declared but empty', () => {
    it('is reported once, as missing, and never as drift', () => {
        /* It was reported twice on the same paste: "Deployment name -- not in
         * this deployment" in the missing list AND "azureOpenAiDeploymentName --
         * no box for this, worth reporting" in the drift list. The drift list is
         * for outputs the catalogs have never heard of; an empty value is one
         * both halves know about. Reporting it there cries wolf on every town
         * that has not chosen a model, which is now all of them by default. */
        const parsed = parseDeployOutputs('azure',
            'keyVaultUrl\nhttps://v/\nazureOpenAiDeploymentName\ntranslatorRegion\neastus');
        expect(parsed.absent.map(a => a.output)).toContain('azureOpenAiDeploymentName');
        expect(parsed.unmatched.map(u => u.output)).not.toContain('azureOpenAiDeploymentName');
    });

    it('still reports an output nothing recognises', () => {
        const parsed = parseDeployOutputs('azure',
            '{"keyVaultUrl": {"value": "https://v/"}, "somethingNew": {"value": "x"}}');
        expect(parsed.unmatched.map(u => u.output)).toContain('somethingNew');
    });
});

describe('the result panel pasted back into the box', () => {
    /* An easy mistake, because the result renders directly beneath the box. It
     * used to match `azureOpenAiDeploymentName` against the words "no box for
     * this — worth reporting" and offer to save them as the deployment name --
     * a credential made of this page's own prose. */
    const PANEL = `Key Vault URL
https://pp311-kv-3b7eeuxuhnsby.vault.azure.net/
Key name
pinpoint-311-pii
Deployment name
not in this deployment
azureOpenAiDeploymentName
no box for this — worth reporting`;

    it('refuses a value that cannot be what it claims', () => {
        const parsed = parseDeployOutputs('azure', PANEL);
        const values = outputsToValues(parsed.matched);
        expect(values.AZURE_OPENAI_DEPLOYMENT).toBeUndefined();
    });

    it('says which value it ignored, rather than going quiet', () => {
        const parsed = parseDeployOutputs('azure', PANEL);
        expect(parsed.error).toBeTruthy();
        expect(parsed.error).toContain('Deployment name');
    });

    it('still accepts a real deployment name', () => {
        const parsed = parseDeployOutputs('azure',
            'azureOpenAiDeploymentName\npinpoint-311-chat');
        expect(outputsToValues(parsed.matched).AZURE_OPENAI_DEPLOYMENT)
            .toBe('pinpoint-311-chat');
        expect(parsed.error).toBeNull();
    });

    it('still accepts every value from a real deployment', () => {
        const parsed = parseDeployOutputs('azure', `keyVaultUrl
https://pp311-kv-3b7eeuxuhnsby.vault.azure.net/
directoryTenantId
42affcd0-98cd-4c54-8e94-5ae059ac29c7
aiServicesEndpoint
https://pinpoint311-ai-3b7eeuxuhnsby.cognitiveservices.azure.com/
translatorRegion
eastus`);
        expect(parsed.error).toBeNull();
        expect(parsed.matched).toHaveLength(4);
    });
});
