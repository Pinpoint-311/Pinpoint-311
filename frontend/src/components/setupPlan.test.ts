import { describe, it, expect } from 'vitest';

import { buildPlan, type PlanInput } from './setupPlan';

/**
 * One trip per login, and the required things first.
 *
 * The grouping is the whole point of this rewrite, and it is the part most
 * likely to quietly stop working: add a capability, forget to give it a vendor,
 * and it lands in its own task. Nothing breaks, no test fails, and a town on
 * Azure is back to bouncing between four portals.
 */

const base: PlanInput = {
    cloud: 'azure',
    idp: 'entra',
    maps: 'azure',
    aiProvider: 'azure',
    emailProvider: 'acs',
    smsProvider: 'acs',
    redactionProvider: 'azure',
    wanted: new Set(['ai', 'translation', 'safety', 'email', 'sms', 'secrets', 'backups', 'errors']),
};

const plan = (over: Partial<PlanInput> = {}) => buildPlan({ ...base, ...over });
const ids = (over: Partial<PlanInput> = {}) => plan(over).map(t => t.id);
const task = (id: string, over: Partial<PlanInput> = {}) => plan(over).find(t => t.id === id);

describe('everything behind one login is one task', () => {
    it('folds an all-Azure town into a single Azure task', () => {
        const azure = task('azure')!;
        const items = azure.items.map(i => i.id).sort();
        // Sign-in via Entra, maps, AI, translation, Key Vault, screening, email
        // and text are all the Azure portal. Eight sections became one visit.
        expect(items).toEqual(['ai', 'email', 'identity', 'kms', 'maps', 'safety', 'sms', 'translation']);
        expect(azure.foundation).toBe('azure');
    });

    it('does not fold things that are genuinely a different login', () => {
        // Same town, but Google Maps and Auth0. Those are two more sign-ins and
        // pretending otherwise would promise one trip and need three.
        const list = ids({ idp: 'auth0', maps: 'google' });
        expect(list).toContain('auth0');
        expect(list).toContain('google');
        expect(list).toContain('azure');
        expect(task('google', { idp: 'auth0', maps: 'google' })!.items.map(i => i.id)).toEqual(['maps']);
    });

    it('treats Entra as Azure, because it is administered in the Azure portal', () => {
        expect(task('azure')!.items.map(i => i.id)).toContain('identity');
        // Okta is not, so it stays its own task.
        expect(task('okta', { idp: 'okta' })!.items.map(i => i.id)).toEqual(['identity']);
    });

    it('only the clouds get the account-setup walk', () => {
        for (const t of plan({ idp: 'auth0', maps: 'esri' })) {
            const isCloud = ['google', 'azure', 'aws'].includes(t.id);
            expect(Boolean(t.foundation)).toBe(isCloud);
        }
    });
});

describe('what the town asked for is what it gets', () => {
    it('leaves out anything unticked', () => {
        const list = ids({ wanted: new Set() });
        // Sign-in and maps are not optional -- a town cannot take a report
        // without them -- so they survive an empty tick list.
        const items = plan({ wanted: new Set() }).flatMap(t => t.items.map(i => i.id));
        expect(items.sort()).toEqual(['identity', 'maps']);
        expect(list.length).toBeGreaterThan(0);
    });

    it('puts whatever carries a required item first', () => {
        // Auth0 sign-in on an Azure town: the Auth0 task has to come before the
        // big optional Azure one, or the first thing on the page is the wrong
        // thing to do first.
        const list = ids({ idp: 'auth0' });
        expect(list.indexOf('auth0')).toBeLessThan(list.indexOf('azure'));
        expect(plan({ idp: 'auth0' }).find(t => t.id === 'auth0')!.required).toBe(true);
    });

    it('screening and blurring are one item, not two', () => {
        /* They were two sections and it made no sense: both answer "what is
         * safe to publish", and a clerk had to work out that the rose panel
         * three sections up was about words and this one is about faces. */
        const all = plan().flatMap(t => t.items);
        const safety = all.filter(i => i.id === 'safety');
        expect(safety).toHaveLength(1);
        expect(safety[0].title.toLowerCase()).toContain('blurring');
        expect(safety[0].cap).toBe('redaction');
    });

    it('follows the cloud for things that are a cloud decision', () => {
        const g = plan({ cloud: 'google', aiProvider: 'vertex', maps: 'google', idp: 'auth0' });
        const google = g.find(t => t.id === 'google')!;
        expect(google.items.map(i => i.id).sort()).toContain('translation');
        expect(google.items.find(i => i.id === 'ai')!.provider).toBe('vertex');
        expect(google.items.find(i => i.id === 'kms')!.provider).toBe('google');
    });

    it('lets email and text sit with whoever actually sends them', () => {
        // An Azure town sending through SES: email belongs to the AWS trip, not
        // the Azure one, because that is the console it is configured in.
        const t = plan({ emailProvider: 'ses' });
        expect(t.find(x => x.id === 'aws')!.items.map(i => i.id)).toContain('email');
        expect(t.find(x => x.id === 'azure')!.items.map(i => i.id)).not.toContain('email');
    });
});

describe('every item can actually be filled in', () => {
    it('has somewhere to type, or is a pointer to its own component', () => {
        /* The failure this catches is an item that renders a heading, a
         * sentence, and nothing else -- which is what the guide used to do
         * before the boxes moved inline, and which looks identical to a step
         * that needs no input. */
        const configurable = plan().flatMap(t => t.items).filter(i => i.id !== 'govtech');
        for (const item of configurable) {
            const hasProvider = Boolean(item.cap && item.provider);
            const hasSecrets = Boolean(item.secrets?.length);
            expect(hasProvider || hasSecrets).toBe(true);
        }
    });

    it('gives backups real boxes rather than telling anyone to find a card', () => {
        const backups = plan().flatMap(t => t.items).find(i => i.id === 'backups')!;
        const keys = backups.secrets!.map(s => s.key);
        expect(keys).toContain('BACKUP_S3_BUCKET');
        expect(keys).toContain('BACKUP_S3_ACCESS_KEY');
        expect(keys).toContain('BACKUP_S3_SECRET_KEY');
    });

    it('offers Azure Content Safety boxes only on Azure', () => {
        const azureSafety = plan().flatMap(t => t.items).find(i => i.id === 'safety')!;
        expect(azureSafety.secrets?.map(s => s.key)).toContain('AZURE_CONTENT_SAFETY_KEY');
        // On Google and AWS the screening reuses credentials entered elsewhere,
        // so offering an empty pair of boxes would invite someone to hunt for
        // values that do not exist.
        const awsSafety = plan({ cloud: 'aws', redactionProvider: 'aws' })
            .flatMap(t => t.items).find(i => i.id === 'safety')!;
        expect(awsSafety.secrets).toBeUndefined();
    });

    it('never puts one item in two tasks', () => {
        const seen = plan().flatMap(t => t.items.map(i => i.id));
        expect(new Set(seen).size).toBe(seen.length);
    });
});

describe('the copy does not make promises', () => {
    /* No claims about price, speed, or how easy something is. A town's
     * procurement officer reads these too, a free tier can change, and telling
     * a clerk something takes ten minutes is a way of making them feel slow
     * when it takes forty. */
    const FORBIDDEN = /\b(free|cheap|costs?|pricing|per month|a month|dollars?|cents?|\$\d|minutes?|hours?|quick(ly|est)?|fast(est)?|easy|easiest|simple|simplest|straightforward|just a)\b/i;

    it('says nothing about cost, speed or difficulty', () => {
        const offenders: string[] = [];
        for (const t of [...plan(), ...plan({ cloud: 'google', idp: 'auth0', maps: 'esri' }),
                         ...plan({ cloud: 'aws', idp: 'okta', maps: 'apple' })]) {
            if (FORBIDDEN.test(t.blurb)) offenders.push(`task ${t.id}: ${t.blurb}`);
            for (const i of t.items) {
                if (FORBIDDEN.test(i.blurb)) offenders.push(`item ${i.id}: ${i.blurb}`);
                if (FORBIDDEN.test(i.title)) offenders.push(`title ${i.id}: ${i.title}`);
            }
        }
        expect(offenders).toEqual([]);
    });
});
