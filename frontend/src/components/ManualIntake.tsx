import { useEffect, useMemo, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Phone, Mail, Footprints, Search, CheckCircle, Loader2, Sparkles,
    ChevronDown, MapPin, User as UserIcon, X, AlertCircle,
} from 'lucide-react';

import { Modal } from './ui';
import { api } from '../services/api';
import { ServiceDefinition, ServiceRequest } from '../types';

type Source = 'phone' | 'email' | 'walk_in';

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
    const [source, setSource] = useState<Source>('phone');
    const [serviceCode, setServiceCode] = useState('');
    const [catQuery, setCatQuery] = useState('');
    const [catOpen, setCatOpen] = useState(false);
    const [description, setDescription] = useState('');
    const [phone, setPhone] = useState('');
    const [address, setAddress] = useState('');
    const [showContact, setShowContact] = useState(false);
    const [firstName, setFirstName] = useState('');
    const [lastName, setLastName] = useState('');
    const [email, setEmail] = useState('');

    const [saving, setSaving] = useState<'close' | 'another' | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [lastLogged, setLastLogged] = useState<string | null>(null);
    const [sessionCount, setSessionCount] = useState(0);

    const descRef = useRef<HTMLTextAreaElement>(null);

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
        setShowContact(false); setFirstName(''); setLastName(''); setEmail('');
        setError(null);
    };

    // Autofocus the description when the dialog opens — the fastest path for a
    // call taker is to start typing what the caller is saying immediately.
    useEffect(() => {
        if (isOpen) {
            setError(null); setLastLogged(null); setSessionCount(0);
            const t = setTimeout(() => descRef.current?.focus(), 120);
            return () => clearTimeout(t);
        }
    }, [isOpen]);

    const canSubmit = !!serviceCode && description.trim().length >= 3 && saving === null;

    const submit = async (mode: 'close' | 'another') => {
        if (!serviceCode) { setError('Pick a category for this request.'); return; }
        if (description.trim().length < 3) { setError('Add a short description of the issue.'); return; }
        if (email && !EMAIL_RE.test(email.trim())) { setError('That email address doesn’t look right.'); return; }
        setSaving(mode); setError(null);
        try {
            const created = await api.createManualIntake({
                service_code: serviceCode,
                description: description.trim(),
                address: address.trim() || undefined,
                first_name: firstName.trim() || undefined,
                last_name: lastName.trim() || undefined,
                email: email.trim() || undefined,
                phone: phone.trim() || undefined,
                source,
            });
            onCreated(created);
            setSessionCount(c => c + 1);
            setLastLogged(created.service_request_id);
            if (mode === 'another') {
                resetForm();
                setTimeout(() => descRef.current?.focus(), 80);
            } else {
                onClose();
            }
        } catch (e: any) {
            setError(e?.message || 'Could not log the request. Please try again.');
        } finally {
            setSaving(null);
        }
    };

    const onKeyDown = (e: React.KeyboardEvent) => {
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter' && canSubmit) {
            e.preventDefault();
            submit('close');
        }
    };

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
                            <CheckCircle className="w-3.5 h-3.5" />
                            {lastLogged ? <>Logged <span className="font-semibold">{lastLogged}</span>.</> : 'Logged.'}
                        </span>
                        <span className="text-emerald-300/80">{sessionCount} this session</span>
                    </div>
                )}

                <p className="text-white/55 text-sm leading-relaxed">{copy.lead}</p>

                {/* How it came in */}
                <div>
                    <span className={labelCls}>How did it come in?</span>
                    <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Intake source">
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
                    <span className={labelCls}>Category <span className="normal-case tracking-normal text-amber-300 font-medium">(required)</span></span>
                    <button
                        type="button"
                        onClick={() => setCatOpen(o => !o)}
                        aria-haspopup="listbox"
                        aria-expanded={catOpen}
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
                                            value={catQuery}
                                            onChange={e => setCatQuery(e.target.value)}
                                            placeholder="Type to filter categories…"
                                            aria-label="Filter categories"
                                            className="w-full rounded-lg bg-white/[0.05] border border-white/10 text-white text-sm pl-8 pr-3 py-2 placeholder:text-white/40 focus:outline-none focus:border-primary-400/50"
                                        />
                                    </div>
                                </div>
                                <ul role="listbox" className="max-h-56 overflow-y-auto py-1">
                                    {filtered.length === 0 && (
                                        <li className="px-3 py-2 text-white/40 text-sm">No categories match “{catQuery}”.</li>
                                    )}
                                    {filtered.map(s => (
                                        <li key={s.service_code}>
                                            <button
                                                type="button"
                                                role="option"
                                                aria-selected={s.service_code === serviceCode}
                                                onClick={() => { setServiceCode(s.service_code); setCatOpen(false); setCatQuery(''); }}
                                                className={`w-full text-left px-3 py-2 text-sm flex items-center justify-between gap-2 transition-colors ${s.service_code === serviceCode ? 'bg-primary-500/20 text-white' : 'text-white/75 hover:bg-white/5'}`}
                                            >
                                                <span className="truncate">{s.service_name}</span>
                                                {s.service_code === serviceCode && <CheckCircle className="w-4 h-4 text-primary-300 shrink-0" />}
                                            </button>
                                        </li>
                                    ))}
                                </ul>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>

                {/* Description */}
                <div>
                    <span className={labelCls}>{copy.descLabel} <span className="normal-case tracking-normal text-amber-300 font-medium">(required)</span></span>
                    <textarea
                        ref={descRef}
                        value={description}
                        onChange={e => setDescription(e.target.value)}
                        rows={3}
                        placeholder={copy.descPlaceholder}
                        className={`${inputCls} resize-y min-h-[84px]`}
                    />
                    <p className="text-white/40 text-xs mt-1.5">AI triage sets a suggested priority automatically once you log it.</p>
                </div>

                {/* Callback + address */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                        <span className={labelCls}>
                            {copy.phoneLabel}
                            <span className="normal-case tracking-normal text-white/40 font-normal ml-1">(optional)</span>
                        </span>
                        <div className="relative">
                            <PhoneIcon className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-white/35" aria-hidden="true" />
                            <input value={phone} onChange={e => setPhone(e.target.value)} inputMode="tel"
                                placeholder={copy.phonePlaceholder} className={`${inputCls} pl-9`} />
                        </div>
                    </div>
                    <div>
                        <span className={labelCls}>Location <span className="normal-case tracking-normal text-white/40 font-normal ml-1">(optional)</span></span>
                        <div className="relative">
                            <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-white/35" aria-hidden="true" />
                            <input value={address} onChange={e => setAddress(e.target.value)}
                                placeholder="123 Main St, or nearest intersection" className={`${inputCls} pl-9`} />
                        </div>
                    </div>
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
                                        <span className={labelCls}>First name</span>
                                        <input value={firstName} onChange={e => setFirstName(e.target.value)} className={inputCls} />
                                    </div>
                                    <div>
                                        <span className={labelCls}>Last name</span>
                                        <input value={lastName} onChange={e => setLastName(e.target.value)} className={inputCls} />
                                    </div>
                                    <div className="sm:col-span-2">
                                        <span className={labelCls}>{copy.emailLabel}</span>
                                        <input value={email} onChange={e => setEmail(e.target.value)} type="email" inputMode="email"
                                            placeholder={copy.emailPlaceholder} className={inputCls} />
                                    </div>
                                </div>
                            </motion.div>
                        )}
                    </AnimatePresence>
                </div>

                {error && (
                    <div className="rounded-xl bg-amber-500/10 border border-amber-400/30 px-3 py-2.5 text-sm text-amber-200 flex items-start gap-2">
                        <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" /> {error}
                    </div>
                )}

                {/* Actions */}
                <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3 pt-1 border-t border-white/10">
                    <button
                        type="button"
                        onClick={onClose}
                        className="inline-flex items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-medium text-white/70 hover:text-white bg-white/5 hover:bg-white/10 border border-white/10 transition-colors"
                    >
                        <X className="w-4 h-4" /> Close
                    </button>
                    <div className="flex flex-col-reverse sm:flex-row gap-2">
                        <button
                            type="button"
                            onClick={() => submit('another')}
                            disabled={!canSubmit}
                            className="inline-flex items-center justify-center gap-1.5 rounded-xl px-4 py-2.5 text-sm font-medium text-white/85 hover:text-white bg-white/5 hover:bg-white/10 border border-white/15 transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                        >
                            {saving === 'another' ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving…</> : <>Log &amp; take another</>}
                        </button>
                        <button
                            type="button"
                            onClick={() => submit('close')}
                            disabled={!canSubmit}
                            className="shimmer-sweep inline-flex items-center justify-center gap-1.5 rounded-xl px-5 py-2.5 text-sm font-semibold text-white bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500 shadow-lg shadow-primary-900/40 transition-all hover:-translate-y-0.5 disabled:opacity-50 disabled:hover:translate-y-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                        >
                            {saving === 'close' ? <><Loader2 className="w-4 h-4 animate-spin" /> Logging…</> : <><Sparkles className="w-4 h-4" /> {copy.logCta}</>}
                        </button>
                    </div>
                </div>
                <p className="text-white/60 text-[11px] text-right -mt-2">Tip: press ⌘/Ctrl + Enter to log.</p>
            </div>
        </Modal>
    );
}
