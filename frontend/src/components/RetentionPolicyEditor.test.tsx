// @vitest-environment jsdom
import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest';
import { useState } from 'react';
import { render, screen, cleanup, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const calls = { run: [] as unknown[], update: [] as unknown[] };
let plan: Record<string, unknown> = {};

vi.mock('../services/api', () => {
    const api = {
        previewRetentionRun: async () => plan,
        runRetentionNow: async (confirm?: string) => { calls.run.push(confirm); return { status: 'ok', task_id: 't', message: 'queued' }; },
        updateRetentionPolicy: async (body: unknown) => { calls.update.push(body); return { configured: true }; },
    };
    return { default: api, api };
});

import RetentionPolicyEditor, { groupScrubFields } from './RetentionPolicyEditor';
import { DialogProvider } from './DialogProvider';
import type { ScrubField } from '../services/api';

if (!window.matchMedia) {
    (window as any).matchMedia = (query: string) => ({
        matches: false, media: query, onchange: null, addEventListener: () => { }, removeEventListener: () => { },
        addListener: () => { }, removeListener: () => { }, dispatchEvent: () => false,
    });
}

const ids = ['name', 'email', 'phone', 'description', 'custom_fields', 'staff_notes', 'media',
    'ai_analysis', 'comments', 'closing_message', 'address', 'coordinates'];
const catalog = (): ScrubField[] => ids.map(id => ({ id, label: `Label ${id}`, detail: `Detail ${id}`, selected: false }));

function Harness({ fields: initial = catalog(), saved = { days: 2555, mode: 'redact' as const, fieldIds: [] as string[] } }) {
    const [days, setDays] = useState('2555');
    const [mode, setMode] = useState<'redact' | 'purge'>('redact');
    const [fields, setFields] = useState<ScrubField[] | null>(initial);
    return (
        <DialogProvider>
            <RetentionPolicyEditor
                days={days} onDaysChange={setDays} mode={mode} onModeChange={setMode}
                fields={fields} onFieldsChange={setFields} saved={saved}
                onApplied={() => { }} onRunStarted={() => { }} onError={() => { }}
                onReview={() => { }} reviewing={false} onExport={() => { }} exportOpen={false}
            />
        </DialogProvider>
    );
}

beforeEach(() => { calls.run.length = 0; calls.update.length = 0; });
afterEach(cleanup);

describe('grouping', () => {
    it('groups by field id, keeps catalog text, and puts unknown ids in Other', () => {
        const groups = groupScrubFields([...catalog(), { id: 'future', label: 'F', detail: 'd', selected: false }]);
        expect(groups.map(g => [g.title, g.fields.map(f => f.id)])).toEqual([
            ['Reporter', ['name', 'email', 'phone']],
            ['What was said', ['description', 'custom_fields', 'comments', 'closing_message', 'staff_notes', 'ai_analysis']],
            ['Media and location', ['media', 'address', 'coordinates']],
            ['Other', ['future']],
        ]);
    });

    it('renders each group with a count, and Select all / None act on that group only', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const reporter = screen.getByRole('group', { name: 'Reporter' });
        expect(within(reporter).getByText('0 of 3')).toBeTruthy();
        expect(within(reporter).getByRole('checkbox', { name: /Label email/ })).toBeTruthy();
        expect(within(reporter).getByText('Detail email')).toBeTruthy();

        await user.click(within(reporter).getByRole('button', { name: 'Select all in Reporter' }));
        expect(within(reporter).getByText('3 of 3')).toBeTruthy();
        within(reporter).getAllByRole('checkbox').forEach(b => expect((b as HTMLInputElement).checked).toBe(true));
        const said = screen.getByRole('group', { name: 'What was said' });
        within(said).getAllByRole('checkbox').forEach(b => expect((b as HTMLInputElement).checked).toBe(false));

        // The count comes from the data: twelve fields, not a fixed eleven.
        expect(screen.getByText(/3 of 12 fields cleared/)).toBeTruthy();
        expect(screen.getByText('Unsaved changes')).toBeTruthy();

        await user.click(within(reporter).getByRole('button', { name: 'None in Reporter' }));
        expect(within(reporter).getByText('0 of 3')).toBeTruthy();
        expect(screen.getByText('Saved')).toBeTruthy();
    });

    it('shows a preset period in words and a days field for Custom', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        expect((screen.getByRole('radio', { name: '7 years' }) as HTMLInputElement).checked).toBe(true);
        expect(screen.queryByLabelText(/Keep closed requests for \(days\)/)).toBeNull();
        await user.click(screen.getByRole('radio', { name: 'Custom' }));
        const input = screen.getByLabelText(/Keep closed requests for \(days\)/) as HTMLInputElement;
        await user.clear(input);
        await user.type(input, '900');
        expect(screen.getByText('2.5 years')).toBeTruthy();
    });
});

describe('Run retention now', () => {
    it('asks first, saying fields are permanently cleared, and does nothing on Cancel', async () => {
        plan = { eligible: 4, will_act_on: 4, retention_days: 2555, mode: 'redact', scrub_fields: ['Reporter’s name'] };
        const user = userEvent.setup();
        render(<Harness />);
        await user.click(screen.getByRole('button', { name: /Run retention now/ }));
        const dialog = await screen.findByRole('dialog');
        expect(dialog.textContent).toMatch(/permanently cleared/);
        expect(dialog.textContent).toMatch(/4\s*closed records have passed/);
        await user.click(within(dialog).getByRole('button', { name: /Cancel/i }));
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        expect(calls.run).toEqual([]);
    });

    it('runs once confirmed', async () => {
        plan = { eligible: 2, retention_days: 365, mode: 'redact' };
        const user = userEvent.setup();
        render(<Harness />);
        await user.click(screen.getByRole('button', { name: /Run retention now/ }));
        const dialog = await screen.findByRole('dialog');
        await user.click(within(dialog).getByRole('button', { name: 'Redact them' }));
        await waitFor(() => expect(calls.run).toHaveLength(1));
    });

    it('does not ask when nothing is due', async () => {
        plan = { eligible: 0, retention_days: 365, mode: 'redact' };
        const user = userEvent.setup();
        render(<Harness />);
        await user.click(screen.getByRole('button', { name: /Run retention now/ }));
        const dialog = await screen.findByRole('dialog');
        expect(dialog.textContent).toMatch(/Nothing is due yet/);
        expect(calls.run).toEqual([]);
    });
});

describe('Apply policy', () => {
    it('is unavailable until something changes, then sends the chosen ids', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const apply = screen.getByRole('button', { name: 'Apply policy' }) as HTMLButtonElement;
        expect(apply.disabled).toBe(true);
        await user.click(screen.getByRole('checkbox', { name: /Label media/ }));
        expect(apply.disabled).toBe(false);
        await user.click(apply);
        await waitFor(() => expect(calls.update).toEqual([{ mode: 'redact', scrub_fields: ['media'], retention_days: 2555 }]));
    });
});
