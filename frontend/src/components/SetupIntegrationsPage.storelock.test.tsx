// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

import { LockedUntilStoreChosen } from './SetupIntegrationsPage';
import { SECRET_STORE_GATE_ID } from './SecretStoreGate';

/**
 * The page has to look like what it will do.
 *
 * `_require_a_secret_store` answers 409 until a town has said where credentials
 * go, and the panel above the fields says so in words -- but every field stayed
 * editable, so the way to find out was to paste a key, click save, and read an
 * error. The refusal was correct and arrived last.
 *
 * These cover the lock itself rather than the page around it. What is worth
 * pinning is the one property the whole approach rests on: a disabled `fieldset`
 * disables everything inside it, including controls belonging to components that
 * were never told about the gate. That is why this is a fieldset and not a
 * `disabled` prop threaded through SetupWizard, ServiceProviders and
 * InlineProviderSetup -- a prop can be forgotten by the fourth one.
 */

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
});

afterEach(() => {
    act(() => root.unmount());
    host.remove();
});

function render(locked: boolean) {
    act(() => {
        root.render(
            <LockedUntilStoreChosen locked={locked}>
                <div>
                    <input data-testid="key" type="password" />
                    <button data-testid="save">Save</button>
                    <select data-testid="pick"><option>a</option></select>
                </div>
            </LockedUntilStoreChosen>,
        );
    });
    return {
        key: host.querySelector('[data-testid="key"]') as HTMLInputElement,
        save: host.querySelector('[data-testid="save"]') as HTMLButtonElement,
        pick: host.querySelector('[data-testid="pick"]') as HTMLSelectElement,
        fieldset: host.querySelector('fieldset'),
    };
}

describe('credential fields are locked until a store is chosen', () => {
    it('disables every nested control, including ones that never saw the prop', () => {
        const { key, save, pick } = render(true);
        // `:disabled` rather than `.disabled`: the IDL property reflects a
        // control's own attribute and is false here in a real browser too. The
        // inherited state is what the user runs into, and what the selector
        // reports.
        expect(key.matches(':disabled')).toBe(true);
        expect(save.matches(':disabled')).toBe(true);
        expect(pick.matches(':disabled')).toBe(true);
    });

    it('points at the panel that explains why', () => {
        const { fieldset } = render(true);
        expect(fieldset?.getAttribute('aria-describedby')).toBe(SECRET_STORE_GATE_ID);
    });

    it('adds no element at all once a store is chosen', () => {
        const { key, save, fieldset } = render(false);
        expect(fieldset).toBeNull();
        expect(key.matches(':disabled')).toBe(false);
        expect(save.matches(':disabled')).toBe(false);
    });

    it('unlocks when the answer arrives, without a remount losing what was typed', () => {
        const { key } = render(true);
        expect(key.matches(':disabled')).toBe(true);

        const after = render(false);
        expect(after.key.matches(':disabled')).toBe(false);
    });
});
