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
    // A real tenant id, because the parser now checks the shape of one.
    directoryTenantId: { value: '42affcd0-98cd-4c54-8e94-5ae059ac29c7' },
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
            AZURE_TENANT_ID: '42affcd0-98cd-4c54-8e94-5ae059ac29c7',
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
        /* The wording, not the wiring, is what changed here: JSON is one
           accepted shape of several now, so the message names the screen to
           copy from instead of a format. What this test is for is that the
           complaint is REACHABLE from the box -- aria-describedby resolving to
           the text -- which is unaffected. */
        const message = document.getElementById(describedBy!)!.textContent!;
        expect(message).toContain('Outputs');
        expect(message).not.toContain('not JSON');
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

describe('a paste that has already landed', () => {
    /* The values live in the vault, but the textarea and the "Saved" line were
     * component state. A reload put the first-run face back up -- empty box,
     * disabled button, nothing to say the deployment had ever been pasted --
     * and the operator's only reasonable reading was that it had not worked. */

    const AZURE_LANDED = ['AZURE_KEYVAULT_URL', 'AZURE_KEYVAULT_KEY'];

    function mountWithConfigured(keys: string[]) {
        mount(
            <DeploymentOutputs
                cloud="azure" values={{}}
                onChange={() => {}}
                onSave={(async () => {}) as any} saving={false}
                isConfigured={(k) => keys.includes(k)}
            />,
        );
    }

    it('does not ask again for outputs that are already stored', () => {
        mountWithConfigured(AZURE_LANDED);

        expect(container.querySelector('textarea')).toBeNull();
        expect(container.querySelector('[data-testid="deployment-outputs-landed"]')).not.toBeNull();
    });

    it('names which outputs are in place', () => {
        mountWithConfigured(AZURE_LANDED);

        const landed = [...container.querySelectorAll('[data-output-status="landed"]')]
            .map(el => el.getAttribute('data-output'));
        expect(landed).toContain('keyVaultUrl');
        expect(landed).toContain('keyName');
        // Not pasted, so not claimed.
        expect(landed).not.toContain('azureOpenAiEndpoint');
    });

    it('does not print the stored values back onto the page', () => {
        mountWithConfigured(AZURE_LANDED);
        expect(container.textContent).not.toContain('vault.azure.net');
    });

    it('still offers the box to whoever wants to paste a new deployment', () => {
        mountWithConfigured(AZURE_LANDED);

        const again = [...container.querySelectorAll('button')]
            .find(b => /Paste again/.test(b.textContent || ''))!;
        expect(again).toBeTruthy();
        act(() => { again.dispatchEvent(new MouseEvent('click', { bubbles: true })); });

        expect(container.querySelector('textarea')).not.toBeNull();
    });

    it('shows the first-run box when nothing has landed yet', () => {
        mountWithConfigured([]);
        expect(container.querySelector('textarea')).not.toBeNull();
        expect(container.querySelector('[data-testid="deployment-outputs-landed"]')).toBeNull();
    });

    it('accepts the paste immediately, without waiting for the parent to refetch', async () => {
        /* The parent refresh is a round trip. Leaving the first-run face up
         * until it lands is the same bug, only briefer. */
        let onSave: any;
        onSave = vi.fn().mockResolvedValue(undefined);
        mount(
            <DeploymentOutputs
                cloud="azure" values={{}}
                onChange={() => {}}
                onSave={onSave} saving={false}
                isConfigured={() => false}
            />,
        );

        type(OUTPUTS);
        await act(async () => {
            saveButton().dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });

        expect(container.querySelector('[data-testid="deployment-outputs-landed"]')).not.toBeNull();
    });
});
