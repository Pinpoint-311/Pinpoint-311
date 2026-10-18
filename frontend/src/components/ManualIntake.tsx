import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { resolveMapProviderConfig, mapProviderReady, RawMapsConfig, isPointInGeoJson } from '../maps';
import { motion, AnimatePresence } from 'framer-motion';
import {
    Phone, Mail, Search, CheckCircle, CheckCircle2, ChevronDown, MapPin, MapPinOff,
    User as UserIcon, X, EyeOff, SignpostBig, MessageSquare, Siren, Layers,
    Copy, Check, ExternalLink, Plus, UserPlus, Settings2, History, AlertTriangle, Camera,
} from 'lucide-react';

import { Modal, Button, Input, Textarea, Select, StatusBadge } from './ui';
import { api, MapLayer } from '../services/api';
import LocationPicker from './LocationPicker';
import PhotoUpload from './PhotoUpload';
import RedirectNotice, { RedirectContact } from './RedirectNotice';
import CustomQuestionFields, { isUnanswered } from './CustomQuestionFields';
import { categoryIconFor } from './categoryIcons';
import { usePhotoAttachments } from '../hooks/usePhotoAttachments';
import { filterPhoneInput, isValidPhone } from '../utils/phone';
import { LANGUAGES } from '../utils/languages';
import {
    Department, ResidentHistoryItem, ServiceDefinition, ServiceRequest, User,
} from '../types';
import { useSettings } from '../context/SettingsContext';
import { useAnnounce } from '../context/AccessibilityContext';

type Source = 'phone' | 'email' | 'walk_in' | 'other';

// How the report reached the town. Recorded on the request (statistics,
// exports, the work order, connected systems), so it stays -- but as one
// compact selector, not four big buttons, and the form no longer rewords
// itself per channel.
const SOURCES: { value: Source; label: string }[] = [
    { value: 'phone', label: 'Phone' },
    { value: 'email', label: 'Email' },
    { value: 'walk_in', label: 'In person' },
    { value: 'other', label: 'Other' },
];

// One wording for every channel, so the form doesn't change under the clerk.
const COPY = {
    who: 'resident',
    descLabel: 'What is being reported?',
    descPlaceholder: 'Large pothole in the eastbound lane of Main St near the library.',
    phoneLabel: 'Phone number',
    contactToggle: 'Resident details',
    contactBlurb: 'Needed only for a status update or a callback.',
    emailLabel: 'Email',
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MIN_DESCRIPTION = 10;
const RECENT_KEY = 'pinpoint.intake.recentCategories';
const RECENT_MAX = 3;
const DUPLICATE_RADIUS_M = 150;

/* Field ids are fixed so the error summary can link straight at them. */
const FIELD = {
    category: 'intake-category',
    description: 'intake-description',
    phone: 'intake-phone',
    email: 'intake-email',
    override: 'intake-override',
} as const;
const customFieldId = (questionId: string) => `intake-custom-${questionId}`;

interface ManualIntakeProps {
    isOpen: boolean;
    onClose: () => void;
    services: ServiceDefinition[];
    onCreated: (request: ServiceRequest) => void;
    /** Requests the dashboard already holds, for the nearby-duplicate check. */
    requests?: ServiceRequest[];
    /** For the staff options. Fetched on first use when not passed. */
    departments?: Department[];
    staff?: User[];
    /** Open an existing request in the dashboard. */
    onOpenRequest?: (serviceRequestId: string) => void;
}

type Redirect = {
    variant: 'road' | 'service';
    jurisdiction: string | null;
    message: string;
    messageIsDefault: boolean;
    contacts: RedirectContact[];
    road: string | null;
};

type SelectedAsset = { layerName: string; properties: Record<string, any>; lat: number; lng: number };

function readRecent(): string[] {
    try {
        const raw = JSON.parse(localStorage.getItem(RECENT_KEY) || '[]');
        return Array.isArray(raw) ? raw.filter((c): c is string => typeof c === 'string').slice(0, RECENT_MAX) : [];
    } catch {
        return [];
    }
}

function rememberRecent(code: string): string[] {
    const next = [code, ...readRecent().filter(c => c !== code)].slice(0, RECENT_MAX);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch { /* private window */ }
    return next;
}

/** Great-circle distance in meters. Plenty accurate at 150 m. */
function distanceMeters(lat1: number, lng1: number, lat2: number, lng2: number): number {
    const rad = Math.PI / 180;
    const dLat = (lat2 - lat1) * rad;
    const dLng = (lng2 - lng1) * rad;
    const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dLng / 2) ** 2;
    return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

/** A section heading with the platform's gradient icon tile. */
function SectionHeading({ icon: Icon, title, id, aside }: {
    icon: typeof Phone; title: string; id?: string; aside?: React.ReactNode;
}) {
    return (
        <div className="flex items-center justify-between gap-3 mb-4">
            <div className="flex items-center gap-3 min-w-0">
                <div className="p-2 rounded-xl bg-gradient-to-br from-primary-500/20 to-purple-500/20 ring-1 ring-white/10 shrink-0" aria-hidden="true">
                    <Icon className="w-4 h-4 text-primary-200" />
                </div>
                <h3 id={id} className="text-sm font-semibold text-white tracking-tight">{title}</h3>
            </div>
            {aside}
        </div>
    );
}

/** A section that opens on demand. The heading holds the toggle, so it is
 *  reachable from the headings list as well as by Tab. */
function Disclosure({ icon: Icon, title, hint, open, onToggle, panelId, children }: {
    icon: typeof Phone; title: string; hint?: string; open: boolean; onToggle: () => void;
    panelId: string; children: React.ReactNode;
}) {
    return (
        <section className="rounded-2xl border border-white/10 bg-white/[0.03]">
            <h3 className="m-0">
                <button
                    type="button"
                    onClick={onToggle}
                    aria-expanded={open}
                    aria-controls={panelId}
                    className="w-full flex items-center gap-3 p-4 text-left rounded-2xl focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60"
                >
                    <span className="p-2 rounded-xl bg-gradient-to-br from-primary-500/20 to-purple-500/20 ring-1 ring-white/10 shrink-0" aria-hidden="true">
                        <Icon className="w-4 h-4 text-primary-200" />
                    </span>
                    <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold text-white">
                            {title} <span className="font-normal text-white/45">(optional)</span>
                        </span>
                        {hint && <span className="block text-xs text-white/50 mt-0.5">{hint}</span>}
                    </span>
                    <ChevronDown className={`w-4 h-4 text-white/50 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} aria-hidden="true" />
                </button>
            </h3>
            <AnimatePresence initial={false}>
                {open && (
                    <motion.div
                        id={panelId}
                        initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }}
                        className="overflow-hidden"
                    >
                        <div className="px-4 pb-4 space-y-4">{children}</div>
                    </motion.div>
                )}
            </AnimatePresence>
        </section>
    );
}

const labelCls = 'block text-sm font-medium text-white/70 mb-2';

export default function ManualIntake({
    isOpen, onClose, services, onCreated, requests = [], departments: departmentsProp, staff: staffProp, onOpenRequest,
}: ManualIntakeProps) {
    const { settings } = useSettings();
    const announce = useAnnounce();

    const [source, setSource] = useState<Source>('phone');
    const [serviceCode, setServiceCode] = useState('');
    const [catQuery, setCatQuery] = useState('');
    const [catOpen, setCatOpen] = useState(false);
    // Which option the combobox keyboard cursor is on; -1 is "none yet".
    const [activeIndex, setActiveIndex] = useState(-1);
    const [recent, setRecent] = useState<string[]>(() => readRecent());
    const [description, setDescription] = useState('');
    const [customAnswers, setCustomAnswers] = useState<Record<string, string | string[]>>({});

    // Location — the same picker residents use, so a call taker can drop a pin
    // or search an address and the request is geolocated identically.
    const [address, setAddress] = useState('');
    const [lat, setLat] = useState<number | null>(null);
    const [lng, setLng] = useState<number | null>(null);
    const [selectedAsset, setSelectedAsset] = useState<SelectedAsset | null>(null);
    const [outOfBounds, setOutOfBounds] = useState(false);
    const [detectedRoad, setDetectedRoad] = useState<{ name: string; distance_m: number } | null>(null);
    const [mapsRaw, setMapsRaw] = useState<RawMapsConfig | null>(null);
    const mapConfig = useMemo(() => resolveMapProviderConfig(mapsRaw), [mapsRaw]);
    const [townshipBoundary, setTownshipBoundary] = useState<object | null>(null);
    const [mapLayers, setMapLayers] = useState<MapLayer[]>([]);
    // Bumped on reset so the map picker remounts clean between back-to-back logs.
    const [mapKey, setMapKey] = useState(0);

    // A location another agency maintains, or a category another agency
    // handles. A clerk on the phone can still choose to log it -- the caller
    // is elderly, the town forwards these anyway, it is faster than
    // explaining. Residents get no such choice; staff judgement is the point
    // of the role.
    const [redirect, setRedirect] = useState<Redirect | null>(null);
    const [overrideJurisdiction, setOverrideJurisdiction] = useState(false);
    const roadCheckSeq = useRef(0);

    // Contact. Staff type someone else's details, so autofill is off.
    const [phone, setPhone] = useState('');
    const [showContact, setShowContact] = useState(false);
    const [firstName, setFirstName] = useState('');
    const [lastName, setLastName] = useState('');
    const [email, setEmail] = useState('');
    const [language, setLanguage] = useState('en');
    // Honors a caller who asks not to be listed publicly — same rule as the
    // resident form, and only offered when the town enabled the module.
    const [hideFromPublic, setHideFromPublic] = useState(false);
    const [callerHistory, setCallerHistory] = useState<{ email: string; total: number; reports: ResidentHistoryItem[] } | null>(null);
    const [showCallerHistory, setShowCallerHistory] = useState(false);
    const lookedUpEmail = useRef<string | null>(null);

    // Staff options. Blank means "decide it the way a resident report would".
    const [showStaff, setShowStaff] = useState(false);
    const [departmentId, setDepartmentId] = useState('');
    const [assignee, setAssignee] = useState('');
    const [priority, setPriority] = useState('');
    const [staffNotes, setStaffNotes] = useState('');
    const [sendConfirmation, setSendConfirmation] = useState(true);
    const [fetchedDepartments, setFetchedDepartments] = useState<Department[] | null>(null);
    const [fetchedStaff, setFetchedStaff] = useState<User[] | null>(null);

    const photos = usePhotoAttachments({ blockedVerdict: 'attach' });

    const [saving, setSaving] = useState(false);
    const [errors, setErrors] = useState<Record<string, string>>({});
    const [errorSummary, setErrorSummary] = useState<{ fieldId: string; message: string }[]>([]);
    const [submitError, setSubmitError] = useState<string | null>(null);
    const [created, setCreated] = useState<ServiceRequest | null>(null);
    const [createdNotes, setCreatedNotes] = useState<{ confirmationTo: string | null }>({ confirmationTo: null });
    const [sessionCount, setSessionCount] = useState(0);
    const [linkCopied, setLinkCopied] = useState(false);

    const descRef = useRef<HTMLTextAreaElement>(null);
    const catButtonRef = useRef<HTMLButtonElement>(null);
    const errorSummaryRef = useRef<HTMLDivElement>(null);
    const successHeadingRef = useRef<HTMLHeadingElement>(null);
    const loggedRef = useRef(false);

    const active = useMemo(() => services.filter(s => s.is_active !== false), [services]);
    const selected = active.find(s => s.service_code === serviceCode);
    const locationMode = selected?.location_mode || 'optional';
    const questions = selected?.routing_config?.custom_questions ?? [];

    /* The options in the order they are shown and walked by the arrows: with
     * no filter, recently used categories first. One flat list, so an option's
     * id and its arrow-key position can never disagree. */
    const { options, recentCount } = useMemo(() => {
        const q = catQuery.trim().toLowerCase();
        if (q) {
            return {
                options: active.filter(s =>
                    s.service_name.toLowerCase().includes(q)
                    || s.service_code.toLowerCase().includes(q)
                    || (s.description || '').toLowerCase().includes(q)),
                recentCount: 0,
            };
        }
        const recents = recent.map(c => active.find(s => s.service_code === c)).filter((s): s is ServiceDefinition => !!s);
        const rest = active.filter(s => !recent.includes(s.service_code));
        return { options: [...recents, ...rest], recentCount: recents.length };
    }, [active, catQuery, recent]);

    const departments = departmentsProp ?? fetchedDepartments ?? [];
    const staff = staffProp ?? fetchedStaff ?? [];
    const emailIsValid = EMAIL_RE.test(email.trim());

    const copy = COPY;

    /* ---------------------------------------------------------- lifecycle */

    // Autofocus the description when the dialog opens — the fastest path for a
    // call taker is to start typing what the caller is saying immediately.
    useEffect(() => {
        if (isOpen) {
            // A form closed on its success panel still holds what was just
            // logged; reopening it must not invite logging it twice. A form
            // closed mid-entry keeps what was typed.
            if (loggedRef.current) {
                loggedRef.current = false;
                resetForm(false);
            }
            setErrorSummary([]); setErrors({}); setSubmitError(null);
            setCreated(null); setSessionCount(0);
            const t = setTimeout(() => descRef.current?.focus(), 120);
            return () => clearTimeout(t);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps -- runs on open only
    }, [isOpen]);

    // Map key, boundary and asset layers, the first time the dialog opens. All
    // optional: without a provider the form falls back to a plain address field.
    useEffect(() => {
        if (!isOpen || mapsRaw) return;
        api.getMapsConfig().then((config) => {
            setMapsRaw(config);
            if (config.township_boundary) setTownshipBoundary(config.township_boundary);
        }).catch(() => { });
        api.getMapLayers().then(setMapLayers).catch(() => { });
    }, [isOpen, mapsRaw]);

    // The staff lists, when the dashboard did not pass them, on first use.
    useEffect(() => {
        if (!showStaff) return;
        if (!departmentsProp && fetchedDepartments === null) {
            api.getDepartments().then(setFetchedDepartments).catch(() => setFetchedDepartments([]));
        }
        if (!staffProp && fetchedStaff === null) {
            api.getStaffMembers().then(setFetchedStaff).catch(() => setFetchedStaff([]));
        }
    }, [showStaff, departmentsProp, staffProp, fetchedDepartments, fetchedStaff]);

    /* An effect rather than a call inside the validator: the summary is created
     * by the same state update, so at that moment there is nothing to focus.
     * A fresh array on every failed attempt brings focus back here on a second
     * press rather than leaving it on a button that seems to do nothing. */
    useEffect(() => {
        if (errorSummary.length > 0) errorSummaryRef.current?.focus();
    }, [errorSummary]);

    useEffect(() => {
        if (created) successHeadingRef.current?.focus();
    }, [created]);

    /* ------------------------------------------------- jurisdiction check */

    /* Ask the server whether a report here would be redirected, the same
     * courtesy check the resident form makes -- before the clerk has typed a
     * description, not after they press Log. It fails open: a check that
     * errors never blocks, and the server re-checks on submit anyway. */
    const checkRoad = useCallback(async (service: ServiceDefinition, pinLat: number, pinLng: number) => {
        const seq = ++roadCheckSeq.current;
        try {
            const result = await api.roadCheck(service.service_code, pinLat, pinLng);
            if (seq !== roadCheckSeq.current) return;
            setDetectedRoad(result.detected_road);
            setRedirect(result.blocked ? {
                variant: 'road',
                jurisdiction: result.jurisdiction,
                message: result.message || '',
                messageIsDefault: Boolean(result.message_is_default),
                contacts: (result.contacts || []).map(c => ({
                    name: c.name || '', phone: c.phone || '', email: c.email || '', url: c.url || '',
                })),
                road: result.detected_road?.name ?? result.road ?? null,
            } : null);
            if (!result.blocked) setOverrideJurisdiction(false);
            // One announcement for one event (WCAG 4.1.3), as on the resident form.
            const road = result.detected_road?.name;
            const who = result.jurisdiction || 'another agency';
            const sentence = result.blocked
                ? road
                    ? `Road detected: ${road}. ${road} is handled by ${who}. Contact details are shown below.`
                    : `This location is handled by ${who}. Contact details are shown below.`
                : road ? `Road detected: ${road}.` : '';
            if (sentence) announce(sentence);
        } catch {
            if (seq !== roadCheckSeq.current) return;
            setDetectedRoad(null);
            setRedirect(null);
        }
    }, [announce]);

    // Re-run whenever the pin or the category changes: on the phone the clerk
    // often drops the pin before they know which category it is.
    useEffect(() => {
        if (!selected || selected.routing_mode !== 'road_based' || lat == null || lng == null) return;
        void checkRoad(selected, lat, lng);
    }, [selected, lat, lng, checkRoad]);

    /* ------------------------------------------------------------ category */

    const chooseCategory = (code: string) => {
        const service = active.find(s => s.service_code === code);
        if (code !== serviceCode) {
            // A different category asks different questions, may route
            // elsewhere and may not match the asset that was picked.
            setCustomAnswers({});
            setSelectedAsset(null);
            setDetectedRoad(null);
            setOverrideJurisdiction(false);
            roadCheckSeq.current++;
            if (service?.routing_mode === 'third_party') {
                const rc = service.routing_config || {};
                setRedirect({
                    variant: 'service',
                    // Same fallback the backend uses: no agency-name field
                    // exists, so the first contact's name is who was named.
                    jurisdiction: rc.third_party_name || rc.contacts?.[0]?.name || null,
                    message: rc.message || '',
                    messageIsDefault: !(rc.message || '').trim(),
                    contacts: rc.contacts || [],
                    road: null,
                });
                announce(`${service.service_name} reports are handled by ${rc.third_party_name || rc.contacts?.[0]?.name || 'another agency'}. Contact details are shown below.`);
            } else {
                setRedirect(null);
            }
        }
        setServiceCode(code);
        if (errors.category) clearError('category');
        closeCategories();
    };

    const clearError = (key: string) => {
        setErrors(prev => {
            if (!prev[key]) return prev;
            const next = { ...prev };
            delete next[key];
            return next;
        });
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

    /* The filter input is the combobox, the options are the `<li>`s
     * themselves, and the cursor is `aria-activedescendant` -- DOM focus stays
     * in the input while the arrows move the announced option, which is what
     * lets typing and choosing happen in the same gesture. */
    const onFilterKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        const count = options.length;
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
            // Never also submit the form from here.
            e.stopPropagation();
            const pick = activeIndex >= 0 ? options[activeIndex] : (options.length === 1 ? options[0] : null);
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
            openCategories(e.key === 'ArrowDown' ? 0 : Math.max(0, options.length - 1));
        }
    };

    // Keep the cursored option in view; jsdom has no scrollIntoView.
    useEffect(() => {
        if (!catOpen || activeIndex < 0 || !options[activeIndex]) return;
        const el = document.getElementById(optionId(options[activeIndex].service_code));
        if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' });
    }, [catOpen, activeIndex, options]);

    /* ------------------------------------------------------------- channel */

    const chooseSource = (value: Source) => {
        setSource(value);
        // An email has the sender's address in it; open the contact fields.
        if (value === 'email') setShowContact(true);
    };

    /* ------------------------------------------------------- caller lookup */

    // Exact match on a full address only, and only when the clerk leaves the
    // field: every search is audited server-side, so half-typed addresses
    // should not be searched one keystroke at a time.
    const lookUpCaller = () => {
        const value = email.trim().toLowerCase();
        if (!settings?.modules?.resident_history || !EMAIL_RE.test(value)) return;
        if (lookedUpEmail.current === value) return;
        lookedUpEmail.current = value;
        api.searchResidents({ email: value })
            .then(result => {
                if (lookedUpEmail.current !== value) return;
                setCallerHistory({ email: value, total: result.total, reports: result.reports || [] });
            })
            .catch(() => { if (lookedUpEmail.current === value) setCallerHistory(null); });
    };
    const callerMatches = callerHistory && callerHistory.email === email.trim().toLowerCase() ? callerHistory : null;

    /* ------------------------------------------------- nearby duplicates */

    const duplicates = useMemo(() => {
        if (!serviceCode || lat == null || lng == null) return [];
        return requests
            .filter(r => r.status !== 'closed' && r.service_code === serviceCode
                && typeof r.lat === 'number' && typeof r.long === 'number')
            .map(r => ({ request: r, meters: distanceMeters(lat, lng, r.lat as number, r.long as number) }))
            .filter(d => d.meters <= DUPLICATE_RADIUS_M)
            .sort((a, b) => a.meters - b.meters)
            .slice(0, 3);
    }, [requests, serviceCode, lat, lng]);

    /* ------------------------------------------------------------ reset */

    const resetForm = (keepCaller: boolean) => {
        setServiceCode(''); setCatQuery(''); setCatOpen(false); setActiveIndex(-1);
        setDescription(''); setCustomAnswers({});
        setAddress(''); setLat(null); setLng(null); setSelectedAsset(null);
        setOutOfBounds(false); setDetectedRoad(null); setMapKey(k => k + 1);
        setRedirect(null); setOverrideJurisdiction(false); roadCheckSeq.current++;
        setHideFromPublic(false);
        setDepartmentId(''); setAssignee(''); setPriority(''); setStaffNotes(''); setSendConfirmation(true);
        setShowStaff(false);
        photos.reset();
        setErrors({}); setErrorSummary([]); setSubmitError(null);
        if (!keepCaller) {
            setPhone(''); setFirstName(''); setLastName(''); setEmail(''); setLanguage('en');
            setShowContact(source === 'email');
            setCallerHistory(null); setShowCallerHistory(false); lookedUpEmail.current = null;
        }
    };

    const logAnother = (keepCaller: boolean) => {
        loggedRef.current = false;
        resetForm(keepCaller);
        setCreated(null);
        setLinkCopied(false);
        setTimeout(() => descRef.current?.focus(), 80);
    };

    /* ----------------------------------------------------------- submit */

    const validate = (): boolean => {
        const next: Record<string, string> = {};
        if (!serviceCode) next.category = 'Pick a category for this request.';
        if (description.trim().length < MIN_DESCRIPTION) {
            next.description = `Describe the issue in at least ${MIN_DESCRIPTION} characters.`;
        }
        for (const q of questions) {
            if (q.required && isUnanswered(customAnswers[q.label])) next[`custom_${q.id}`] = `${q.label} is required`;
        }
        if (phone.trim() && !isValidPhone(phone)) next.phone = 'Enter a valid phone number, such as (555) 123-4567.';
        if (email.trim() && !emailIsValid) next.email = 'Enter a valid email address.';
        if (redirect && !overrideJurisdiction) {
            next.override = `${redirect.jurisdiction || 'Another agency'} handles this. Check “Log it anyway” to log it here.`;
        }

        setErrors(next);
        // The email field lives in a collapsed block; open it so the summary
        // link has somewhere to land.
        if (next.email) setShowContact(true);
        const fieldFor = (key: string) => key.startsWith('custom_')
            ? customFieldId(key.slice('custom_'.length))
            : FIELD[key as keyof typeof FIELD];
        setErrorSummary(Object.entries(next).map(([key, message]) => ({ fieldId: fieldFor(key), message })));
        return Object.keys(next).length === 0;
    };

    const submit = async () => {
        if (saving || photos.stillChecking) return;
        setSubmitError(null);
        if (!validate()) return;
        setSaving(true);
        try {
            const blankAddress = !address.trim();
            const { media_urls, media_flagged, inlineFallback } = photos.submission();
            const hidden = locationMode === 'hidden';
            const matchedAsset = selectedAsset && !hidden ? {
                layer_name: selectedAsset.layerName,
                layer_id: 0, // Filled in by the backend
                asset_id: selectedAsset.properties.asset_id || selectedAsset.properties.id,
                asset_type: selectedAsset.properties.asset_type || selectedAsset.layerName,
                properties: selectedAsset.properties,
                distance_meters: 0, // Exact selection, no distance
            } : undefined;
            const confirmationTo = email.trim() && sendConfirmation ? email.trim() : null;
            const result = await api.createManualIntake({
                service_code: serviceCode,
                description: description.trim(),
                address: hidden || blankAddress ? undefined : address.trim(),
                lat: hidden ? undefined : lat ?? undefined,
                long: hidden ? undefined : lng ?? undefined,
                matched_asset: matchedAsset,
                first_name: firstName.trim() || undefined,
                last_name: lastName.trim() || undefined,
                email: email.trim() || undefined,
                phone: phone.trim() || undefined,
                preferred_language: language,
                media_urls,
                media_flagged: media_flagged.length ? media_flagged : undefined,
                custom_fields: customAnswers,
                is_public: hideFromPublic && !selected?.hidden_from_public ? false : undefined,
                override_jurisdiction: overrideJurisdiction || undefined,
                source,
                assigned_department_id: departmentId ? Number(departmentId) : undefined,
                assigned_to: assignee || undefined,
                manual_priority_score: priority ? Number(priority) : undefined,
                staff_notes: staffNotes.trim() || undefined,
                send_confirmation: sendConfirmation,
            }, inlineFallback);
            onCreated(result);
            setRecent(rememberRecent(serviceCode));
            setSessionCount(c => c + 1);
            setCreatedNotes({ confirmationTo });
            setCreated(result);
            loggedRef.current = true;
            setErrors({}); setErrorSummary([]);
            announce(`Request ${result.service_request_id} logged.`);
        } catch (e: any) {
            // The server returns the jurisdiction, the road and who to contact
            // rather than a bare error, so the clerk can read it to the caller.
            const detail = e?.detail ?? e?.body?.detail;
            if (detail?.error === 'redirected') {
                setRedirect({
                    variant: 'road',
                    jurisdiction: detail.jurisdiction ?? null,
                    message: detail.message ?? '',
                    messageIsDefault: Boolean(detail.message_is_default),
                    contacts: detail.contacts ?? [],
                    road: detail.road ?? null,
                });
                setOverrideJurisdiction(false);
                announce(
                    `${detail.jurisdiction || 'Another agency'} maintains this location. Check “Log it anyway” to record it here.`,
                    'assertive',
                );
            } else {
                setSubmitError(e?.message || 'The request wasn’t logged. Try again.');
            }
        } finally {
            setSaving(false);
        }
    };

    const onKeyDown = (e: React.KeyboardEvent) => {
        if (created) return;
        if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
            e.preventDefault();
            void submit();
            return;
        }
        // Alt+1..4 switches channel. `code`, not `key`: on a Mac, Option+1
        // types "¡".
        if (e.altKey && !e.ctrlKey && !e.metaKey) {
            const match = /^Digit([1-9])$/.exec(e.code) || /^([1-9])$/.exec(e.key);
            const index = match ? Number(match[1]) - 1 : -1;
            if (index >= 0 && index < SOURCES.length) {
                e.preventDefault();
                chooseSource(SOURCES[index].value);
                announce(`Received by: ${SOURCES[index].label}.`);
            }
        }
    };

    /* ------------------------------------------------------------ render */

    const trackingUrl = created ? `${window.location.origin}/#track/${created.service_request_id}` : '';
    const copyLink = async () => {
        try {
            await navigator.clipboard.writeText(trackingUrl);
            setLinkCopied(true);
            announce('Tracking link copied.');
        } catch {
            announce('The link wasn’t copied. It’s shown under the request ID.', 'assertive');
        }
    };

    const unlistedModule = settings?.modules?.unlisted_reports ?? (settings?.modules as any)?.private_reports;
    const categoryDefaultDept = selected?.assigned_department_id
        ? departments.find(d => d.id === selected.assigned_department_id)?.name
        : undefined;
    const staffOptions = staff
        .filter(u => u.is_active !== false && (u.role === 'staff' || u.role === 'admin'))
        .sort((a, b) => (a.full_name || a.username).localeCompare(b.full_name || b.username));
    const languageOptions = useMemo(() => [
        { value: 'en', label: 'English' },
        ...LANGUAGES.filter(l => l.code !== 'en')
            .sort((a, b) => a.name.localeCompare(b.name))
            .map(l => ({ value: l.code, label: l.nativeName && l.nativeName !== l.name ? `${l.name} — ${l.nativeName}` : l.name })),
    ], []);

    const SelectedIcon = selected ? categoryIconFor(selected.icon) : null;
    const locationRequiredMissing = !!selected && locationMode === 'required' && !address.trim() && (lat == null || lng == null);

    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title="Log a request"
            size="lg"
            panelClassName="bg-slate-900/95 border border-white/20 shadow-[0_20px_80px_rgba(0,0,0,0.6)] backdrop-blur-3xl rounded-3xl"
            headerClassName="bg-slate-800/90 border-b border-white/15 p-6"
        >
            <div className="space-y-6" onKeyDown={onKeyDown}>
                {created ? (
                    /* ------------------------------------------- success */
                    <div className="space-y-6">
                        <div className="text-center space-y-3">
                            <div className="w-14 h-14 mx-auto rounded-2xl bg-gradient-to-br from-emerald-500/25 to-teal-500/20 ring-1 ring-emerald-400/30 flex items-center justify-center" aria-hidden="true">
                                <CheckCircle2 className="w-7 h-7 text-emerald-300" />
                            </div>
                            <h3
                                ref={successHeadingRef}
                                tabIndex={-1}
                                className="text-xl font-semibold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 rounded-lg"
                            >
                                Request logged
                            </h3>
                            <p className="text-3xl font-bold tracking-tight text-white" data-no-translate>{created.service_request_id}</p>
                            <p className="text-sm text-white/60">
                                {created.service_name || selected?.service_name}
                                {' · '}{SOURCES.find(s => s.value === source)?.label}
                                {sessionCount > 1 && <> · {sessionCount} logged this session</>}
                            </p>
                        </div>

                        <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 space-y-3">
                            <div className="flex flex-col sm:flex-row sm:items-center gap-3">
                                <div className="min-w-0 flex-1">
                                    <p className="text-xs font-medium text-white/55">Tracking link</p>
                                    <p className="text-sm text-white/85 [overflow-wrap:anywhere]" data-no-translate>{trackingUrl}</p>
                                </div>
                                <Button variant="secondary" size="sm" onClick={copyLink}
                                    leftIcon={linkCopied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}>
                                    {linkCopied ? 'Copied' : 'Copy tracking link'}
                                </Button>
                            </div>
                            {createdNotes.confirmationTo && (
                                <p className="text-xs text-white/55 flex items-center gap-1.5">
                                    <Mail className="w-3.5 h-3.5" aria-hidden="true" />
                                    A confirmation goes to {createdNotes.confirmationTo}.
                                </p>
                            )}
                            {(created.photos_pending_review ?? 0) > 0 && (
                                <p className="text-xs text-amber-200 flex items-center gap-1.5">
                                    <Camera className="w-3.5 h-3.5" aria-hidden="true" />
                                    {created.photos_pending_review === 1
                                        ? '1 photo is held for review. Release it from the request.'
                                        : `${created.photos_pending_review} photos are held for review. Release them from the request.`}
                                </p>
                            )}
                        </div>

                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                            <Button onClick={() => logAnother(false)} leftIcon={<Plus className="w-4 h-4" />}>
                                Log another
                            </Button>
                            <Button variant="secondary" onClick={() => logAnother(true)} leftIcon={<UserPlus className="w-4 h-4" />}>
                                Log another for the same {copy.who}
                            </Button>
                            {onOpenRequest && (
                                <Button variant="secondary" onClick={() => onOpenRequest(created.service_request_id)}
                                    leftIcon={<ExternalLink className="w-4 h-4" />}>
                                    Open request
                                </Button>
                            )}
                            <Button variant="ghost" onClick={onClose} leftIcon={<X className="w-4 h-4" />}>
                                Close
                            </Button>
                        </div>
                    </div>
                ) : (
                    /* ---------------------------------------------- form */
                    <>
                        {/* How it came in: one compact selector */}
                        <section aria-label="How the report came in" className="space-y-3">
                            <div className="flex flex-wrap items-center gap-3">
                                <label htmlFor="intake-source" className="text-sm font-medium text-white/70">Received by</label>
                                <select
                                    id="intake-source"
                                    value={source}
                                    onChange={e => chooseSource(e.target.value as Source)}
                                    aria-keyshortcuts="Alt+1 Alt+2 Alt+3 Alt+4"
                                    className="glass-input text-sm py-2 w-auto min-w-[9rem]"
                                >
                                    {SOURCES.map((s, i) => (
                                        <option key={s.value} value={s.value}>{s.label}{` (Alt+${i + 1})`}</option>
                                    ))}
                                </select>
                            </div>
                            {(source === 'phone' || source === 'walk_in') && (
                                <p className="flex items-center gap-2 rounded-xl border border-red-400/25 bg-red-500/10 px-3.5 py-2.5 text-sm text-red-100">
                                    <Siren className="w-4 h-4 shrink-0 text-red-300" aria-hidden="true" />
                                    If this is an emergency, direct them to 911.
                                </p>
                            )}
                        </section>

                        {/* The issue */}
                        <section aria-labelledby="intake-issue-heading" className="space-y-5">
                            <SectionHeading icon={MessageSquare} title="The issue" id="intake-issue-heading" />

                            {/* Category — searchable combobox */}
                            <div className="relative">
                                <label htmlFor={FIELD.category} className={labelCls}>
                                    Category
                                    <span className="required-indicator" aria-hidden="true">*</span>
                                </label>
                                <button
                                    type="button"
                                    id={FIELD.category}
                                    ref={catButtonRef}
                                    onClick={() => (catOpen ? closeCategories(false) : openCategories())}
                                    onKeyDown={onTriggerKeyDown}
                                    aria-haspopup="listbox"
                                    aria-expanded={catOpen}
                                    /* The listbox is only in the DOM while open. */
                                    aria-controls={catOpen ? 'intake-category-listbox' : undefined}
                                    aria-required="true"
                                    aria-invalid={errors.category ? true : undefined}
                                    aria-describedby={errors.category ? `${FIELD.category}-error` : undefined}
                                    className={`glass-input flex items-center gap-3 text-left ${errors.category ? 'border-red-400/50' : ''}`}
                                >
                                    {selected && SelectedIcon ? (
                                        <span className="w-7 h-7 rounded-lg bg-gradient-to-br from-primary-500/30 to-primary-600/30 flex items-center justify-center text-primary-200 shrink-0" aria-hidden="true">
                                            <SelectedIcon className="w-4 h-4" />
                                        </span>
                                    ) : null}
                                    <span className={`truncate flex-1 ${selected ? 'text-white' : 'text-white/45'}`}>
                                        {selected ? selected.service_name : 'Choose a category…'}
                                    </span>
                                    <ChevronDown className="w-4 h-4 shrink-0 text-white/40" aria-hidden="true" />
                                </button>
                                {errors.category && (
                                    <p id={`${FIELD.category}-error`} className="mt-1.5 text-sm text-red-400">{errors.category}</p>
                                )}
                                <AnimatePresence>
                                    {catOpen && (
                                        <motion.div
                                            initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
                                            className="absolute z-30 mt-1 w-full rounded-2xl border border-white/15 bg-slate-800/95 backdrop-blur-xl shadow-2xl overflow-hidden"
                                        >
                                            <div className="p-2 border-b border-white/10">
                                                <div className="relative">
                                                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-white/40" aria-hidden="true" />
                                                    <input
                                                        autoFocus
                                                        value={catQuery}
                                                        onChange={e => setCatQuery(e.target.value)}
                                                        onKeyDown={onFilterKeyDown}
                                                        placeholder="Search name, code or description…"
                                                        aria-label="Filter categories"
                                                        role="combobox"
                                                        aria-expanded="true"
                                                        aria-controls="intake-category-listbox"
                                                        aria-autocomplete="list"
                                                        autoComplete="off"
                                                        aria-activedescendant={activeIndex >= 0 && options[activeIndex]
                                                            ? optionId(options[activeIndex].service_code)
                                                            : undefined}
                                                        className="w-full rounded-lg bg-white/[0.05] border border-white/10 text-white text-sm pl-8 pr-3 py-2 placeholder:text-white/40 focus:outline-none focus:border-primary-400/50"
                                                    />
                                                </div>
                                            </div>
                                            <ul
                                                id="intake-category-listbox"
                                                role="listbox"
                                                aria-label="Service categories"
                                                className="max-h-72 overflow-y-auto py-1"
                                            >
                                                {options.length === 0 && (
                                                    <li role="presentation" className="px-3 py-2 text-white/40 text-sm">No categories match “{catQuery}”.</li>
                                                )}
                                                {options.map((s, i) => {
                                                    const isChosen = s.service_code === serviceCode;
                                                    const isCursor = i === activeIndex;
                                                    const Icon = categoryIconFor(s.icon);
                                                    const sectionLabel = recentCount > 0 && i === 0 ? 'Recent'
                                                        : recentCount > 0 && i === recentCount ? 'All categories' : null;
                                                    return (
                                                        <li
                                                            key={s.service_code}
                                                            id={optionId(s.service_code)}
                                                            role="option"
                                                            aria-selected={isChosen}
                                                            onClick={() => chooseCategory(s.service_code)}
                                                            onMouseMove={() => setActiveIndex(i)}
                                                            className={`cursor-pointer ${sectionLabel && i > 0 ? 'border-t border-white/10 mt-1 pt-1' : ''}`}
                                                        >
                                                            {sectionLabel && (
                                                                <span className="block px-3 pt-1.5 pb-1 text-[11px] font-semibold uppercase tracking-wider text-white/40" aria-hidden="true">
                                                                    {sectionLabel}
                                                                </span>
                                                            )}
                                                            <span className={`flex items-center gap-3 px-3 py-2 text-sm transition-colors ${isChosen ? 'bg-primary-500/20 text-white' : isCursor ? 'bg-white/10 text-white' : 'text-white/80'}`}>
                                                                <span className="w-8 h-8 rounded-lg bg-gradient-to-br from-primary-500/25 to-primary-600/25 flex items-center justify-center text-primary-200 shrink-0" aria-hidden="true">
                                                                    <Icon className="w-4 h-4" />
                                                                </span>
                                                                <span className="min-w-0 flex-1">
                                                                    <span className="block truncate font-medium">{s.service_name}</span>
                                                                    {s.description && (
                                                                        <span className="block truncate text-xs text-white/50">{s.description}</span>
                                                                    )}
                                                                </span>
                                                                {isChosen && <CheckCircle className="w-4 h-4 text-primary-300 shrink-0" aria-hidden="true" />}
                                                            </span>
                                                        </li>
                                                    );
                                                })}
                                            </ul>
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </div>

                            {/* Whole category handled elsewhere: said the moment it is picked. */}
                            {redirect?.variant === 'service' && selected && (
                                <RedirectNotice
                                    variant="service"
                                    jurisdiction={redirect.jurisdiction}
                                    message={redirect.message}
                                    messageIsDefault={redirect.messageIsDefault}
                                    contacts={redirect.contacts}
                                    serviceName={selected.service_name}
                                />
                            )}

                            <Textarea
                                id={FIELD.description}
                                ref={descRef}
                                label={copy.descLabel}
                                value={description}
                                onChange={e => { setDescription(e.target.value); if (errors.description) clearError('description'); }}
                                rows={3}
                                required
                                error={errors.description}
                                errorAsAlert={false}
                                helperText="AI triage suggests a priority once it’s logged."
                                placeholder={copy.descPlaceholder}
                                className="min-h-[96px] resize-y"
                            />

                            {questions.length > 0 && (
                                <div className="space-y-4 rounded-2xl border border-white/10 bg-white/[0.03] p-4">
                                    <p className="text-sm font-semibold text-white">Questions for {selected?.service_name}</p>
                                    <CustomQuestionFields
                                        questions={questions}
                                        answers={customAnswers}
                                        onChange={(label, value) => setCustomAnswers(p => ({ ...p, [label]: value }))}
                                        errors={errors}
                                        fieldId={customFieldId}
                                        namePrefix="intake_custom_"
                                    />
                                </div>
                            )}

                            {selected?.hidden_from_public && (
                                <div className="flex items-start gap-3 rounded-2xl border border-white/10 bg-white/[0.04] p-4">
                                    <div className="w-9 h-9 rounded-xl bg-slate-500/20 border border-slate-400/25 flex items-center justify-center shrink-0" aria-hidden="true">
                                        <EyeOff className="w-4 h-4 text-slate-200" />
                                    </div>
                                    <div className="min-w-0">
                                        <p className="text-sm font-medium text-white">This report won’t be shown publicly</p>
                                        <p className="text-xs text-white/55 mt-1 leading-relaxed">
                                            Reports in this category stay off the public map and list. Staff work it as
                                            usual and the tracking link still works. Like other municipal records, it can be
                                            released in response to a public records request.
                                        </p>
                                    </div>
                                </div>
                            )}

                            <div>
                                <span className={labelCls} id="intake-photos-label">Photos <span className="font-normal text-white/45">(optional)</span></span>
                                <PhotoUpload
                                    previewUrls={photos.previewUrls}
                                    statuses={photos.statuses}
                                    onAdd={photos.add}
                                    onRemove={photos.remove}
                                />
                            </div>
                        </section>

                        {/* Where */}
                        <section aria-labelledby="intake-where-heading" className="space-y-4">
                            <SectionHeading icon={MapPin} title="Where" id="intake-where-heading" />
                            {/* A category that collects no location gets none, from a
                                clerk either -- the server drops one sent anyway. */}
                            {locationMode === 'hidden' ? (
                                <div className="flex items-center gap-3 p-3.5 rounded-xl bg-white/[0.04] border border-white/10 text-white/60">
                                    <MapPinOff className="w-4 h-4 shrink-0 text-white/40" aria-hidden="true" />
                                    <p className="text-sm">{selected?.service_name} doesn’t collect a location.</p>
                                </div>
                            ) : (
                                <div>
                                    {/* Only the fallback is a single labelable control;
                                        the picker is a composite, so it gets a group label. */}
                                    {mapProviderReady(mapsRaw) ? (
                                        <div role="group" aria-labelledby="intake-location-label">
                                            <span id="intake-location-label" className={labelCls}>
                                                Location
                                                {locationMode === 'required'
                                                    ? <><span className="required-indicator" aria-hidden="true">*</span><span className="sr-only"> (usually needed)</span></>
                                                    : <span className="ml-1.5 font-normal text-white/45">(optional)</span>}
                                            </span>
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
                                                onOutOfBounds={() => setOutOfBounds(true)}
                                                onChange={(loc) => {
                                                    setAddress(loc.address); setLat(loc.lat); setLng(loc.lng);
                                                    // Decided from the pin itself: the picker reports
                                                    // out-of-bounds before its address lookup finishes.
                                                    setOutOfBounds(loc.lat != null && loc.lng != null && !!townshipBoundary
                                                        && !isPointInGeoJson(loc.lat, loc.lng, townshipBoundary));
                                                }}
                                                onAssetSelect={(asset) => setSelectedAsset(asset)}
                                                placeholder="Search for an address or click on the map…"
                                            />
                                        </div>
                                    ) : (
                                        <Input
                                            id="intake-address"
                                            label={locationMode === 'required' ? 'Location' : 'Location (optional)'}
                                            required={locationMode === 'required' ? true : undefined}
                                            value={address}
                                            onChange={e => setAddress(e.target.value)}
                                            autoComplete="off"
                                            leftIcon={<MapPin className="w-4 h-4" />}
                                            placeholder="123 Main St, or nearest intersection"
                                        />
                                    )}
                                </div>
                            )}

                            {locationRequiredMissing && (
                                <p className="flex items-center gap-2 text-sm text-amber-200">
                                    <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden="true" />
                                    This category usually needs a location.
                                </p>
                            )}

                            {outOfBounds && locationMode !== 'hidden' && (
                                <p className="flex items-center gap-2 rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-sm text-red-100">
                                    <MapPinOff className="w-4 h-4 shrink-0 text-red-300" aria-hidden="true" />
                                    This pin is outside the municipality.
                                </p>
                            )}

                            {selectedAsset && locationMode !== 'hidden' && (
                                <div className="flex items-center gap-2 flex-wrap">
                                    <span className="text-xs text-white/55">Selected asset</span>
                                    <span className="inline-flex items-center gap-1.5 rounded-full border border-primary-400/30 bg-primary-500/15 pl-2.5 pr-1 py-0.5 text-xs text-primary-100">
                                        <Layers className="w-3.5 h-3.5" aria-hidden="true" />
                                        {selectedAsset.properties.asset_type || selectedAsset.layerName}
                                        {(selectedAsset.properties.asset_id || selectedAsset.properties.id) && (
                                            <> · {String(selectedAsset.properties.asset_id || selectedAsset.properties.id)}</>
                                        )}
                                        <button
                                            type="button"
                                            onClick={() => setSelectedAsset(null)}
                                            aria-label="Clear selected asset"
                                            className="ml-0.5 rounded-full p-0.5 hover:bg-white/15 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-300"
                                        >
                                            <X className="w-3 h-3" aria-hidden="true" />
                                        </button>
                                    </span>
                                </div>
                            )}

                            {detectedRoad && locationMode !== 'hidden' && (
                                <div className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl bg-white/[0.04] border border-white/10">
                                    <SignpostBig className="w-4 h-4 text-white/40 shrink-0" aria-hidden="true" />
                                    <span className="text-sm text-white/60">
                                        Road detected: <span className="text-white/90 font-medium">{detectedRoad.name}</span>
                                    </span>
                                </div>
                            )}

                            {redirect?.variant === 'road' && (
                                <RedirectNotice
                                    variant="road"
                                    jurisdiction={redirect.jurisdiction}
                                    message={redirect.message}
                                    messageIsDefault={redirect.messageIsDefault}
                                    contacts={redirect.contacts}
                                    roadName={redirect.road}
                                    serviceName={selected?.service_name}
                                />
                            )}

                            {duplicates.length > 0 && (
                                <div className="rounded-2xl border border-amber-400/25 bg-amber-500/[0.07] p-4">
                                    <p className="text-sm font-semibold text-amber-100 flex items-center gap-2">
                                        <History className="w-4 h-4" aria-hidden="true" /> Possible duplicates
                                    </p>
                                    <p className="text-xs text-white/55 mt-0.5">Open {selected?.service_name} reports within {DUPLICATE_RADIUS_M} m.</p>
                                    <ul className="mt-3 space-y-2">
                                        {duplicates.map(({ request: r, meters }) => (
                                            <li key={r.service_request_id} className="flex items-center gap-3 rounded-xl bg-white/[0.05] border border-white/10 px-3 py-2">
                                                <span className="min-w-0 flex-1">
                                                    <span className="flex items-center gap-2 text-sm text-white font-medium">
                                                        <span data-no-translate>{r.service_request_id}</span>
                                                        <StatusBadge status={r.status} />
                                                    </span>
                                                    <span className="block text-xs text-white/55 truncate">
                                                        {Math.round(meters)} m away{r.address ? ` · ${r.address}` : ''}
                                                    </span>
                                                </span>
                                                {onOpenRequest && (
                                                    <Button variant="ghost" size="sm" onClick={() => onOpenRequest(r.service_request_id)}
                                                        aria-label={`Open request ${r.service_request_id}`}>
                                                        Open
                                                    </Button>
                                                )}
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                        </section>

                        {redirect && (
                            <label
                                className={`flex items-start gap-3 cursor-pointer rounded-xl border px-3.5 py-3 ${errors.override ? 'border-red-400/50 bg-red-500/10' : 'border-white/10 bg-white/[0.03]'}`}
                            >
                                <input
                                    id={FIELD.override}
                                    type="checkbox"
                                    checked={overrideJurisdiction}
                                    onChange={e => { setOverrideJurisdiction(e.target.checked); if (e.target.checked) clearError('override'); }}
                                    aria-describedby={`${FIELD.override}-hint${errors.override ? ` ${FIELD.override}-error` : ''}`}
                                    aria-invalid={errors.override ? true : undefined}
                                    className="mt-0.5 w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500 shrink-0"
                                />
                                <span className="min-w-0">
                                    <span className="block text-sm font-medium text-white">Log it anyway</span>
                                    <span id={`${FIELD.override}-hint`} className="block text-xs text-white/55 mt-0.5 leading-relaxed">
                                        Records the report here. Your town still needs to forward it.
                                    </span>
                                    {errors.override && (
                                        <span id={`${FIELD.override}-error`} className="block text-sm text-red-400 mt-1">{errors.override}</span>
                                    )}
                                </span>
                            </label>
                        )}

                        {/* Callback number stays in view: on the phone it is the
                            one detail most callers give. */}
                        <Input
                            id={FIELD.phone}
                            label={`${copy.phoneLabel} (optional)`}
                            type="tel"
                            inputMode="tel"
                            autoComplete="off"
                            value={phone}
                            onChange={e => { setPhone(filterPhoneInput(e.target.value)); if (errors.phone) clearError('phone'); }}
                            error={errors.phone}
                            errorAsAlert={false}
                            leftIcon={<Phone className="w-4 h-4" />}
                            placeholder="(555) 123-4567"
                        />

                        <Disclosure
                            icon={UserIcon}
                            title={copy.contactToggle}
                            hint={copy.contactBlurb}
                            open={showContact}
                            onToggle={() => setShowContact(v => !v)}
                            panelId="intake-contact-panel"
                        >
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <Input id="intake-first-name" label="First name" autoComplete="off"
                                    value={firstName} onChange={e => setFirstName(e.target.value)} />
                                <Input id="intake-last-name" label="Last name" autoComplete="off"
                                    value={lastName} onChange={e => setLastName(e.target.value)} />
                            </div>
                            <div>
                                <Input
                                    id={FIELD.email}
                                    label={copy.emailLabel}
                                    type="email"
                                    inputMode="email"
                                    autoComplete="off"
                                    value={email}
                                    onChange={e => { setEmail(e.target.value); if (errors.email) clearError('email'); }}
                                    onBlur={lookUpCaller}
                                    error={errors.email}
                                    errorAsAlert={false}
                                    helperText="If given, they get the same confirmation as an online report."
                                    placeholder="name@example.com"
                                />
                                {callerMatches && (
                                    <div className="mt-2">
                                        {callerMatches.total === 0 ? (
                                            <p className="text-xs text-white/50">No other reports from this {copy.who}.</p>
                                        ) : (
                                            <>
                                                <button
                                                    type="button"
                                                    onClick={() => setShowCallerHistory(v => !v)}
                                                    aria-expanded={showCallerHistory}
                                                    aria-controls="intake-caller-history"
                                                    className="inline-flex items-center gap-1.5 text-xs font-medium text-primary-200 hover:text-primary-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-400/60 rounded"
                                                >
                                                    <History className="w-3.5 h-3.5" aria-hidden="true" />
                                                    {callerMatches.total === 1 ? '1 other report' : `${callerMatches.total} other reports`} from this {copy.who}
                                                    <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showCallerHistory ? 'rotate-180' : ''}`} aria-hidden="true" />
                                                </button>
                                                {showCallerHistory && (
                                                    <ul id="intake-caller-history" className="mt-2 space-y-1.5">
                                                        {callerMatches.reports.slice(0, 5).map(r => (
                                                            <li key={r.service_request_id} className="flex items-center gap-3 rounded-lg bg-white/[0.04] border border-white/10 px-3 py-1.5">
                                                                <span className="min-w-0 flex-1 text-xs text-white/70 truncate">
                                                                    <span className="text-white font-medium" data-no-translate>{r.service_request_id}</span>
                                                                    {r.service_name && <> · {r.service_name}</>}
                                                                    {r.status && <> · {r.status.replace('_', ' ')}</>}
                                                                </span>
                                                                {onOpenRequest && (
                                                                    <Button variant="ghost" size="sm" onClick={() => onOpenRequest(r.service_request_id)}
                                                                        aria-label={`Open request ${r.service_request_id}`}>
                                                                        Open
                                                                    </Button>
                                                                )}
                                                            </li>
                                                        ))}
                                                    </ul>
                                                )}
                                            </>
                                        )}
                                    </div>
                                )}
                            </div>
                            <Select
                                id="intake-language"
                                label="Preferred language"
                                options={languageOptions}
                                value={language}
                                onChange={e => setLanguage(e.target.value)}
                                helperText="Confirmations and updates go out in this language."
                            />
                        </Disclosure>

                        {unlistedModule && !selected?.hidden_from_public && (
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
                                    <span className="block text-xs text-white/55 mt-1 leading-relaxed">
                                        Check only if the {copy.who} asked to keep it unlisted. Staff still see and work it,
                                        the tracking link still works, and it still counts in anonymized statistics.
                                    </span>
                                </span>
                            </label>
                        )}

                        <Disclosure
                            icon={Settings2}
                            title="Staff options"
                            hint="Assignment, priority, internal note, confirmation."
                            open={showStaff}
                            onToggle={() => setShowStaff(v => !v)}
                            panelId="intake-staff-panel"
                        >
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <Select
                                    id="intake-department"
                                    label="Department"
                                    value={departmentId}
                                    onChange={e => setDepartmentId(e.target.value)}
                                    options={[
                                        { value: '', label: categoryDefaultDept ? `Category default (${categoryDefaultDept})` : 'Category default' },
                                        ...departments.filter(d => d.is_active !== false)
                                            .map(d => ({ value: String(d.id), label: d.name })),
                                    ]}
                                />
                                <Select
                                    id="intake-assignee"
                                    label="Assign to"
                                    value={assignee}
                                    onChange={e => setAssignee(e.target.value)}
                                    options={[
                                        { value: '', label: 'Category default' },
                                        ...staffOptions.map(u => ({ value: u.username, label: u.full_name || u.username })),
                                    ]}
                                />
                            </div>
                            <Select
                                id="intake-priority"
                                label="Priority"
                                value={priority}
                                onChange={e => setPriority(e.target.value)}
                                helperText="Left blank, AI triage suggests one."
                                options={[
                                    { value: '', label: 'Let AI triage suggest it' },
                                    ...Array.from({ length: 10 }, (_, i) => 10 - i).map(p => ({
                                        value: String(p),
                                        label: p === 10 ? '10 — most urgent' : p === 1 ? '1 — least urgent' : String(p),
                                    })),
                                ]}
                            />
                            <Textarea
                                id="intake-staff-notes"
                                label="Internal note"
                                value={staffNotes}
                                onChange={e => setStaffNotes(e.target.value)}
                                rows={2}
                                helperText="Staff only. Never shown to the resident."
                                className="min-h-[72px] resize-y"
                            />
                            <label className={`flex items-start gap-3 rounded-xl border border-white/10 bg-white/[0.03] px-3.5 py-3 ${emailIsValid ? 'cursor-pointer' : 'opacity-60'}`}>
                                <input
                                    id="intake-send-confirmation"
                                    type="checkbox"
                                    checked={sendConfirmation && emailIsValid}
                                    disabled={!emailIsValid}
                                    onChange={e => setSendConfirmation(e.target.checked)}
                                    aria-describedby="intake-send-confirmation-hint"
                                    className="mt-0.5 w-4 h-4 rounded border-white/20 bg-white/10 text-primary-500 shrink-0"
                                />
                                <span className="min-w-0">
                                    <span className="block text-sm font-medium text-white">Send the {copy.who} a confirmation</span>
                                    <span id="intake-send-confirmation-hint" className="block text-xs text-white/55 mt-0.5">
                                        {emailIsValid ? `Emailed to ${email.trim()}.` : `Add the ${copy.who}’s email to send one.`}
                                    </span>
                                </span>
                            </label>
                        </Disclosure>

                        {/* What went wrong, in one place, with focus on it --
                            the same pattern as the resident form (WCAG 3.3.1).
                            Not role="alert": moving focus here is what announces
                            it, and the field messages are plain text tied to
                            their controls by aria-describedby. */}
                        {errorSummary.length > 0 && (
                            <div
                                id="intake-error-summary"
                                ref={errorSummaryRef}
                                tabIndex={-1}
                                aria-labelledby="intake-error-summary-heading"
                                className="p-4 rounded-2xl bg-red-500/15 border border-red-500/35 text-red-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
                            >
                                <h3 id="intake-error-summary-heading" className="font-semibold text-red-100">
                                    {errorSummary.length === 1
                                        ? 'There is a problem with this request'
                                        : `There are ${errorSummary.length} problems with this request`}
                                </h3>
                                <ul className="mt-2 space-y-1 list-disc list-inside">
                                    {errorSummary.map(({ fieldId, message }) => (
                                        <li key={message}>
                                            <a
                                                href={`#${fieldId}`}
                                                className="underline"
                                                onClick={(e) => {
                                                    /* Focus the field rather than letting the
                                                       fragment move only the focus starting point. */
                                                    const el = document.getElementById(fieldId);
                                                    if (!el) return;
                                                    e.preventDefault();
                                                    el.focus();
                                                    if (typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'center' });
                                                }}
                                            >{message}</a>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        )}

                        {submitError && (
                            /* role="alert": nothing else on screen moves when a
                               save fails, so without it the failure is silent. */
                            <div id="intake-submit-error" role="alert" className="p-4 rounded-2xl bg-red-500/15 border border-red-500/35 text-red-200 text-sm">
                                {submitError}
                            </div>
                        )}

                        {/* Actions */}
                        <div className="flex flex-col-reverse sm:flex-row sm:items-center sm:justify-between gap-3 pt-4 border-t border-white/10">
                            <Button variant="ghost" onClick={onClose} leftIcon={<X className="w-4 h-4" />}>
                                Close
                            </Button>
                            <div className="flex flex-col sm:items-end gap-1">
                                <Button
                                    onClick={() => void submit()}
                                    isLoading={saving || photos.stillChecking}
                                    leftIcon={<CheckCircle2 className="w-4 h-4" />}
                                    aria-keyshortcuts="Control+Enter Meta+Enter"
                                >
                                    {photos.stillChecking ? 'Checking photos…' : saving ? 'Logging…' : 'Log request'}
                                </Button>
                                <span className="text-[11px] text-white/50">⌘/Ctrl + Enter to log</span>
                            </div>
                        </div>
                    </>
                )}
            </div>
        </Modal>
    );
}
