import { useEffect, useMemo, useRef, useState } from 'react';
import { resolveMapProviderConfig, mapProviderReady, RawMapsConfig } from '../maps';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Phone, Mail, Footprints, Search, CheckCircle, Loader2, Sparkles,
    ChevronDown, MapPin, User as UserIcon, X, AlertCircle, EyeOff, SignpostBig,
} from 'lucide-react';

import { Modal } from './ui';
import { api, MapLayer } from '../services/api';
import LocationPicker from './LocationPicker';
import { ServiceDefinition, ServiceRequest } from '../types';
import { useSettings } from '../context/SettingsContext';
import { useAnnounce } from '../context/AccessibilityContext';

type Source = 'phone' | 'email' | 'walk_in';

/* Which field a validation message belongs to, so the message can be tied to
 * the control with aria-describedby and focus can be sent there. A bare
 * `error` string could say what was wrong but not what to fix. */
type ErrorField = 'category' | 'description' | 'email' | null;

const SOURCES: { value: Source; label: string; icon: typeof Phone }[] = [
    { value: 'phone', label: 'Phone call', icon: Phone },
    { value: 'email', label: 'Email', icon: Mail },
    { value: 'walk_in', label: 'Walk-in', icon: Footprints },
];

// Per-channel copy — a phone caller, an email sender and a walk-in visitor are
// three different intake situations, so the labels, examples and contact hints
// are tailored to each rather than defaulting everything to "caller".
const COPY: Record<Source, {
    lead: string;
    descLabel: string;
    descPlaceholder: string;
    phoneLabel: string;
    phoneIcon: typeof Phone;
    phonePlaceholder: string;
    contactToggle: string;
    contactBlurb: string;
    emailLabel: string;
    emailPlaceholder: string;
    logCta: string;
}> = {
    phone: {
        lead: 'Take a request over the phone on a resident’s behalf. It’s triaged, routed, and synced exactly like a report filed online — contact details are optional.',
        descLabel: 'What is the caller reporting?',
        descPlaceholder: 'e.g. Caller reports a large pothole in the eastbound lane of Main St near the library, damaging tires.',
        phoneLabel: 'Callback number',
        phoneIcon: Phone,
        phonePlaceholder: '(555) 123-4567',
        contactToggle: 'Caller details (optional — for follow-up & confirmation)',
        contactBlurb: 'Only needed if the caller wants a status update or callback.',
        emailLabel: 'Caller email',
        emailPlaceholder: 'If given, the caller gets the same confirmation as an online report',
        logCta: 'Log request',
    },
    email: {
        lead: 'Log a request from an email a resident sent in. It’s triaged, routed, and synced exactly like a report filed online — paste the details below.',
        descLabel: 'What does the email say?',
        descPlaceholder: 'e.g. Resident emailed that the streetlight at 4th & Elm has been out for a week, leaving the crosswalk dark at night. Paste or summarize the message here.',
        phoneLabel: 'Contact number',
        phoneIcon: Phone,
        phonePlaceholder: '(555) 123-4567 — if included in the email',
        contactToggle: 'Sender details (optional — pull from the email)',
        contactBlurb: 'Copy the sender’s name and address from the email so replies reach them.',
        emailLabel: 'Sender email',
        emailPlaceholder: 'sender@email.com — they’ll get the same confirmation as an online report',
        logCta: 'Log request',
    },
    walk_in: {
        lead: 'Log a request for someone at the counter. It’s triaged, routed, and synced exactly like a report filed online — contact details are optional.',
        descLabel: 'What is the visitor reporting?',
        descPlaceholder: 'e.g. Visitor reports the playground gate at Riverside Park is broken and won’t latch, so it swings into the path.',
        phoneLabel: 'Contact number',
        phoneIcon: Phone,
        phonePlaceholder: '(555) 123-4567',
        contactToggle: 'Visitor details (optional — for follow-up & confirmation)',
        contactBlurb: 'Only needed if the visitor wants a status update or callback.',
        emailLabel: 'Visitor email',
        emailPlaceholder: 'If given, they’ll get the same confirmation as an online report',
        logCta: 'Log request',
    },
};

interface ManualIntakeProps {
    isOpen: boolean;
    onClose: () => void;
    services: ServiceDefinition[];
    onCreated: (request: ServiceRequest) => void;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function ManualIntake({ isOpen, onClose, services, onCreated }: ManualIntakeProps) {
    const { settings } = useSettings();
    const announce = useAnnounce();
    const [source, setSource] = useState<Source>('phone');
    // Honors a caller who asks not to be listed publicly — same rule as the
    // resident form, and only offered when the town enabled the module.
    const [hideFromPublic, setHideFromPublic] = useState(false);
    const [serviceCode, setServiceCode] = useState('');
    const [catQuery, setCatQuery] = useState('');
    const [catOpen, setCatOpen] = useState(false);
    const [description, setDescription] = useState('');
    const [phone, setPhone] = useState('');
    const [address, setAddress] = useState('');
    const [lat, setLat] = useState<number | null>(null);
    const [lng, setLng] = useState<number | null>(null);
    const [matchedAsset, setMatchedAsset] = useState<Record<string, any> | null>(null);
    const [showContact, setShowContact] = useState(false);

    // Map configuration — the same picker residents use, so a call taker can
    // drop a pin or search an address and the request is geolocated identically.
    const [mapsRaw, setMapsRaw] = useState<RawMapsConfig | null>(null);
    const mapConfig = useMemo(() => resolveMapProviderConfig(mapsRaw), [mapsRaw]);
    const [townshipBoundary, setTownshipBoundary] = useState<object | null>(null);
    const [mapLayers, setMapLayers] = useState<MapLayer[]>([]);
    // Bumped on reset so the map picker remounts clean between back-to-back logs.
    const [mapKey, setMapKey] = useState(0);
    const [firstName, setFirstName] = useState('');
    const [lastName, setLastName] = useState('');
    const [email, setEmail] = useState('');

    const [saving, setSaving] = useState<'close' | 'another' | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [errorField, setErrorField] = useState<ErrorField>(null);
    // Which option the combobox keyboard cursor is on; -1 is "none yet".
    const [activeIndex, setActiveIndex] = useState(-1);
    // A 409 from the server means this location belongs to another agency. A
    // clerk on the phone can still choose to log it -- the caller is elderly,
    // the town forwards these anyway, it is faster than explaining. Refusing
    // outright would just move the work into a notepad. Residents get no such
    // choice; staff exercising judgement is the point of the role.
    const [redirect, setRedirect] = useState<{
        jurisdiction: string | null; message: string; road: string | null;
        contacts: { name?: string; phone?: string; url?: string }[];
    } | null>(null);
    const [overrideJurisdiction, setOverrideJurisdiction] = useState(false);
    const [lastLogged, setLastLogged] = useState<string | null>(null);
    const [sessionCount, setSessionCount] = useState(0);

    const descRef = useRef<HTMLTextAreaElement>(null);
    const catButtonRef = useRef<HTMLButtonElement>(null);
    const catFilterRef = useRef<HTMLInputElement>(null);
    const emailRef = useRef<HTMLInputElement>(null);
    const listboxRef = useRef<HTMLUListElement>(null);

    const active = useMemo(() => services.filter(s => s.is_active !== false), [services]);
    const selected = active.find(s => s.service_code === serviceCode);
    const filtered = useMemo(() => {
        const q = catQuery.trim().toLowerCase();
        if (!q) return active;
        return active.filter(s => s.service_name.toLowerCase().includes(q) || s.service_code.toLowerCase().includes(q));
    }, [active, catQuery]);

    const resetForm = (keepSource = true) => {
        if (!keepSource) setSource('phone');
        setServiceCode(''); setCatQuery(''); setCatOpen(false);
        setDescription(''); setPhone(''); setAddress('');
        setLat(null); setLng(null); setMatchedAsset(null); setMapKey(k => k + 1);
        setShowContact(false); setFirstName(''); setLastName(''); setEmail('');
        setHideFromPublic(false);
        setRedirect(null); setOverrideJurisdiction(false);
        setError(null); setErrorField(null); setActiveIndex(-1);
    };

    // Autofocus the description when the dialog opens — the fastest path for a
    // call taker is to start typing what the caller is saying immediately.
    useEffect(() => {
        if (isOpen) {
            setError(null); setErrorField(null); setLastLogged(null); setSessionCount(0);
            setRedirect(null); setOverrideJurisdiction(false);
            const t = setTimeout(() => descRef.current?.focus(), 120);
            return () => clearTimeout(t);
        }
    }, [isOpen]);

    // Load the map key, boundary and asset layers the first time the dialog is
    // opened, mirroring the resident portal. All optional: if the key is absent
    // the form falls back to a plain address text field.
    useEffect(() => {
        if (!isOpen || mapsRaw) return;
        api.getMapsConfig().then((config) => {
            setMapsRaw(config);
            if (config.township_boundary) setTownshipBoundary(config.township_boundary);
        }).catch(() => { });
        api.getMapLayers().then(setMapLayers).catch(() => { });
    }, [isOpen, mapsRaw]);

    /* The submit buttons used to be `disabled` until the form was already
     * valid, which is why an incomplete form produced nothing at all: a
     * disabled button is not reachable by Tab and swallows the click, so the
     * one thing that would have explained the problem — the validation message
     * — could never be asked for. The buttons stay enabled and the form
     * answers instead; only an in-flight save disables them, to stop a double
     * log. */

    /* WCAG 3.3.1 / 3.3.3 / 4.1.3. Three things have to happen together for a
     * call taker who cannot see the form: the message has to be announced (it
     * is the only evidence anything happened), focus has to move to the control
     * that is wrong (otherwise "pick a category" is advice with no address),
     * and the message has to be tied to that control with aria-describedby so
     * it is read again when they arrive. */
    const fail = (field: Exclude<ErrorField, null>, message: string) => {
        setError(message);
        setErrorField(field);
        announce(message, 'assertive');
        if (field === 'category') catButtonRef.current?.focus();
        else if (field === 'description') descRef.current?.focus();
        else if (emailRef.current) emailRef.current.focus();
        else {
            // The contact block is collapsed; open it before sending focus in.
            setShowContact(true);
            setTimeout(() => emailRef.current?.focus(), 60);
        }
    };

    const submit = async (mode: 'close' | 'another') => {
        if (saving !== null) return;
        if (!serviceCode) { fail('category', 'Pick a category for this request.'); return; }
        if (description.trim().length < 3) { fail('description', 'Add a short description of the issue.'); return; }
        if (email && !EMAIL_RE.test(email.trim())) { fail('email', 'That email address doesn’t look right.'); return; }
        setSaving(mode); setError(null); setErrorField(null);
        try {
            const created = await api.createManualIntake({
                service_code: serviceCode,
                description: description.trim(),
                address: address.trim() || undefined,
                lat: lat ?? undefined,
                long: lng ?? undefined,
                matched_asset: matchedAsset,
                first_name: firstName.trim() || undefined,
                last_name: lastName.trim() || undefined,
                email: email.trim() || undefined,
                phone: phone.trim() || undefined,
                is_public: hideFromPublic ? false : undefined,
                override_jurisdiction: overrideJurisdiction || undefined,
                source,
            });
            onCreated(created);
            setSessionCount(c => c + 1);
            setLastLogged(created.service_request_id);
            /* The only sign of success was a green strip appearing at the top
             * of a dialog that had just been reset — nothing a screen reader
             * reports on its own. Announced before the branch below, because
             * "log & take another" wipes the form under the announcement and
             * "log" closes the dialog outright. */
            announce(`Request ${created.service_request_id} logged.`);
            if (mode === 'another') {
                resetForm();
                setTimeout(() => descRef.current?.focus(), 80);
            } else {
                onClose();
            }
        } catch (e: any) {
            // The server returns the jurisdiction, the road and who to contact
            // rather than a bare error, so the clerk can read it to the caller.
            const detail = e?.detail ?? e?.body?.detail;
            if (detail?.error === 'redirected') {
                setRedirect({
                    jurisdiction: detail.jurisdiction ?? null,
                    message: detail.message ?? '',
                    road: detail.road ?? null,
                    contacts: detail.contacts ?? [],
                });
                setError(null); setErrorField(null);
                announce(
                    `${detail.jurisdiction || 'Another agency'} maintains this location. Tick “Log it anyway” to record it here.`,
                    'assertive',
                );
            } else {
                const message = e?.message || 'Could not log the request. Please try again.';
                setError(message); setErrorField(null);
                announce(message, 'assertive');
            }
        } finally {
            setSaving(null);
        }
    };

    const onKeyDown = (e: React.KeyboardEvent) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && saving === null) {
            e.preventDefault();
            submit('close');
        }
    };

    // A filtered list can be shorter than the cursor that was on it.
    useEffect(() => { setActiveIndex(-1); }, [catQuery]);

    const optionId = (code: string) => `intake-category-option-${code}`;

    const openCategories = (index = -1) => {
        setCatOpen(true);
        setActiveIndex(index);
    };

    const closeCategories = (returnFocus = true) => {
        setCatOpen(false);
        setCatQuery('');
        setActiveIndex(-1);
        if (returnFocus) catButtonRef.current?.focus();
    };

    const chooseCategory = (code: string) => {
        setServiceCode(code);
        if (errorField === 'category') { setError(null); setErrorField(null); }
        closeCategories();
    };

    /* The list used to be `<li><button role="option">`, which is an invalid
     * listbox — a listbox's children have to be options, and a button inside
     * one is neither reachable as an option nor announced as part of the list.
     * It was also mouse-only: nothing moved a keyboard cursor through it and
     * Escape did not dismiss it, so a keyboard user who opened the list had no
     * way to pick anything or to get back out.
     *
     * Now the filter input is the combobox, the options are the `<li>`s
     * themselves, and the cursor is `aria-activedescendant` — DOM focus stays
     * in the input while the arrows move the announced option, which is what
     * lets typing and choosing happen in the same gesture. */
    const onFilterKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        const count = filtered.length;
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            if (count === 0) return;
            const step = e.key === 'ArrowDown' ? 1 : -1;
            setActiveIndex(prev => {
                if (prev === -1) return step === 1 ? 0 : count - 1;
                return (prev + step + count) % count;
            });
        } else if (e.key === 'Home' && count > 0) {
            e.preventDefault(); setActiveIndex(0);
        } else if (e.key === 'End' && count > 0) {
            e.preventDefault(); setActiveIndex(count - 1);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const pick = activeIndex >= 0 ? filtered[activeIndex] : (filtered.length === 1 ? filtered[0] : null);
            if (pick) chooseCategory(pick.service_code);
        } else if (e.key === 'Escape') {
            // Stops the dialog's own Escape handler from closing the whole
            // form when the user only meant to dismiss the list.
            e.preventDefault();
            e.stopPropagation();
            closeCategories();
        } else if (e.key === 'Tab') {
            closeCategories(false);
        }
    };

    const onTriggerKeyDown = (e: React.KeyboardEvent<HTMLButtonElement>) => {
        if (!catOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
            e.preventDefault();
            openCategories(e.key === 'ArrowDown' ? 0 : Math.max(0, filtered.length - 1));
        }
    };

    // Keep the cursored option in view; jsdom has no scrollIntoView.
    useEffect(() => {
        if (!catOpen || activeIndex < 0) return;
        const el = listboxRef.current?.children[activeIndex] as HTMLElement | undefined;
        if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
    }, [catOpen, activeIndex]);

    const labelCls = 'text-[11px] uppercase tracking-wider text-white/60 mb-1.5 font-semibold block';
    const inputCls = 'w-full rounded-xl bg-white/[0.05] border border-white/12 text-white text-sm px-3.5 py-2.5 placeholder:text-white/40 transition-all focus:outline-none focus:border-primary-400/50 focus:bg-white/[0.08] focus:shadow-[0_0_0_3px_rgba(99,102,241,0.15)]';

    const copy = COPY[source];
    const PhoneIcon = copy.phoneIcon;

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title="Log a request"
            size="lg"
            panelClassName="bg-slate-900 bg-gradient-to-b from-slate-900 to-slate-950 border border-white/10 shadow-2xl shadow-black/60"
            headerClassName="bg-slate-900/95 backdrop-blur-xl"
        >
            <div className="space-y-5" onKeyDown={onKeyDown}>
                {/* Session counter — reassures a call taker doing back-to-back intake */}
                {sessionCount > 0 && (
                    <div className="flex items-center justify-between gap-2 rounded-xl bg-emerald-500/10 border border-emerald-400/25 px-3 py-2 text-xs text-emerald-200">
                        <span className="inline-flex items-center gap-1.5">
                            <CheckCircle className="w-3.5 h-3.5" aria-hidden="true" />
                            {lastLogged ? <>Logged <span className="font-semibold">{lastLogged}</span>.</> : 'Logged.'}
                        </span>
                        <span className="text-emerald-300/80">{sessionCount} this session</span>
                    </div>
                )}

                <p className="text-white/55 text-sm leading-relaxed">{copy.lead}</p>

                {/* How it came in */}
                <div>
                    {/* Named by the heading a sighted user reads, rather than by
                        a second wording only a screen reader ever hears. */}
                    <span className={labelCls} id="intake-source-label">How did it come in?</span>
                    <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-labelledby="intake-source-label">
                        {SOURCES.map(s => {
                            const isSel = source === s.value;
                            return (
                                <button
                                    key={s.value}
                                    type="button"
                                    role="radio"
                                    aria-checked={isSel}
                                    onClick={() => { setSource(s.value); if (s.value === 'email') setShowContact(true); }}
                                    className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 border text-sm font-medium transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 ${isSel
                                        ? 'bg-gradient-to-br from-primary-500/25 to-primary-700/15 border-primary-400/50 text-white shadow-lg shadow-primary-900/30'
                                        : 'bg-white/[0.03] border-white/10 text-white/70 hover:bg-white/[0.06] hover:border-white/20'}`}
                                >
                                    <s.icon className="w-4 h-4" aria-hidden="true" /> {s.label}
                                </button>
                            );
                        })}
                    </div>
                </div>

                {/* Category — searchable */}
                <div className="relative">
                    <label htmlFor="intake-category" className={labelCls}>Category <span className="normal-case tracking-normal text-amber-300 font-medium">(required)</span></label>
                    <button
                        type="button"
                        id="intake-category"
                        ref={catButtonRef}
                        onClick={() => (catOpen ? closeCategories(false) : openCategories())}
                        onKeyDown={onTriggerKeyDown}
                        aria-haspopup="listbox"
                        aria-expanded={catOpen}
                        /* The listbox is only in the DOM while open, so this is
                         * only meaningful while open. aria-haspopup above is what
                         * tells you a popup exists in the closed state. */
                        aria-controls={catOpen ? 'intake-category-listbox' : undefined}
                        aria-required="true"
                        aria-invalid={errorField === 'category' || undefined}
                        aria-describedby={errorField === 'category' ? 'intake-error' : undefined}
                        className={`${inputCls} flex items-center justify-between text-left ${selected ? '' : 'text-white/40'}`}
                    >
                        <span className="truncate">{selected ? selected.service_name : 'Choose a service category…'}</span>
                        <ChevronDown className="w-4 h-4 shrink-0 text-white/40" aria-hidden="true" />
                    </button>
                    <AnimatePresence>
                        {catOpen && (
                            <motion.div
                                initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                                className="absolute z-20 mt-1 w-full rounded-xl border border-white/15 bg-slate-800/95 backdrop-blur-xl shadow-2xl overflow-hidden"
                            >
                                <div className="p-2 border-b border-white/10">
                                    <div className="relative">
                                        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-white/40" aria-hidden="true" />
                                        <input
                                            autoFocus
                                            ref={catFilterRef}
                                            value={catQuery}
                                            onChange={e => setCatQuery(e.target.value)}
                                            onKeyDown={onFilterKeyDown}
                                            placeholder="Type to filter categories…"
                                            aria-label="Filter categories"
                                            role="combobox"
                                            aria-expanded="true"
                                            aria-controls="intake-category-listbox"
                                            aria-autocomplete="list"
                                            aria-activedescendant={activeIndex >= 0 && filtered[activeIndex]
                                                ? optionId(filtered[activeIndex].service_code)
                                                : undefined}
                                            className="w-full rounded-lg bg-white/[0.05] border border-white/10 text-white text-sm pl-8 pr-3 py-2 placeholder:text-white/40 focus:outline-none focus:border-primary-400/50"
                                        />
                                    </div>
                                </div>
                                <ul
                                    id="intake-category-listbox"
                                    ref={listboxRef}
                                    role="listbox"
                                    aria-label="Service categories"
                                    className="max-h-56 overflow-y-auto py-1"
                                >
                                    {filtered.length === 0 && (
                                        <li role="presentation" className="px-3 py-2 text-white/40 text-sm">No categories match “{catQuery}”.</li>
                                    )}
                                    {filtered.map((s, i) => {
                                        const isChosen = s.service_code === serviceCode;
                                        const isCursor = i === activeIndex;
                                        return (
                                            <li
                                                key={s.service_code}
                                                id={optionId(s.service_code)}
                                                role="option"
                                                aria-selected={isChosen}
                                                onClick={() => chooseCategory(s.service_code)}
                                                onMouseMove={() => setActiveIndex(i)}
                                                className={`cursor-pointer w-full text-left px-3 py-2 text-sm flex items-center justify-between gap-2 transition-colors ${isChosen ? 'bg-primary-500/20 text-white' : isCursor ? 'bg-white/10 text-white' : 'text-white/75'}`}
                                            >
                                                <span className="truncate">{s.service_name}</span>
                                                {isChosen && <CheckCircle className="w-4 h-4 text-primary-300 shrink-0" aria-hidden="true" />}
                                            </li>
                                        );
                                    })}
                                </ul>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>

                {/* Description */}
                <div>
                    <label htmlFor="intake-description" className={labelCls}>{copy.descLabel} <span className="normal-case tracking-normal text-amber-300 font-medium">(required)</span></label>
                    <textarea
                        id="intake-description"
                        ref={descRef}
                        value={description}
                        onChange={e => setDescription(e.target.value)}
                        rows={3}
                        required
                        aria-required="true"
                        aria-invalid={errorField === 'description' || undefined}
                        /* The hint is part of the field's instructions, so it is
                         * described here rather than left as loose text a screen
                         * reader only meets after the control. */
                        aria-describedby={`${errorField === 'description' ? 'intake-error ' : ''}intake-description-hint`}
                        placeholder={copy.descPlaceholder}
                        className={`${inputCls} resize-y min-h-[84px]`}
                    />
                    <p id="intake-description-hint" className="text-white/40 text-xs mt-1.5">AI triage sets a suggested priority automatically once you log it.</p>
                </div>

                {/* Callback number */}
                <div>
                    <label htmlFor="intake-phone" className={labelCls}>
                        {copy.phoneLabel}
                        <span className="normal-case tracking-normal text-white/40 font-normal ml-1">(optional)</span>
                    </label>
                    <div className="relative">
                        <PhoneIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-white/35" aria-hidden="true" />
                        <input id="intake-phone" value={phone} onChange={e => setPhone(e.target.value)} inputMode="tel"
                            placeholder={copy.phonePlaceholder} className={`${inputCls} pl-9`} />
                    </div>
                </div>

                {/* Location — the same picker residents use: search an address or
                    drop a pin on the map, geolocated identically to an online report. */}
                <div>
                    {/* Only the fallback branch is a single labelable control;
                        the picker is a composite, so it gets a group label
                        rather than a `for` pointing at nothing. */}
                    {mapProviderReady(mapsRaw)
                        ? <span className={labelCls}>Location <span className="normal-case tracking-normal text-white/40 font-normal ml-1">(optional)</span></span>
                        : <label htmlFor="intake-address" className={labelCls}>Location <span className="normal-case tracking-normal text-white/40 font-normal ml-1">(optional)</span></label>}
                    {mapProviderReady(mapsRaw) ? (
                        <LocationPicker
                            key={mapKey}
                            config={mapConfig}
                            townshipBoundary={townshipBoundary}
                            customLayers={mapLayers.filter(layer => {
                                if ((layer as any).visible_on_map === false) return false;
                                const codes = layer.service_codes || [];
                                if (codes.length === 0) return true;
                                return selected ? codes.includes(selected.service_code) : false;
                            })}
                            value={{ address, lat, lng }}
                            onChange={(loc) => { setAddress(loc.address); setLat(loc.lat); setLng(loc.lng); }}
                            onAssetSelect={(asset) => setMatchedAsset(asset)}
                            placeholder="Search for an address or click on the map…"
                        />
                    ) : (
                        <div className="relative">
                            <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-white/35" aria-hidden="true" />
                            <input id="intake-address" value={address} onChange={e => setAddress(e.target.value)}
                                placeholder="123 Main St, or nearest intersection" className={`${inputCls} pl-9`} />
                        </div>
                    )}
                </div>

                {/* Optional caller contact */}
                <div>
                    <button
                        type="button"
                        onClick={() => setShowContact(v => !v)}
                        className="inline-flex items-center gap-1.5 text-xs font-medium text-white/55 hover:text-white/85 transition-colors"
                        aria-expanded={showContact}
                    >
                        <UserIcon className="w-3.5 h-3.5" aria-hidden="true" />
                        {copy.contactToggle}
                        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showContact ? 'rotate-180' : ''}`} aria-hidden="true" />
                    </button>
                    <AnimatePresence initial={false}>
                        {showContact && (
                            <motion.div
                                initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                                className="overflow-hidden"
                            >
                                <p className="text-white/40 text-xs pt-2.5">{copy.contactBlurb}</p>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-3">
                                    <div>
                                        <label htmlFor="intake-first-name" className={labelCls}>First name</label>
                                        <input id="intake-first-name" value={firstName} onChange={e => setFirstName(e.target.value)} className={inputCls} />
                                    </div>
                                    <div>
                                        <label htmlFor="intake-last-name" className={labelCls}>Last name</label>
                                        <input id="intake-last-name" value={lastName} onChange={e => setLastName(e.target.value)} className={inputCls} />
                                    </div>
                                    <div className="sm:col-span-2">
                                        <label htmlFor="intake-email" className={labelCls}>{copy.emailLabel}</label>
                                        <input id="intake-email" ref={emailRef} value={email} onChange={e => setEmail(e.target.value)} type="email" inputMode="email"
                                            aria-invalid={errorField === 'email' || undefined}
                                            aria-describedby={errorField === 'email' ? 'intake-error' : undefined}
                                            placeholder={copy.emailPlaceholder} className={inputCls} />
                                    </div>
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>

                {(settings?.modules?.unlisted_reports ?? (settings?.modules as any)?.private_reports) && (
                    <label className="flex items-start gap-3 cursor-pointer rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-3">
                        <input
                            type="checkbox"
                            checked={hideFromPublic}
                            onChange={e => setHideFromPublic(e.target.checked)}
                            className="mt-0.5 w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500 shrink-0"
                        />
                        <span className="min-w-0">
                            <span className="flex items-center gap-1.5 text-sm font-medium text-white">
                                <EyeOff className="w-3.5 h-3.5 text-white/50" aria-hidden="true" /> Hide from the public map and feed
                            </span>
                            <span className="block text-[11px] text-white/50 mt-1 leading-relaxed">
                                Check only if the resident asked to keep it unlisted. Staff still see and work it
                                normally, the tracking link still works, and it still counts in anonymized statistics.
                            </span>
                        </span>
                    </label>
                )}

                {redirect && (
                    <div className="rounded-xl bg-gradient-to-br from-amber-500/[0.12] to-orange-500/[0.08] border border-amber-400/30 p-4 space-y-3">
                        <div className="flex items-start gap-3">
                            <div className="w-9 h-9 rounded-full bg-amber-500/20 flex items-center justify-center shrink-0">
                                <SignpostBig className="w-4.5 h-4.5 text-amber-300" aria-hidden="true" />
                            </div>
                            <div className="min-w-0">
                                <p className="text-sm font-semibold text-amber-200">
                                    {redirect.jurisdiction
                                        ? `${redirect.jurisdiction} maintains this location`
                                        : 'Another agency maintains this location'}
                                </p>
                                {redirect.road && (
                                    <p className="text-xs text-white/50 mt-0.5">
                                        Detected road: <span className="text-white/75">{redirect.road}</span>
                                    </p>
                                )}
                                {redirect.message && (
                                    <p className="text-sm text-white/70 mt-2 leading-relaxed">{redirect.message}</p>
                                )}
                                {redirect.contacts.length > 0 && (
                                    <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-xs">
                                        {redirect.contacts.map((c, i) => (
                                            <span key={i} className="text-white/60">
                                                {c.name && <span className="text-white/80 font-medium">{c.name}</span>}
                                                {c.phone && <> &middot; <a href={`tel:${c.phone}`} className="text-primary-300 hover:text-primary-200">{c.phone}</a></>}
                                                {c.url && <> &middot; <a href={c.url} target="_blank" rel="noopener noreferrer" className="text-primary-300 hover:text-primary-200">Website</a></>}
                                            </span>
                                        ))}
                                    </div>
                                )}
                            </div>
                        </div>
                        <label className="flex items-start gap-3 cursor-pointer rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2.5">
                            <input
                                type="checkbox"
                                checked={overrideJurisdiction}
                                onChange={e => setOverrideJurisdiction(e.target.checked)}
                                className="mt-0.5 w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500 shrink-0"
                            />
                            <span className="min-w-0">
                                <span className="block text-sm font-medium text-white">Log it anyway</span>
                                <span className="block text-[11px] text-white/50 mt-0.5 leading-relaxed">
                                    Records the report here so it is not lost. Your town still has to forward it.
                                </span>
                            </span>
                        </label>
                    </div>
                )}

                {error && (
                    /* role="alert" is what makes the message reach somebody who
                     * is not looking at this corner of the dialog. The id is
                     * pointed at by whichever field is at fault, so arriving
                     * there reads the reason as well as the label. The message
                     * is also passed to announce() at the moment it is set —
                     * a role="alert" that renders in the same tick as its text
                     * is announced inconsistently across screen readers. */
                    <div id="intake-error" role="alert" className="rounded-xl bg-amber-500/10 border border-amber-400/30 px-3 py-2.5 text-sm text-amber-200 flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" aria-hidden="true" /> {error}
                    </div>
                )}

                {/* Actions */}
                <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3 pt-1 border-t border-white/10">
                    <button
                        type="button"
                        onClick={onClose}
                        className="inline-flex items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-medium text-white/70 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 transition-colors"
                    >
                        <X className="w-4 h-4" aria-hidden="true" /> Close
                    </button>
                    <div className="flex flex-col-reverse sm:flex-row gap-2">
                        <button
                            type="button"
                            onClick={() => submit('another')}
                            disabled={saving !== null}
                            className="inline-flex items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-medium text-white/85 hover:text-white bg-white/5 hover:bg-white/10 border border-white/15 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                        >
                            {saving === 'another' ? <><Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Saving…</> : <>Log &amp; take another</>}
                        </button>
                        <button
                            type="button"
                            onClick={() => submit('close')}
                            disabled={saving !== null}
                            className="shimmer-sweep inline-flex items-center justify-center gap-1.5 rounded-xl px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 shadow-lg shadow-primary-900/40 transition-all hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                        >
                            {saving === 'close' ? <><Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" /> Logging…</> : <><Sparkles className="w-4 h-4" aria-hidden="true" /> {copy.logCta}</>}
                        </button>
                    </div>
                </div>
                <p className="text-white/60 text-[11px] text-right -mt-2">Tip: press ⌘/Ctrl + Enter to log.</p>
            </div>
        </Modal>
    );
}
