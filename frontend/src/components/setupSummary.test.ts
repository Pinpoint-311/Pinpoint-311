import { describe, it, expect } from 'vitest';

import { buildPlan, summarise, nameList, type PlanItem } from './setupPlan';

/**
 * The badge on the collapsed panel has one job: be true.
 *
 * A count that disagrees with the list underneath it is worse than no count,
 * and the two most tempting merges are both wrong. "Not set up" and "not
 * working" need different actions from a clerk. And something that cannot be
 * checked from here is neither -- counting it produces a badge that can never
 * reach zero.
 */
const plan = () => buildPlan({
    cloud: 'azure', idp: 'entra', maps: 'google', aiProvider: 'azure',
    emailProvider: 'acs', smsProvider: 'acs', redactionProvider: 'azure',
    wanted: new Set(['ai', 'translation', 'sms', 'backups', 'errors', 'safety']),
});

const byId = (id: string) => (i: PlanItem) => i.id === id;

describe('summarise', () => {
    it('counts nothing when everything is configured and healthy', () => {
        const s = summarise(plan(), { isDone: () => true, stateOf: () => 'working' });
        expect(s.notSetUp).toEqual([]);
        expect(s.notWorking).toEqual([]);
        expect(s.total).toBeGreaterThan(0);
    });

    it('separates never-configured from configured-but-broken', () => {
        const s = summarise(plan(), {
            isDone: (i) => !byId('maps')(i),
            stateOf: (i) => (byId('identity')(i) ? 'failing' : 'working'),
        });
        expect(s.notSetUp.map(i => i.id)).toEqual(['maps']);
        expect(s.notWorking.map(i => i.id)).toEqual(['identity']);
    });

    it('does not count something that cannot be checked from here', () => {
        // An HTTP SMS gateway is configured and unverifiable forever. Counting
        // it gives a badge that can never reach zero, which is the same defect
        // as a red pill that can never go green.
        const s = summarise(plan(), { isDone: () => true, stateOf: () => 'unverifiable' });
        expect(s.notWorking).toEqual([]);
    });

    it('does not count an unchecked connector as broken', () => {
        const s = summarise(plan(), { isDone: () => true, stateOf: () => 'unchecked' });
        expect(s.notWorking).toEqual([]);
    });

    it('never counts an item twice', () => {
        const s = summarise(plan(), { isDone: () => false });
        const ids = s.notSetUp.map(i => i.id);
        expect(new Set(ids).size).toBe(ids.length);
    });

    it('treats a missing health lookup as not-broken rather than broken', () => {
        // The badge renders before the health request lands. Guessing "broken"
        // there would flash a red count at a town whose page is merely slow.
        const s = summarise(plan(), { isDone: () => true });
        expect(s.notWorking).toEqual([]);
    });
});

describe('nameList', () => {
    const items = (...titles: string[]) => titles.map(t => ({ id: t, title: t } as PlanItem));

    it('names one', () => expect(nameList(items('Maps'))).toBe('Maps'));
    it('names two', () => expect(nameList(items('Maps', 'AI'))).toBe('Maps and AI'));
    it('summarises more than it lists', () =>
        expect(nameList(items('Maps', 'AI', 'Email', 'Text'))).toBe('Maps, AI and 2 more'));
    it('says nothing about nothing', () => expect(nameList([])).toBe(''));
});
