// @vitest-environment jsdom
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * The translation card shows the spend against the town's budget, and lets an
 * admin move it. The server refuses past either budget and serves residents the
 * source text; this is the only place that is visible before it happens.
 */

const getTranslationBudget = vi.fn();
const updateTranslationBudget = vi.fn();
vi.mock('../services/api', () => {
    const api = {
        getTranslationBudget: (...a: unknown[]) => getTranslationBudget(...a),
        updateTranslationBudget: (...a: unknown[]) => updateTranslationBudget(...a),
    };
    return { default: api, api };
});

function usage(dayUsed: number, monthUsed: number, opts: Partial<{ dayLimit: number; monthLimit: number; dayExhausted: boolean; store: string }> = {}) {
    const dayLimit = opts.dayLimit ?? 500000;
    const monthLimit = opts.monthLimit ?? 5000000;
    const period = (used: number, limit: number, exhausted: boolean) => ({
        period: 'x', used, limit, remaining: Math.max(limit - used, 0),
        percent: Math.round((used / limit) * 1000) / 10, exhausted, resets_at: '2026-10-19T00:00:00+00:00',
    });
    return {
        day: period(dayUsed, dayLimit, opts.dayExhausted ?? dayUsed >= dayLimit),
        month: period(monthUsed, monthLimit, monthUsed >= monthLimit),
        status: 'ok', counter_store: opts.store ?? 'redis',
        defaults: { daily: 500000, monthly: 5000000 }, max_budget: 1e9,
    };
}

let host: HTMLDivElement; let root: Root;
beforeEach(() => { host = document.createElement('div'); document.body.appendChild(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.clearAllMocks(); });

async function mount() {
    const { default: Panel } = await import('./TranslationBudgetPanel');
    await act(async () => { root.render(React.createElement(Panel)); });
    return host;
}

function setInput(el: HTMLInputElement, value: string) {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
}

describe('TranslationBudgetPanel', () => {
    it("shows today's and this month's usage against the budget", async () => {
        getTranslationBudget.mockResolvedValue(usage(123456, 1000000));
        const el = await mount();
        const today = el.querySelector('[data-testid="translation-budget-today"]')!;
        const month = el.querySelector('[data-testid="translation-budget-this-month"]')!;
        expect(today.textContent).toContain('123,456 of 500,000 characters');
        expect(today.textContent).toContain('Within budget');
        expect(month.textContent).toContain('1,000,000 of 5,000,000 characters');
        const bar = today.querySelector('[role="progressbar"]')!;
        expect(bar.getAttribute('aria-valuenow')).toBe('25');
        expect(bar.getAttribute('aria-valuetext')).toBe('123,456 of 500,000 characters');
    });

    it('flags near-limit and reached budgets in words, not only colour', async () => {
        getTranslationBudget.mockResolvedValue(usage(420000, 5000000, { dayExhausted: false }));
        const el = await mount();
        expect(el.querySelector('[data-testid="translation-budget-today"]')!.textContent).toContain('Near limit');
        expect(el.querySelector('[data-testid="translation-budget-this-month"]')!.textContent).toContain('Budget reached');
    });

    it('counts a refused request as reached even below 100%', async () => {
        getTranslationBudget.mockResolvedValue(usage(485000, 0, { dayExhausted: true }));
        const el = await mount();
        expect(el.querySelector('[data-testid="translation-budget-today"]')!.textContent).toContain('Budget reached');
    });

    it('warns when the shared counter is unavailable', async () => {
        getTranslationBudget.mockResolvedValue(usage(0, 0, { store: 'memory' }));
        const el = await mount();
        expect(el.textContent).toMatch(/counting on its own/);
    });

    it('renders nothing without access or data', async () => {
        getTranslationBudget.mockRejectedValue(new Error('Admin access required'));
        const el = await mount();
        expect(el.textContent).toBe('');
        getTranslationBudget.mockResolvedValue({});
        const el2 = await mount();
        expect(el2.textContent).toBe('');
    });

    it('lets an admin change the budgets', async () => {
        getTranslationBudget.mockResolvedValue(usage(1000, 2000));
        updateTranslationBudget.mockResolvedValue(usage(1000, 2000, { dayLimit: 250000, monthLimit: 3000000 }));
        const el = await mount();
        const change = [...el.querySelectorAll('button')].find(b => b.textContent === 'Change budget')!;
        expect(change.className).toContain('btn-outline');
        await act(async () => { change.click(); });
        const [daily, monthly] = [...el.querySelectorAll('input')] as HTMLInputElement[];
        expect(daily.value).toBe('500000');
        await act(async () => { setInput(daily, '250,000'); setInput(monthly, '3000000'); });
        const save = [...el.querySelectorAll('button')].find(b => b.textContent === 'Save')!;
        await act(async () => { save.click(); });
        expect(updateTranslationBudget).toHaveBeenCalledWith(250000, 3000000);
        expect(el.textContent).toContain('1,000 of 250,000 characters');
        expect(el.querySelector('form')).toBeNull();
    });

    it('refuses a daily budget above the monthly one without calling the server', async () => {
        getTranslationBudget.mockResolvedValue(usage(0, 0));
        const el = await mount();
        await act(async () => { [...el.querySelectorAll('button')].find(b => b.textContent === 'Change budget')!.click(); });
        const [daily, monthly] = [...el.querySelectorAll('input')] as HTMLInputElement[];
        await act(async () => { setInput(daily, '900'); setInput(monthly, '100'); });
        await act(async () => { [...el.querySelectorAll('button')].find(b => b.textContent === 'Save')!.click(); });
        expect(updateTranslationBudget).not.toHaveBeenCalled();
        expect(el.querySelector('[role="alert"]')!.textContent).toMatch(/daily budget cannot be larger/);
    });
});
