// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, within, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

/**
 * The staff "log a request" form, beyond labelling and keyboard basics (see
 * ManualIntake.a11y.test.tsx): it has to ask everything the resident form
 * asks, say everything the resident form says before submit, and then get out
 * of a call taker's way -- staff options, a success panel, and the shortcuts.
 */

const state = vi.hoisted(() => ({
    modules: {} as Record<string, boolean>,
    mapsReady: false,
}));

const created = {
    service_request_id: 'REQ-4242',
    service_code: 'pothole',
    service_name: 'Pothole',
    status: 'open',
    description: 'Deep pothole near the crosswalk',
};

const createManualIntake = vi.fn();
const roadCheck = vi.fn();
const searchResidents = vi.fn();

vi.mock('../services/api', () => {
    const api = {
        createManualIntake: (...args: any[]) => createManualIntake(...args),
        roadCheck: (...args: any[]) => roadCheck(...args),
        searchResidents: (...args: any[]) => searchResidents(...args),
        getMapsConfig: vi.fn(async () => (state.mapsReady ? { map_provider_missing: [] } : {})),
        getMapLayers: vi.fn().mockResolvedValue([]),
        getDepartments: vi.fn().mockResolvedValue([]),
        getStaffMembers: vi.fn().mockResolvedValue([]),
        screenPhoto: vi.fn(),
    };
    return { api, default: api };
});

vi.mock('../context/SettingsContext', () => ({
    useSettings: () => ({ settings: { modules: state.modules } }),
}));

/* The real picker needs a map provider. This stand-in exposes the three
 * callbacks the form depends on as buttons. */
vi.mock('./LocationPicker', () => ({
    default: (props: any) => (
        <div>
            <button type="button" onClick={() => props.onChange({ address: '10 Main St', lat: 40.0, lng: -74.0 })}>
                Drop pin
            </button>
            <button type="button" onClick={() => props.onOutOfBounds?.()}>Drop pin outside</button>
            <button type="button" onClick={() => props.onAssetSelect?.({
                layerName: 'Streetlights', properties: { asset_id: 'SL-12', asset_type: 'Streetlight' }, lat: 40, lng: -74,
            })}>Pick asset</button>
        </div>
    ),
}));

import ManualIntake from './ManualIntake';
import { AccessibilityProvider } from '../context/AccessibilityContext';

if (!window.matchMedia) {
    (window as any).matchMedia = (query: string) => ({
        matches: false, media: query, onchange: null,
        addEventListener: () => { }, removeEventListener: () => { },
        addListener: () => { }, removeListener: () => { }, dispatchEvent: () => false,
    });
}
// framer-motion measures layout through scrollTo, which jsdom does not have.
window.scrollTo = (() => { }) as any;

const services = [
    {
        service_code: 'pothole', service_name: 'Pothole', description: 'Holes in the road surface',
        icon: 'Construction', is_active: true, assigned_department_id: 1,
        routing_config: {
            custom_questions: [
                { id: 'q1', label: 'Nearest cross street', type: 'text', required: true },
                { id: 'q2', label: 'Is the road blocked?', type: 'yes_no', required: true },
                { id: 'q3', label: 'Lane', type: 'select', required: false, options: ['Left', 'Right'] },
            ],
        },
    },
    { service_code: 'streetlight', service_name: 'Streetlight Out', description: 'Dark poles', icon: 'Lightbulb', is_active: true, location_mode: 'required' },
    {
        service_code: 'county', service_name: 'County Road Issue', description: 'Handled by the county',
        icon: 'Route', is_active: true, routing_mode: 'third_party',
        routing_config: { third_party_name: 'County DPW', contacts: [{ name: 'County DPW', phone: '555-0100' }] },
    },
    { service_code: 'roads', service_name: 'Road Damage', icon: 'Route', is_active: true, routing_mode: 'road_based' },
    { service_code: 'abuse', service_name: 'Code Complaint', icon: 'Gavel', is_active: true, hidden_from_public: true },
    { service_code: 'graffiti', service_name: 'Graffiti', description: 'Spray paint tags', icon: 'SprayCan', is_active: true },
] as any;

const departments = [
    { id: 1, name: 'Public Works', is_active: true },
    { id: 2, name: 'Parks', is_active: true },
] as any;
const staff = [
    { id: 7, username: 'jdoe', full_name: 'Jane Doe', role: 'staff', is_active: true },
    { id: 8, username: 'reader', full_name: 'Rita Reader', role: 'researcher', is_active: true },
] as any;

const onCreated = vi.fn();
const onClose = vi.fn();
const onOpenRequest = vi.fn();

async function open(props: Record<string, any> = {}) {
    render(
        <AccessibilityProvider>
            <ManualIntake
                isOpen onClose={onClose} services={services} onCreated={onCreated}
                departments={departments} staff={staff} onOpenRequest={onOpenRequest}
                {...props}
            />
        </AccessibilityProvider>,
    );
    const description = await screen.findByLabelText(/what is the caller reporting/i);
    await waitFor(() => expect(document.activeElement).toBe(description));
    return description as HTMLTextAreaElement;
}

const category = () => screen.getByRole('button', { name: /^category/i });
const logRequest = () => screen.getByRole('button', { name: /log request/i });

async function pickCategory(user: ReturnType<typeof userEvent.setup>, name: string) {
    await user.click(category());
    await user.keyboard(name);
    await user.keyboard('{ArrowDown}{Enter}');
    await waitFor(() => expect(screen.queryByRole('listbox')).toBeNull());
}

const payload = () => createManualIntake.mock.calls[createManualIntake.mock.calls.length - 1][0];

beforeEach(() => {
    try { localStorage.clear(); } catch { /* no storage */ }
    state.modules = {};
    state.mapsReady = false;
    createManualIntake.mockReset().mockResolvedValue(created);
    roadCheck.mockReset();
    searchResidents.mockReset();
    onCreated.mockClear(); onClose.mockClear(); onOpenRequest.mockClear();
});
afterEach(cleanup);

describe('validation', () => {
    it('collects every problem at once and links each to its field', async () => {
        const user = userEvent.setup();
        await open();
        await pickCategory(user, 'Pothole');

        await user.type(screen.getByLabelText(/what is the caller reporting/i), 'short');
        await user.type(screen.getByLabelText(/callback number/i), '12');
        await user.click(screen.getByRole('button', { name: /caller details/i }));
        await user.type(screen.getByLabelText(/caller email/i), 'bad@');
        await user.click(logRequest());

        const summary = document.getElementById('intake-error-summary')!;
        expect(document.activeElement).toBe(summary);
        expect(within(summary).getByRole('heading').textContent).toContain('5 problems');
        const hrefs = within(summary).getAllByRole('link').map(a => a.getAttribute('href'));
        expect(hrefs).toEqual(expect.arrayContaining([
            '#intake-description', '#intake-custom-q1', '#intake-custom-q2', '#intake-phone', '#intake-email',
        ]));
        // Errors are red, not amber.
        expect(document.getElementById('intake-description-error')!.className).toContain('text-red-400');
        expect(createManualIntake).not.toHaveBeenCalled();
    });

    it('accepts a full category description match', async () => {
        const user = userEvent.setup();
        await open();
        await user.click(category());
        // "Spray paint" is only in Graffiti's description.
        await user.keyboard('spray paint');
        const options = screen.getAllByRole('option');
        expect(options).toHaveLength(1);
        expect(options[0].textContent).toContain('Graffiti');
        expect(options[0].textContent).toContain('Spray paint tags');
    });
});

describe('category questions', () => {
    it('asks them, and sends the answers as custom_fields', async () => {
        const user = userEvent.setup();
        await open();
        await pickCategory(user, 'Pothole');

        await user.type(screen.getByLabelText(/what is the caller reporting/i), 'Pothole by the library steps');
        await user.type(screen.getByLabelText(/Nearest cross street/), 'Oak Ave');
        const blocked = screen.getByRole('group', { name: /Is the road blocked\?/ });
        await user.click(within(blocked).getByRole('radio', { name: 'Yes' }));
        await user.selectOptions(screen.getByLabelText(/^Lane/), 'Left');
        await user.click(logRequest());

        await waitFor(() => expect(createManualIntake).toHaveBeenCalled());
        expect(payload().custom_fields).toEqual({
            'Nearest cross street': 'Oak Ave', 'Is the road blocked?': 'Yes', Lane: 'Left',
        });
        expect(payload().preferred_language).toBe('en');
    });

    it('remembers recently used categories at the top of the list', async () => {
        const user = userEvent.setup();
        await open();
        await pickCategory(user, 'Graffiti');
        await user.type(screen.getByLabelText(/what is the caller reporting/i), 'Tags on the library wall');
        await user.click(logRequest());
        await screen.findByRole('heading', { name: /request logged/i });

        await user.click(screen.getByRole('button', { name: /^log another$/i }));
        await user.click(category());
        const first = screen.getAllByRole('option')[0];
        expect(first.textContent).toContain('Recent');
        expect(first.textContent).toContain('Graffiti');
    });
});

describe('the success panel', () => {
    it('shows the ID, copies the tracking link, and opens the request', async () => {
        const user = userEvent.setup();
        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

        const description = await open();
        await pickCategory(user, 'Graffiti');
        await user.type(description, 'Tags on the library wall');
        await user.click(logRequest());

        const heading = await screen.findByRole('heading', { name: /request logged/i });
        await waitFor(() => expect(document.activeElement).toBe(heading));
        expect(screen.getByText('REQ-4242')).toBeTruthy();
        const url = `${window.location.origin}/#track/REQ-4242`;
        expect(screen.getByText(url)).toBeTruthy();

        await user.click(screen.getByRole('button', { name: /copy tracking link/i }));
        expect(writeText).toHaveBeenCalledWith(url);

        await user.click(screen.getByRole('button', { name: /open request/i }));
        expect(onOpenRequest).toHaveBeenCalledWith('REQ-4242');
        expect(onClose).not.toHaveBeenCalled();
        expect(onCreated).toHaveBeenCalledWith(created);
    });

    it('logs another for the same caller, keeping only the contact details', async () => {
        const user = userEvent.setup();
        const description = await open();
        await pickCategory(user, 'Graffiti');
        await user.type(description, 'Tags on the library wall');
        await user.type(screen.getByLabelText(/callback number/i), '(555) 123-4567');
        await user.click(logRequest());
        await screen.findByRole('heading', { name: /request logged/i });

        await user.click(screen.getByRole('button', { name: /same caller/i }));
        const fresh = await screen.findByLabelText(/what is the caller reporting/i);
        expect((fresh as HTMLTextAreaElement).value).toBe('');
        expect((screen.getByLabelText(/callback number/i) as HTMLInputElement).value).toBe('(555) 123-4567');
        expect(category().textContent).toContain('Choose a category');
    });

    it('logs another from scratch', async () => {
        const user = userEvent.setup();
        const description = await open();
        await pickCategory(user, 'Graffiti');
        await user.type(description, 'Tags on the library wall');
        await user.type(screen.getByLabelText(/callback number/i), '(555) 123-4567');
        await user.click(logRequest());
        await screen.findByRole('heading', { name: /request logged/i });

        await user.click(screen.getByRole('button', { name: /^log another$/i }));
        expect((await screen.findByLabelText(/callback number/i) as HTMLInputElement).value).toBe('');
    });
});

describe('closing and reopening', () => {
    function Harness() {
        const [isOpen, setOpen] = React.useState(true);
        return (
            <AccessibilityProvider>
                <button type="button" onClick={() => setOpen(true)}>Reopen</button>
                <ManualIntake isOpen={isOpen} onClose={() => setOpen(false)} services={services} onCreated={onCreated} />
            </AccessibilityProvider>
        );
    }

    it('starts clean after a request was logged, so it cannot be logged twice', async () => {
        const user = userEvent.setup();
        render(<Harness />);
        const description = await screen.findByLabelText(/what is the caller reporting/i);
        await waitFor(() => expect(document.activeElement).toBe(description));
        await pickCategory(user, 'Graffiti');
        await user.type(description, 'Tags on the library wall');
        await user.click(logRequest());
        await screen.findByRole('heading', { name: /request logged/i });

        await user.click(screen.getByRole('button', { name: /^close$/i }));
        await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
        await user.click(screen.getByRole('button', { name: 'Reopen' }));
        const fresh = await screen.findByLabelText(/what is the caller reporting/i);
        expect((fresh as HTMLTextAreaElement).value).toBe('');
        expect(category().textContent).toContain('Choose a category');
    });
});

describe('staff options', () => {
    it('sends nothing extra when left alone', async () => {
        const user = userEvent.setup();
        const description = await open();
        await pickCategory(user, 'Graffiti');
        await user.type(description, 'Tags on the library wall');
        await user.click(logRequest());
        await waitFor(() => expect(createManualIntake).toHaveBeenCalled());
        const sent = payload();
        expect(sent.assigned_department_id).toBeUndefined();
        expect(sent.assigned_to).toBeUndefined();
        expect(sent.manual_priority_score).toBeUndefined();
        expect(sent.staff_notes).toBeUndefined();
        expect(sent.send_confirmation).toBe(true);
    });

    it('sends the department, assignee, priority, note and confirmation choice', async () => {
        const user = userEvent.setup();
        const description = await open();
        await pickCategory(user, 'Graffiti');
        await user.type(description, 'Tags on the library wall');
        await user.click(screen.getByRole('button', { name: /caller details/i }));
        await user.type(screen.getByLabelText(/caller email/i), 'caller@example.gov');

        await user.click(screen.getByRole('button', { name: /staff options/i }));
        const dept = screen.getByLabelText(/^Department/) as HTMLSelectElement;
        // The blank choice says what it falls back to.
        expect(dept.options[0].textContent).toBe('Category default');
        await user.selectOptions(dept, '2');
        const assignee = screen.getByLabelText(/^Assign to/) as HTMLSelectElement;
        // Only people who can work a request.
        expect(Array.from(assignee.options).map(o => o.value)).toEqual(['', 'jdoe']);
        await user.selectOptions(assignee, 'jdoe');
        await user.selectOptions(screen.getByLabelText(/^Priority/), '8');
        await user.type(screen.getByLabelText(/^Internal note/), 'Owner is on vacation');
        const confirm = screen.getByLabelText(/send the caller a confirmation/i) as HTMLInputElement;
        expect(confirm.checked).toBe(true);
        await user.click(confirm);

        await user.click(logRequest());
        await waitFor(() => expect(createManualIntake).toHaveBeenCalled());
        expect(payload()).toMatchObject({
            assigned_department_id: 2,
            assigned_to: 'jdoe',
            manual_priority_score: 8,
            staff_notes: 'Owner is on vacation',
            send_confirmation: false,
            email: 'caller@example.gov',
        });
    });

    it('cannot promise a confirmation without an email', async () => {
        const user = userEvent.setup();
        await open();
        await user.click(screen.getByRole('button', { name: /staff options/i }));
        const confirm = screen.getByLabelText(/send the caller a confirmation/i) as HTMLInputElement;
        expect(confirm.disabled).toBe(true);
        expect(confirm.checked).toBe(false);
    });
});

describe('what the resident form says before submit', () => {
    it('names the agency for a third-party category as soon as it is picked, and requires the override', async () => {
        const user = userEvent.setup();
        const description = await open();
        await pickCategory(user, 'County');
        expect(screen.getByRole('heading', { name: /County Road Issue reports are handled by County DPW/ })).toBeTruthy();

        await user.type(description, 'Shoulder washed out near mile 3');
        await user.click(logRequest());
        const summary = document.getElementById('intake-error-summary')!;
        expect(summary.textContent).toContain('Log it anyway');
        expect(createManualIntake).not.toHaveBeenCalled();

        await user.click(screen.getByLabelText(/log it anyway/i));
        await user.click(logRequest());
        await waitFor(() => expect(createManualIntake).toHaveBeenCalled());
        expect(payload().override_jurisdiction).toBe(true);
    });

    it('checks the road when the pin drops, before submit', async () => {
        state.mapsReady = true;
        roadCheck.mockResolvedValue({
            blocked: true, block_type: 'road', jurisdiction: 'State DOT', message: '', message_is_default: true,
            contacts: [{ name: 'State DOT', phone: '555-0199' }], road: 'Route 1',
            detected_road: { name: 'Route 1', distance_m: 4 },
        });
        const user = userEvent.setup();
        await open();
        await pickCategory(user, 'Road Damage');
        await user.click(await screen.findByRole('button', { name: 'Drop pin' }));

        await waitFor(() => expect(roadCheck).toHaveBeenCalledWith('roads', 40.0, -74.0));
        expect(await screen.findByRole('heading', { name: /Road Damage reports on Route 1 are handled by State DOT/ })).toBeTruthy();
        expect(screen.getByLabelText(/log it anyway/i)).toBeTruthy();
    });

    it('says when the pin is outside the municipality', async () => {
        state.mapsReady = true;
        const user = userEvent.setup();
        await open();
        await user.click(await screen.findByRole('button', { name: 'Drop pin outside' }));
        expect(screen.getByText(/outside the municipality/i)).toBeTruthy();
    });

    it('shows the selected asset, sends it normalized, and can clear it', async () => {
        state.mapsReady = true;
        const user = userEvent.setup();
        const description = await open();
        await pickCategory(user, 'Graffiti');
        await user.type(description, 'Tags on the streetlight pole');
        await user.click(await screen.findByRole('button', { name: 'Pick asset' }));
        expect(screen.getByText(/Selected asset/)).toBeTruthy();
        await user.click(logRequest());
        await waitFor(() => expect(createManualIntake).toHaveBeenCalled());
        expect(payload().matched_asset).toMatchObject({
            layer_name: 'Streetlights', asset_id: 'SL-12', asset_type: 'Streetlight', distance_meters: 0,
        });
    });

    it('clears a selected asset', async () => {
        state.mapsReady = true;
        const user = userEvent.setup();
        await open();
        await user.click(await screen.findByRole('button', { name: 'Pick asset' }));
        await user.click(screen.getByRole('button', { name: /clear selected asset/i }));
        expect(screen.queryByText(/Selected asset/)).toBeNull();
    });

    it('warns, without blocking, when a category usually needs a location', async () => {
        const user = userEvent.setup();
        const description = await open();
        await pickCategory(user, 'Streetlight');
        expect(screen.getByText('This category usually needs a location.')).toBeTruthy();
        await user.type(description, 'Light out at 4th and Elm');
        await user.click(logRequest());
        await waitFor(() => expect(createManualIntake).toHaveBeenCalled());
    });

    it('says a hidden category stays off the public map, and offers no unlisted box', async () => {
        state.modules = { unlisted_reports: true };
        const user = userEvent.setup();
        await open();
        expect(screen.getByText(/hide from the public map/i)).toBeTruthy();
        await pickCategory(user, 'Code Complaint');
        expect(screen.getByText(/won’t be shown publicly/)).toBeTruthy();
        expect(screen.queryByText(/hide from the public map/i)).toBeNull();
    });
});

describe('call-taker shortcuts and context', () => {
    it('switches channel with Alt+number, and shows the 911 cue only for calls', async () => {
        await open();
        expect(screen.getByText(/transfer the caller to 911/i)).toBeTruthy();

        fireEvent.keyDown(screen.getByLabelText(/what is the caller reporting/i), { key: '¡', code: 'Digit2', altKey: true });
        expect(screen.getByRole('radio', { name: /email/i }).getAttribute('aria-checked')).toBe('true');
        expect(screen.getByLabelText(/what does the email say/i)).toBeTruthy();
        expect(screen.queryByText(/transfer the caller to 911/i)).toBeNull();

        fireEvent.keyDown(screen.getByLabelText(/what does the email say/i), { key: '4', code: 'Digit4', altKey: true });
        expect(screen.getByRole('radio', { name: /other/i }).getAttribute('aria-checked')).toBe('true');
    });

    it('logs with Ctrl+Enter and sends the chosen language', async () => {
        const user = userEvent.setup();
        const description = await open();
        await pickCategory(user, 'Graffiti');
        await user.type(description, 'Tags on the library wall');
        await user.click(screen.getByRole('button', { name: /caller details/i }));
        await user.selectOptions(screen.getByLabelText(/preferred language/i), 'es');
        fireEvent.keyDown(screen.getByLabelText(/what is the caller reporting/i), { key: 'Enter', ctrlKey: true });
        await waitFor(() => expect(createManualIntake).toHaveBeenCalled());
        expect(payload().preferred_language).toBe('es');
        expect(payload().source).toBe('phone');
    });

    it('lists possible duplicates nearby in the same category', async () => {
        state.mapsReady = true;
        const requests = [
            { service_request_id: 'REQ-NEAR', service_code: 'graffiti', status: 'open', lat: 40.0003, long: -74.0, address: '12 Main St' },
            { service_request_id: 'REQ-CLOSED', service_code: 'graffiti', status: 'closed', lat: 40.0, long: -74.0 },
            { service_request_id: 'REQ-FAR', service_code: 'graffiti', status: 'open', lat: 40.01, long: -74.0 },
            { service_request_id: 'REQ-OTHER', service_code: 'pothole', status: 'open', lat: 40.0, long: -74.0 },
        ];
        const user = userEvent.setup();
        await open({ requests });
        await pickCategory(user, 'Graffiti');
        await user.click(await screen.findByRole('button', { name: 'Drop pin' }));

        expect(screen.getByText('Possible duplicates')).toBeTruthy();
        expect(screen.getByText('REQ-NEAR')).toBeTruthy();
        expect(screen.queryByText('REQ-CLOSED')).toBeNull();
        expect(screen.queryByText('REQ-FAR')).toBeNull();
        expect(screen.queryByText('REQ-OTHER')).toBeNull();
        await user.click(screen.getByRole('button', { name: 'Open request REQ-NEAR' }));
        expect(onOpenRequest).toHaveBeenCalledWith('REQ-NEAR');
    });

    it('looks up other reports from the caller when Resident History is on', async () => {
        state.modules = { resident_history: true };
        searchResidents.mockResolvedValue({
            searched_by: 'email', total: 2,
            reports: [
                { service_request_id: 'REQ-1', service_name: 'Pothole', status: 'open', requested_datetime: null },
                { service_request_id: 'REQ-2', service_name: 'Graffiti', status: 'closed', requested_datetime: null },
            ],
        });
        const user = userEvent.setup();
        await open();
        await user.click(screen.getByRole('button', { name: /caller details/i }));
        await user.type(screen.getByLabelText(/caller email/i), 'Caller@Example.gov');
        await user.tab();

        await waitFor(() => expect(searchResidents).toHaveBeenCalledWith({ email: 'caller@example.gov' }));
        const toggle = await screen.findByRole('button', { name: /2 other reports from this caller/i });
        await user.click(toggle);
        await user.click(screen.getByRole('button', { name: 'Open request REQ-2' }));
        expect(onOpenRequest).toHaveBeenCalledWith('REQ-2');
    });

    it('never searches residents when the module is off', async () => {
        const user = userEvent.setup();
        await open();
        await user.click(screen.getByRole('button', { name: /caller details/i }));
        await user.type(screen.getByLabelText(/caller email/i), 'caller@example.gov');
        await user.tab();
        expect(searchResidents).not.toHaveBeenCalled();
    });

    it('turns autofill off on the contact fields', async () => {
        const user = userEvent.setup();
        await open();
        await user.click(screen.getByRole('button', { name: /caller details/i }));
        for (const label of [/first name/i, /last name/i, /caller email/i, /callback number/i]) {
            expect(screen.getByLabelText(label).getAttribute('autocomplete')).toBe('off');
        }
    });
});
