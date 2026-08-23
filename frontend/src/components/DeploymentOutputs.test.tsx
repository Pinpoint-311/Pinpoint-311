// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import DeploymentOutputs from './DeploymentOutputs';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * The paste-back step, mounted.
 *
 * The parser has its own tests; what is checked here is the part that was
 * actually broken the first time it was written. `handleSave` on the page reads
 * the value out of React state, and setting state and then saving in the same
 * tick saves nothing at all -- a green button, seven empty boxes, and no error
 * anywhere. So the assertion that matters is that the VALUES arrive at the
 * save, not merely that the save was called.
 */

const OUTPUTS = JSON.stringify({
    keyVaultUrl: { value: 'https://pinpoint311.vault.azure.net/' },
    keyName: { value: 'pinpoint-pii' },
    directoryTenantId: { value: 'tenant-1' },
    translatorRegion: { value: 'eastus' },
});

let container: HTMLDivElement;
let root: Root;

function mount(node: React.ReactElement) {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => { root.render(node); });
}

function type(text: string) {
    const box = container.querySelector('textarea')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    act(() => {
        setter.call(box, text);
        box.dispatchEvent(new Event('input', { bubbles: true }));
    });
}

function saveButton(): HTMLButtonElement {
    return [...container.querySelectorAll('button')]
        .find(b => /Fill in/.test(b.textContent || ''))!;
}

afterEach(() => {
    act(() => { root.unmount(); });
    container.remove();
});

describe('pasting what the deployment gave back', () => {
    let onSave: ReturnType<typeof vi.fn>;
    let changed: Record<string, string>;

    beforeEach(() => {
        onSave = vi.fn().mockResolvedValue(undefined);
        changed = {};
        mount(
            <DeploymentOutputs
                cloud="azure" values={{}}
                onChange={(k, v) => { changed[k] = v; }}
                onSave={onSave as any} saving={false}
                isConfigured={() => false}
            />,
        );
    });

    it('saves nothing until the operator has seen what matched', () => {
        expect(saveButton().disabled).toBe(true);
        expect(onSave).not.toHaveBeenCalled();

        type(OUTPUTS);

        // Every value on screen, with its own value, before the button works.
        const rows = container.querySelectorAll('[data-output-status="matched"]');
        expect(rows.length).toBe(4);
        expect(container.textContent).toContain('https://pinpoint311.vault.azure.net/');
        expect(saveButton().disabled).toBe(false);
        expect(onSave).not.toHaveBeenCalled();
    });

    it('hands the save the values, not just the keys', async () => {
        type(OUTPUTS);
        await act(async () => { saveButton().click(); });

        expect(onSave).toHaveBeenCalledTimes(1);
        expect(onSave.mock.calls[0][0]).toEqual({
            AZURE_KEYVAULT_URL: 'https://pinpoint311.vault.azure.net/',
            AZURE_KEYVAULT_KEY: 'pinpoint-pii',
            AZURE_TENANT_ID: 'tenant-1',
            AZURE_TRANSLATOR_REGION: 'eastus',
        });
        // And into the boxes, so the cards show what landed.
        expect(changed.AZURE_KEYVAULT_URL).toBe('https://pinpoint311.vault.azure.net/');
    });

    it('says what this deployment did not produce', () => {
        type(OUTPUTS);
        const absent = [...container.querySelectorAll('[data-output-status="absent"]')]
            .map(el => (el as HTMLElement).dataset.output);
        expect(absent).toContain('azureOpenAiEndpoint');
        expect(absent).toContain('aiServicesEndpoint');
    });

    it('surfaces an output no box wanted rather than dropping it', () => {
        type('{"keyVaultUrl": {"value": "https://v/"}, "brandNewThing": {"value": "x"}}');
        const drift = container.querySelector('[data-output-status="unmatched"]');
        expect(drift).toBeTruthy();
        expect((drift as HTMLElement).dataset.output).toBe('brandNewThing');
    });

    it('names the keys that are still a human job, and where each one lives', () => {
        const listed = [...container.querySelectorAll('[data-manual-credential]')]
            .map(el => (el as HTMLElement).dataset.manualCredential);

        expect(listed).toContain('AZURE_OPENAI_API_KEY');
        expect(listed).toContain('AZURE_KEYVAULT_CLIENT_SECRET');
        expect(container.textContent).toContain('Keys are not in the outputs');
        expect(container.textContent).toContain('Keys and Endpoint');
    });

    it('reports a bad paste in a way the box points at', () => {
        type('paste of the wrong screen');
        const box = container.querySelector('textarea')!;
        const describedBy = box.getAttribute('aria-describedby');
        expect(box.getAttribute('aria-invalid')).toBe('true');
        expect(describedBy).toBeTruthy();
        expect(document.getElementById(describedBy!)!.textContent).toContain('not JSON');
        expect(saveButton().disabled).toBe(true);
    });
});

describe('AWS, where the stack creates no key', () => {
    it('lists nothing outstanding', () => {
        mount(
            <DeploymentOutputs
                cloud="aws" values={{}} onChange={() => {}}
                onSave={async () => {}} saving={false} isConfigured={() => false}
            />,
        );
        expect(container.querySelector('[data-manual-credential]')).toBeNull();
        expect(container.textContent).not.toContain('Keys are not in the outputs');
    });
});
