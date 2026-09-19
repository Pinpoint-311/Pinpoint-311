import { describe, it, expect } from 'vitest';

import { forkFor } from './setupSteps';
import type { StepContext } from './setupSteps';
// Registers every provider's walk and every fork as a side effect.
import './setupStepsContent';

/**
 * What the deployment template already did, the steps must not ask for again.
 *
 * The Azure translation walk opened with "press Create a resource and create a
 * Translator resource" for everybody, including an operator who had run the
 * template ten minutes earlier. The template creates one multi-service AI
 * Services account precisely so translation, vision and face share a key, so
 * following the steps produced a second, redundant Translator resource --
 * billed separately, in whatever region got picked, and not the one the
 * template's own `translatorRegion` output names.
 *
 * And on the Key Vault walk, granting the app registration its role was the
 * last clause of a note, conditioned on a form field the reader had filled in
 * days earlier. It is not conditional: the template runs BEFORE the app
 * registration exists, so there is no object id to give it and the template
 * grants nothing. Skipping it leaves a vault, a key and credentials that all
 * authenticate, and a 403 on every wrap.
 */

const CTX = {} as StepContext;

function text(nodes: unknown): string {
    return JSON.stringify(nodes);
}

describe('the template path does not re-ask for what the template made', () => {
    it('offers both paths for Azure translation', () => {
        const fork = forkFor('translation', 'azure', CTX);
        expect(fork).not.toBeNull();
        expect(fork!.template.length).toBeGreaterThan(0);
        expect(fork!.manual.length).toBeGreaterThan(0);
    });

    it('never tells a template user to create a Translator resource', () => {
        const fork = forkFor('translation', 'azure', CTX)!;
        expect(text(fork.template)).not.toMatch(/Create a\s*resource/i);
        // The manual path still must, since there nothing has been created.
        expect(text(fork.manual)).toMatch(/Translator/);
    });

    it('still collects the key and region on both paths', () => {
        const fork = forkFor('translation', 'azure', CTX)!;
        for (const path of [fork.template, fork.manual]) {
            const fields = path.flatMap(s => s.fields ?? []);
            expect(fields).toContain('AZURE_TRANSLATOR_KEY');
            expect(fields).toContain('AZURE_TRANSLATOR_REGION');
        }
    });
});

describe('the Key Vault role grant is a step, not a footnote', () => {
    it('gives the role assignment its own step with its own check', () => {
        const fork = forkFor('kms', 'azure', CTX)!;
        const granting = fork.template.filter(s => text(s.body).includes('Key Vault Crypto User'));

        expect(granting.length).toBe(1);
        // A step, which means it carries its own confirmation.
        expect(granting[0].check).toBeTruthy();
    });

    it('does not present the grant as conditional on a form field', () => {
        const fork = forkFor('kms', 'azure', CTX)!;
        const step = fork.template.find(s => text(s.body).includes('Key Vault Crypto User'))!;

        /* The condition that must be gone is the one on the TEMPLATE FORM
           field. "if you left the three boxes above empty" is a different and
           legitimate branch -- the managed-identity case, pointing at boxes on
           this same page rather than at a value typed into Azure days ago. */
        expect(text(step.body)).not.toMatch(/principal object id/i);
        expect(text(step.body)).not.toMatch(/blank on the form/i);
    });

    it('names which member type to pick, since the wrong one lists nothing usable', () => {
        /* An app registration is a service principal. The Azure blade defaults
           the reader towards "Managed identity", whose list contains the
           identities Azure attached to other resources -- Foundry and the
           Foundry project on this deployment -- and can never contain the app.
           Saying "assign it to the app you just registered" was not enough to
           get past that screen. */
        const fork = forkFor('kms', 'azure', CTX)!;
        const step = fork.template.find(s => text(s.body).includes('Key Vault Crypto User'))!;

        expect(text(step.body)).toMatch(/User, group, or service principal/);
        expect(text(step.body)).toMatch(/Managed identity/);
        // By NAME. Measured in the live portal: pasting the Application
        // (client) ID into that box returns "No results" even though the app
        // exists, so telling the reader to paste it sent them to a dead end.
        expect(text(step.body)).toMatch(/by the name you gave it/);
        expect(text(step.trouble)).toMatch(/No results/);
    });

    it('says what skipping it looks like, since it looks like success', () => {
        const fork = forkFor('kms', 'azure', CTX)!;
        const step = fork.template.find(s => text(s.body).includes('Key Vault Crypto User'))!;

        expect(text(step.trouble)).toMatch(/403/);
    });
});
