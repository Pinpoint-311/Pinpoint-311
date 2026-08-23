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
            keyName: { value: 'k' },
            directoryTenantId: { value: 't' },
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
        expect(parseDeployOutputs('azure', 'not json at all').error).toContain('not JSON');
        expect(parseDeployOutputs('azure', 'not json at all').matched).toEqual([]);
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
