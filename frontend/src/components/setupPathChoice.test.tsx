// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

import ProviderCredentialSteps from './ProviderCredentialSteps';
import { writePathChoice } from './setupSteps';
import type { StepContext } from './setupSteps';
// Registers every provider's walk, and the two clouds' forks, as a side effect.
import './setupStepsContent';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * The fork is a real choice, and only one side of it is ever on screen.
 *
 * What this is guarding is a regression that was invisible from the source: the
 * two paths were both present, both correct, and rendered one after the other
 * as steps 1 and 2 of the same list -- so the owner looked at the live page and
 * could not find the feature at all. Every assertion here is about what a
 * reader can see and reach, because that was the whole failure.
 */

const ctx: StepContext = { origin: 'https://311.example.gov', copy: () => {}, copied: null };

const AZURE_KMS = {
    provider: 'azure',
    name: 'Azure Key Vault',
    credential_fields: [
        { key: 'AZURE_KEYVAULT_URL', label: 'Key Vault URL', secret: false },
        { key: 'AZURE_KEYVAULT_KEY', label: 'Key name', secret: false },
        { key: 'AZURE_TENANT_ID', label: 'Directory (tenant) ID', secret: false },
        { key: 'AZURE_KEYVAULT_CLIENT_ID', label: 'Application (client) ID', secret: false },
        { key: 'AZURE_KEYVAULT_CLIENT_SECRET', label: 'Client secret', secret: true },
    ],
} as any;

const GOOGLE_KMS = {
    provider: 'google',
    name: 'Google Cloud KMS',
    credential_fields: [
        { key: 'KMS_LOCATION', label: 'Location', secret: false },
        { key: 'KMS_KEY_RING', label: 'Key ring', secret: false },
        { key: 'KMS_KEY_ID', label: 'Key', secret: false },
    ],
} as any;

let container: HTMLDivElement;
let root: Root;

function mount(node: React.ReactElement) {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    act(() => { root.render(node); });
}

function azureCard() {
    return (
        <ProviderCredentialSteps
            cap="kms" provider="azure" active={AZURE_KMS}
            values={{}} onChange={() => {}} ctx={ctx}
        />
    );
}

/** The numbered circles the card draws to the left of each step. */
function stepNumbers(): string[] {
    return [...container.querySelectorAll('span')]
        .map(el => el.textContent || '')
        .filter(t => /^\d+$/.test(t));
}

function button(selector: string): HTMLButtonElement {
    const el = container.querySelector<HTMLButtonElement>(selector);
    if (!el) throw new Error(`no element matching ${selector}`);
    return el;
}

beforeEach(() => {
    window.localStorage.clear();
});

afterEach(() => {
    act(() => { root.unmount(); });
    container.remove();
    window.localStorage.clear();
});

describe('the fork, before anything is chosen', () => {
    it('offers both paths and renders neither walk', () => {
        mount(azureCard());

        expect(container.querySelector('[data-testid="setup-path-choice"]')).toBeTruthy();
        expect(button('[data-setup-path="template"]').textContent).toContain('Deploy with the Azure template');
        expect(button('[data-setup-path="manual"]').textContent).toContain('Set it up by hand');

        // Nothing numbered: no step from either path is on screen.
        expect(stepNumbers()).toEqual([]);
        // And in particular neither path's opening line.
        expect(container.textContent).not.toContain('Custom deployment form');
        expect(container.textContent).not.toContain('Access configuration');
    });

    it('does not dump the credential boxes under the two buttons', () => {
        mount(azureCard());
        // Both paths claim these fields, so "no step claimed it" must not fire.
        expect(container.querySelectorAll('input').length).toBe(0);
    });

    it('marks which action is primary in the markup, not only in the colour', () => {
        mount(azureCard());
        expect(button('[data-setup-path="template"]').dataset.emphasis).toBe('primary');
        expect(button('[data-setup-path="manual"]').dataset.emphasis).toBe('secondary');
    });

    it('puts the trust copy behind the action rather than in front of it', () => {
        mount(azureCard());
        const details = container.querySelector('[data-testid="setup-path-trust"]');
        expect(details).toBeTruthy();
        // Every word of it is still here, just not in the way.
        expect(details!.textContent).toContain('It runs in');
        expect(details!.textContent).toContain('scoped to');
        // Closed by default: the reader sees the action first.
        expect((details as HTMLDetailsElement).open).toBe(false);

        const choice = container.querySelector('[data-testid="setup-path-choice"]')!;
        const html = choice.innerHTML;
        expect(html.indexOf('data-setup-path="template"')).toBeLessThan(html.indexOf('setup-path-trust'));
    });

    it('is operable from the keyboard, with real key events', () => {
        mount(azureCard());
        const primary = button('[data-setup-path="template"]');

        // A real button: focusable, and Enter activates it without a click.
        act(() => { primary.focus(); });
        expect(document.activeElement).toBe(primary);
        expect(primary.tagName).toBe('BUTTON');

        act(() => {
            primary.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
            // jsdom does not synthesise the click a real browser fires for
            // Enter on a button, so the activation itself is dispatched here.
            // What the test is proving is that the element's own semantics do
            // the work -- there is no key handler of ours in the way.
            primary.dispatchEvent(new MouseEvent('click', { bubbles: true }));
        });

        expect(container.querySelector('[data-testid="setup-path-choice"]')).toBeNull();
        expect(container.querySelector('[data-setup-path-active="template"]')).toBeTruthy();
    });
});

describe('choosing a path', () => {
    it('shows the template walk and none of the by-hand screens', () => {
        mount(azureCard());
        act(() => { button('[data-setup-path="template"]').click(); });

        expect(container.textContent).toContain('Custom deployment form');
        expect(container.querySelector('a[href*="portal.azure.com/#create"]')).toBeTruthy();
        // The by-hand walk's own screens are absent.
        expect(container.textContent).not.toContain('Access configuration');
        expect(container.textContent).not.toContain('Key Vault Crypto Officer');
    });

    it('shows the complete by-hand walk, numbered from 1, with no deploy button', () => {
        mount(azureCard());
        act(() => { button('[data-setup-path="manual"]').click(); });

        const numbers = stepNumbers();
        expect(numbers[0]).toBe('1');
        expect(numbers).toEqual(numbers.map((_, i) => String(i + 1)));
        expect(numbers.length).toBeGreaterThanOrEqual(9);

        // The screens that were missing before, still here.
        expect(container.textContent).toContain('Access configuration');
        expect(container.textContent).toContain('Key Vault Crypto Officer');
        expect(container.textContent).toContain('Key Vault Crypto User');
        // Nothing telling them to press a button they have declined.
        expect(container.querySelector('a[href*="portal.azure.com/#create"]')).toBeNull();
        expect(container.textContent).not.toContain('Custom deployment form');
    });

    it('moves focus to the walk that appeared, without adding a live region', () => {
        mount(azureCard());
        const before = container.querySelectorAll('[aria-live]').length;

        act(() => { button('[data-setup-path="manual"]').click(); });

        const heading = container.querySelector('[data-testid="setup-path-banner"] h4')!;
        expect(document.activeElement).toBe(heading);
        expect(heading.textContent).toContain('Set it up by hand');
        // A heading takes focus programmatically and stays out of the tab order.
        expect(heading.getAttribute('tabindex')).toBe('-1');
        expect(container.querySelectorAll('[aria-live]').length).toBe(before);
    });
});

describe('changing your mind', () => {
    it('offers a visible way to the other path and takes it', () => {
        mount(azureCard());
        act(() => { button('[data-setup-path="template"]').click(); });

        const back = button('[data-setup-path-switch="manual"]');
        expect(back.textContent).toContain('Set it up by hand instead');

        act(() => { back.click(); });
        expect(container.querySelector('[data-setup-path-active="manual"]')).toBeTruthy();
        expect(container.textContent).toContain('Access configuration');

        // And back again, from the other side.
        act(() => { button('[data-setup-path-switch="template"]').click(); });
        expect(container.querySelector('[data-setup-path-active="template"]')).toBeTruthy();
    });

    it('leaves anything already typed alone', () => {
        const values: Record<string, string> = { AZURE_KEYVAULT_URL: 'https://v.vault.azure.net/' };
        mount(
            <ProviderCredentialSteps
                cap="kms" provider="azure" active={AZURE_KMS}
                values={values} onChange={(k, v) => { values[k] = v; }} ctx={ctx}
            />,
        );
        act(() => { button('[data-setup-path="manual"]').click(); });
        act(() => { button('[data-setup-path-switch="template"]').click(); });

        expect(values).toEqual({ AZURE_KEYVAULT_URL: 'https://v.vault.azure.net/' });
        const filled = [...container.querySelectorAll('input')]
            .some(i => (i as HTMLInputElement).value === 'https://v.vault.azure.net/');
        expect(filled).toBe(true);
    });
});

describe('remembering the choice', () => {
    it('does not ask again on the next visit', () => {
        mount(azureCard());
        act(() => { button('[data-setup-path="template"]').click(); });
        act(() => { root.unmount(); });
        container.remove();

        // A fresh mount, as a reload would be: same browser, same storage.
        mount(azureCard());
        expect(container.querySelector('[data-testid="setup-path-choice"]')).toBeNull();
        expect(container.querySelector('[data-setup-path-active="template"]')).toBeTruthy();
    });

    it('does not steal focus when it is only remembering', () => {
        writePathChoice('azure', 'manual');
        const outside = document.createElement('button');
        document.body.appendChild(outside);
        outside.focus();

        mount(azureCard());
        expect(document.activeElement).toBe(outside);
        outside.remove();
    });

    it('stores it per cloud, not per capability, and never in system settings', () => {
        mount(azureCard());
        act(() => { button('[data-setup-path="template"]').click(); });

        expect(window.localStorage.getItem('pinpoint.setupPath.azure')).toBe('template');
        // One answer for the whole cloud: the AI and Translation cards on Azure
        // are set up by the same deployment, so they must not ask again.
        const keys = Object.keys(window.localStorage);
        expect(keys).toEqual(['pinpoint.setupPath.azure']);
        expect(window.localStorage.getItem('pinpoint.setupPath.aws')).toBeNull();
    });
});

describe('Google, which has no template', () => {
    it('renders the walk directly, with no fork and no disabled button', () => {
        mount(
            <ProviderCredentialSteps
                cap="kms" provider="google" active={GOOGLE_KMS}
                values={{}} onChange={() => {}} ctx={ctx}
            />,
        );

        expect(container.querySelector('[data-testid="setup-path-choice"]')).toBeNull();
        expect(container.querySelector('[data-testid="setup-path-banner"]')).toBeNull();
        expect(container.querySelector('[data-setup-path]')).toBeNull();
        expect(stepNumbers()[0]).toBe('1');
        expect(container.textContent).toContain('Key Management');
        // The one line saying why, as a statement rather than an apology.
        expect(container.textContent).toContain('Google has none');
    });
});

describe('a step whose boxes are already filled', () => {
    /* The reader's remaining job should not sit below a screen of instructions
     * they have already carried out. What is asserted is that finished work
     * folds and unfinished work does not -- and that folding never means
     * losing: the values stay reachable, because a saved credential is one
     * somebody may need to change. */
    const FILLED = { AZURE_KEYVAULT_URL: true, AZURE_KEYVAULT_KEY: true };

    const cardWith = (storedFields: Record<string, boolean>) => (
        <ProviderCredentialSteps
            cap="kms" provider="azure" active={AZURE_KMS}
            values={{}} onChange={() => {}} ctx={ctx}
            storedFields={storedFields}
        />
    );

    const folded = () => container.querySelectorAll('details[data-testid^="setup-step-done-"]');

    beforeEach(() => { writePathChoice('azure', 'template'); });

    it('folds the finished step and leaves the outstanding one open', () => {
        mount(cardWith(FILLED));
        expect(folded().length).toBe(1);
        expect(folded()[0].textContent).toContain('Done');
        // The step still wanting the Entra credential is not folded away.
        expect(container.textContent).toContain('How this server opens the vault');
    });

    it('keeps a saved value reachable rather than hiding it', () => {
        mount(cardWith(FILLED));
        expect(folded()[0].querySelector('summary')!.textContent).toContain('Change');
        expect(folded()[0].querySelectorAll('input').length).toBeGreaterThan(0);
    });

    it('folds nothing when nothing has been saved', () => {
        mount(cardWith({}));
        expect(folded().length).toBe(0);
    });
});
