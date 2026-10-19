import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { resolveMapProviderConfig, mapProviderReady, RawMapsConfig } from '../maps';
import { categoryIconFor } from '../components/categoryIcons';
import { motion, AnimatePresence } from 'framer-motion';
import { Link, useParams } from 'react-router-dom';
import {
    ArrowLeft,
    MapPin,
    CheckCircle2,
    Send,
    SignpostBig,
    Sparkles, Home,
    Phone,
    ClipboardList,
    Globe,
    Facebook,
    Instagram,
    Youtube,
    Twitter,
    Linkedin,
    AlertTriangle,
    Search,
    MapPinOff,
    EyeOff,
    Map as MapIcon,
} from 'lucide-react';
import { Button, Input, Textarea, Card, Chip } from '../components/ui';
import LocationPicker from '../components/LocationPicker';
import PhotoUpload from '../components/PhotoUpload';
import { usePhotoAttachments } from '../hooks/usePhotoAttachments';
import { filterPhoneInput, isValidPhone } from '../utils/phone';
import RedirectNotice, { RedirectContact } from '../components/RedirectNotice';
import CustomQuestionFields from '../components/CustomQuestionFields';
import TrackRequests from '../components/TrackRequests';
import PlatformFeedback from '../components/PlatformFeedback';
import LanguageSelector from '../components/LanguageSelector';
import StaffDashboardMap from '../components/StaffDashboardMap';
import { useSettings } from '../context/SettingsContext';
import { useTranslation } from '../context/TranslationContext';
import { useAnnounce } from '../context/AccessibilityContext';
import { api, MapLayer } from '../services/api';
import { ServiceDefinition, ServiceRequestCreate, ServiceRequest } from '../types';
import { usePageNavigation } from '../hooks/usePageNavigation';
import {
    saveResidentDraft,
    loadResidentDraft,
    clearResidentDraft,
    draftHasContent,
    type ResidentDraft,
} from '../utils/residentDraft';

// Icon mapping for service categories
// Category icons resolve through the shared set (components/categoryIcons.ts),
// the same one the admin picker offers, so every icon an admin picks shows here.

type Step = 'categories' | 'form' | 'success';




export default function ResidentPortal() {
    const { settings } = useSettings();
    const { language, setLanguage } = useTranslation();
    const announce = useAnnounce();
    const { requestId: urlRequestId } = useParams<{ requestId?: string }>();

    // Whether the language picker is worth drawing. A picker over a translator
    // that is switched off or unconfigured offers Spanish and then serves
    // English. Defaults to shown: an older backend does not send the field,
    // and a fetch error is not evidence that translation is unavailable.
    const [translationEnabled, setTranslationEnabled] = useState(true);
    useEffect(() => {
        fetch('/api/system/config')
            .then((r) => (r.ok ? r.json() : null))
            .then((cfg) => {
                if (cfg && cfg.translation_enabled === false) setTranslationEnabled(false);
            })
            .catch(() => { /* keep the picker */ });
    }, []);

    // Initialize state based on URL hash (not pathname)
    const initialHash = typeof window !== 'undefined' ? window.location.hash.slice(1) : '';
    /* `#track/<id>` has to work on a COLD load, not just on a hash change.
     *
     * Every "track your request" email links to `{portal}/#track/REQ-...`, and
     * this was `initialHash === 'track'` -- an exact match, which `track/REQ-1`
     * fails. The resident clicked the link in their email and landed on the
     * category list, with no sign of the report they came to see. The
     * startsWith branch existed, but only inside handleHashChange, which fires
     * on a hashchange event and not on first render.
     *
     * `urlRequestId` could not cover it either: it comes from useParams, and
     * there is no `/track/:requestId` route -- the portal is mounted at `/`
     * alone -- so it is always undefined. The hash is the only carrier. */
    const hashRequestId = initialHash.startsWith('track/')
        ? decodeURIComponent(initialHash.slice('track/'.length)) || undefined
        : undefined;
    const [showTrackingView, setShowTrackingView] = useState(
        Boolean(urlRequestId) || initialHash === 'track' || Boolean(hashRequestId),
    );
    const [step, setStep] = useState<Step>('categories');
    const [services, setServices] = useState<ServiceDefinition[]>([]);
    const [selectedService, setSelectedService] = useState<ServiceDefinition | null>(null);
    /** Whether this category asks where. Set per category by an administrator;
     *  absent on an older server, which means the map was always optional. */
    const locationMode = selectedService?.location_mode || 'optional';
    const [searchQuery, setSearchQuery] = useState('');
    const [isLoading, setIsLoading] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submittedId, setSubmittedId] = useState<string | null>(null);
    /**
     * How many of the photos just submitted the server held back for a person
     * to look at, straight from the create response.
     *
     * The thumbnail statuses on the form were a guess made at pick time and
     * the submit is where the answer is actually decided -- a photo the
     * pick-time screen could not clear is often cleared by the submit-time
     * pass, and one that looked fine can still be withheld there. Until this
     * existed the success screen said "received and will be reviewed shortly"
     * to a resident whose photo had just been withheld, with no mention of it
     * here or anywhere on the tracker afterwards.
     */
    const [submittedPhotosHeld, setSubmittedPhotosHeld] = useState(0);
    /* Read from inside handleHashChange, which is memoised once and so cannot
     * see the state value directly. */
    const submittedIdRef = useRef<string | null>(null);
    submittedIdRef.current = submittedId;
    /* How many photos a restored draft had attached. Photos are never kept in
     * the draft (handles expire, originals are megabytes), so after a restore
     * the form asks for them again; cleared once a photo is added. */
    const [photosToReadd, setPhotosToReadd] = useState(0);
    /* Assigned further down, once the setters they use exist. handleHashChange
     * is memoised with no dependencies and reaches them through these. */
    const resetFormRef = useRef<() => void>(() => { });
    const updateHashRef = useRef<(hash: string, replace?: boolean) => void>(() => { });
    const contentRef = useRef<HTMLDivElement>(null);

    // Non-emergency disclaimer modal state
    const [showDisclaimerModal, setShowDisclaimerModal] = useState(false);
    const [disclaimerChecked, setDisclaimerChecked] = useState(false);
    const [hasAcknowledgedDisclaimer, setHasAcknowledgedDisclaimer] = useState(() => {
        // Check localStorage on initial load
        return localStorage.getItem('disclaimer_acknowledged_v1') === 'true';
    });

    // Show disclaimer modal if not acknowledged
    useEffect(() => {
        if (!hasAcknowledgedDisclaimer) {
            setShowDisclaimerModal(true);
        }
    }, [hasAcknowledgedDisclaimer]);

    /* The disclaimer overlay covers the entire portal, so it has to behave like
     * the modal it looks like (WCAG 2.1.2 No Keyboard Trap / 4.1.2 Name, Role,
     * Value). It used to be a bare motion.div: a screen reader saw the page
     * behind it, and Tab walked out of the overlay into controls nobody could
     * see or click.
     *
     * Initial focus goes to the dialog container rather than to the checkbox so
     * the heading and the 911 sentence are read before the resident is asked to
     * agree to them; the container is the labelled/described element, so
     * focusing it announces the whole thing. */
    const disclaimerRef = useRef<HTMLDivElement>(null);
    useEffect(() => {
        if (!showDisclaimerModal) return;
        const frame = window.requestAnimationFrame(() => disclaimerRef.current?.focus());
        return () => window.cancelAnimationFrame(frame);
    }, [showDisclaimerModal]);

    const focusableInDisclaimer = () =>
        Array.from(
            disclaimerRef.current?.querySelectorAll<HTMLElement>(
                'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])',
            ) ?? [],
        );

    const handleDisclaimerKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
        if (e.key === 'Escape') {
            /* Escape deliberately does NOT dismiss. The dialog is the gate that
             * records the non-emergency acknowledgement, and the portal behind
             * it is unusable until that is recorded -- so a "close" that left
             * the resident staring at the same blocked page would only look
             * broken, and a close that let them through would make Escape a
             * silent substitute for reading the 911 notice. Instead focus goes
             * back to the checkbox, which is the way out. */
            e.preventDefault();
            e.stopPropagation();
            const checkbox = disclaimerRef.current?.querySelector<HTMLElement>('input[type="checkbox"]');
            checkbox?.focus();
            announce('Confirm the non-emergency notice to continue.', 'assertive');
            return;
        }
        if (e.key !== 'Tab') return;

        // Focus trap. The checkbox is `sr-only` but still focusable, so it is
        // part of the cycle; only genuinely disabled controls drop out.
        const focusable = focusableInDisclaimer();
        if (focusable.length === 0) {
            e.preventDefault();
            disclaimerRef.current?.focus();
            return;
        }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        const active = document.activeElement;
        if (e.shiftKey) {
            if (active === first || active === disclaimerRef.current) {
                e.preventDefault();
                last.focus();
            }
        } else if (active === last) {
            e.preventDefault();
            first.focus();
        }
    };

    // Handle disclaimer acknowledgment
    const handleDisclaimerAcknowledge = async () => {
        if (!disclaimerChecked) return;

        // Generate session ID for logging
        const sessionId = localStorage.getItem('session_id') ||
            `sess_${Date.now()}_${Array.from(crypto.getRandomValues(new Uint8Array(6))).map(b => b.toString(36).padStart(2, '0')).join('').slice(0, 9)}`;
        localStorage.setItem('session_id', sessionId);

        // Log acknowledgment to backend
        try {
            await fetch('/api/system/disclaimer/acknowledge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: sessionId })
            });
        } catch (e) {
            // Non-critical - proceed even if logging fails
            console.warn('Failed to log disclaimer acknowledgment:', e);
        }

        // Store acknowledgment locally
        localStorage.setItem('disclaimer_acknowledged_v1', 'true');
        setHasAcknowledgedDisclaimer(true);
        setShowDisclaimerModal(false);
    };

    /* Moving between steps swaps the entire contents of <main>, and the control
     * that caused the swap is unmounted with it -- so focus fell back to
     * <body>. A keyboard user's next Tab restarted from the top of the document
     * and a screen reader said nothing at all about the new page (WCAG 2.4.3
     * Focus Order). Focus goes to the new step's heading instead.
     *
     * A ref callback rather than an effect on `step`, because AnimatePresence
     * runs in "wait" mode here: the incoming step is not in the DOM yet when an
     * effect keyed on `step` would fire. The flag is cleared on the first call
     * so later re-renders cannot yank focus back out from under the resident. */
    const pendingStepFocus = useRef<Step | null>(null);
    const stepHeadingRef = useMemo(() => {
        const make = (target: Step) => (el: HTMLElement | null) => {
            if (el && pendingStepFocus.current === target) {
                pendingStepFocus.current = null;
                el.focus();
            }
        };
        return { categories: make('categories'), form: make('form'), success: make('success') };
    }, []);

    // Error summary shown after a failed submit, and the thing focus lands on.
    const errorSummaryRef = useRef<HTMLDivElement>(null);
    const [errorSummary, setErrorSummary] = useState<{ fieldId: string; message: string }[]>([]);
    /* An effect rather than a call inside the validator: the summary is created
     * by the same state update that the validator makes, so at the moment it
     * returns there is nothing in the DOM to focus yet. A fresh array on every
     * failed attempt means a second press of Submit brings focus back here
     * rather than leaving it on a button that appears to do nothing. */
    useEffect(() => {
        if (errorSummary.length > 0) errorSummaryRef.current?.focus();
    }, [errorSummary]);

    // Handle browser back/forward navigation
    const handleHashChange = useCallback((hash: string) => {
        if (hash === 'track') {
            // Track list view (no specific request selected)
            setShowTrackingView(true);
            // TrackRequests component will handle clearing its internal selectedRequest
        } else if (hash.startsWith('track/')) {
            // Track with specific request - show tracking view
            // TrackRequests will load the request from its initialRequestId or internal state
            setShowTrackingView(true);
        } else if (hash === '' || hash === 'categories') {
            /* Home is home whatever was on screen before. This used to leave
             * `step` alone when arriving from the tracker, so a resident who
             * went submit -> track -> home saw the stale "Request Submitted!"
             * screen at the root URL. The in-memory form is cleared too; the
             * saved draft is NOT -- this is Back/Forward, not a deliberate
             * "start over", so Forward to the form still brings it back. */
            setShowTrackingView(false);
            pendingStepFocus.current = 'categories';
            setStep('categories');
            setSelectedService(null);
            resetFormRef.current();
        } else if (hash.startsWith('report/')) {
            setShowTrackingView(false);
            if (submittedIdRef.current) {
                /* Back from the confirmation: that report is filed. Showing
                 * its filled-in form again invites a duplicate submit, so
                 * start a fresh one for the same category instead. */
                resetFormRef.current();
                setSelectedService(null);
            }
            pendingStepFocus.current = 'form';
            setStep('form');
            // Service will be selected based on the hash - handled in useEffect after services load
        } else if (hash === 'success') {
            setShowTrackingView(false);
            if (submittedIdRef.current) {
                setStep('success');
            } else {
                /* Forward onto a confirmation that no longer exists (it was
                 * reset, or the page reloaded) -- there is no id to show, so
                 * go home and take the dead entry out of the way. */
                pendingStepFocus.current = 'categories';
                setStep('categories');
                setSelectedService(null);
                updateHashRef.current('', true);
            }
        }
    }, []);

    // URL hashing, dynamic titles, and scroll-to-top
    const { updateHash, updateTitle, scrollToTop, currentHash } = usePageNavigation({
        baseTitle: settings?.township_name || 'Resident Portal',
        scrollContainerRef: contentRef,
        onHashChange: handleHashChange,
    });
    updateHashRef.current = updateHash;

    // Update title based on current state (but DON'T update hash here - that causes loops)
    useEffect(() => {
        if (showTrackingView) {
            updateTitle('Track My Requests');
        } else if (step === 'categories') {
            updateTitle('Report an Issue');
        } else if (step === 'form' && selectedService) {
            updateTitle(selectedService.service_name);
        } else if (step === 'success') {
            updateTitle('Request Submitted');
        }
    }, [step, showTrackingView, selectedService, updateTitle]);

    // Handle initial hash on page load (after services are loaded)
    useEffect(() => {
        if (services.length > 0 && currentHash.startsWith('report/')) {
            const serviceCode = currentHash.split('/')[1];
            const service = services.find(s => s.service_code === serviceCode);
            if (service && !selectedService) {
                setSelectedService(service);
                applyServiceRouting(service);
                // Coming back to the form (from the Terms page, a reload, or
                // Forward) restores what the resident had typed; otherwise
                // just set formData.service_code - critical for submission!
                if (!restoreDraftFor(service)) {
                    setFormData((prev) => ({ ...prev, service_code: service.service_code }));
                }
                setStep('form');
            }
        }
        // restoreDraftFor / applyServiceRouting only read setters and the language.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [services, currentHash, selectedService]);

    // Requests for staff map
    const [allRequests, setAllRequests] = useState<ServiceRequest[]>([]);
    // Counts for the map header's chips, from the same list the map draws.
    const mapCounts = useMemo(() => ({
        open: allRequests.filter(r => r.status === 'open').length,
        inProgress: allRequests.filter(r => r.status === 'in_progress').length,
        closed: allRequests.filter(r => r.status === 'closed').length,
    }), [allRequests]);

    // Form state
    const [formData, setFormData] = useState<ServiceRequestCreate>({
        service_code: '',
        description: '',
        address: '',
        first_name: '',
        last_name: '',
        email: '',
        phone: '',
        is_public: true,
    });
    const [formErrors, setFormErrors] = useState<Record<string, string>>({});

    // Blocking state for third-party/road-based services
    const [isBlocked, setIsBlocked] = useState(false);
    // Named separately from the message so the notice can say WHO handles it
    // rather than only quoting the town's configured sentence.
    const [blockJurisdiction, setBlockJurisdiction] = useState<string | null>(null);
    const [blockMessage, setBlockMessage] = useState('');
    // Whether blockMessage is the backend's generated sentence rather than the
    // clerk's own, so the notice can avoid restating its own heading.
    const [blockMessageIsDefault, setBlockMessageIsDefault] = useState(false);
    const [blockContacts, setBlockContacts] = useState<RedirectContact[]>([]);

    // Custom question answers
    const [customAnswers, setCustomAnswers] = useState<Record<string, string | string[]>>({});

    /* Photos and their pick-time screening -- see usePhotoAttachments. The
     * names below are the ones this form has always used. */
    const {
        photos: attachedPhotos,
        previewUrls: photoPreviewUrls,
        statuses: photoStatuses,
        blocked: blockedPhotos,
        stillChecking: photosStillChecking,
        add: handlePhotoUpload,
        remove: handleRemovePhoto,
        reset: resetPhotos,
    } = usePhotoAttachments();

    const [mapLayers, setMapLayers] = useState<MapLayer[]>([]);
    // Selected asset from map layer (for report logging)
    const [selectedAsset, setSelectedAsset] = useState<{ layerName: string; properties: Record<string, any>; lat: number; lng: number } | null>(null);

    // Location/GPS state  
    const [location, setLocation] = useState<{ address: string; lat: number | null; lng: number | null }>({
        address: '',
        lat: null,
        lng: null
    });
    // The whole payload, not just a key: the provider and its own credentials
    // live in here, and gating on a Google key left an Esri town with no map.
    const [mapsRaw, setMapsRaw] = useState<RawMapsConfig | null>(null);
    const mapConfig = useMemo(() => resolveMapProviderConfig(mapsRaw), [mapsRaw]);
    const [townshipBoundary, setTownshipBoundary] = useState<object | null>(null);
    const [isLocationOutOfBounds, setIsLocationOutOfBounds] = useState(false);


    // Load Maps API key and configuration
    useEffect(() => {
        api.getMapsConfig().then((config) => {
            setMapsRaw(config);
            if (config.township_boundary) {
                setTownshipBoundary(config.township_boundary);
            }
        }).catch(() => { });

        // Load custom map layers (public endpoint)
        api.getMapLayers().then((layers) => {
            setMapLayers(layers);
        }).catch(() => { });
    }, []);



    // Reload services when language changes
    useEffect(() => {
        loadServices();
    }, [language]);

    const loadServices = async () => {
        try {
            const data = await api.getServices();
            setServices(data);
        } catch (err) {
            console.error('Failed to load services:', err);
        } finally {
            setIsLoading(false);
        }
    };

    // Load requests for the map (public endpoint - includes department/staff for filtering)
    useEffect(() => {
        api.getPublicRequests().then((requests) => {
            // Cast to ServiceRequest since we now include assigned_department_id and assigned_to
            setAllRequests(requests as unknown as ServiceRequest[]);
        }).catch(() => { });
    }, []);

    const filteredServices = services.filter(
        (s) =>
            s.service_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
            s.description?.toLowerCase().includes(searchQuery.toLowerCase())
    );

    /** Blocking state a category carries before any pin is dropped. */
    function applyServiceRouting(service: ServiceDefinition) {
        // Clear any previous blocking state and selected asset
        setIsBlocked(false);
        setBlockMessage('');
        setBlockContacts([]);
        setSelectedAsset(null); // Reset asset selection for new category

        // Check if third-party only service - block immediately
        if (service.routing_mode === 'third_party') {
            setIsBlocked(true);
            setBlockMessage(service.routing_config?.message || '');
            setBlockMessageIsDefault(!(service.routing_config?.message || '').trim());
            setBlockContacts(service.routing_config?.contacts || []);
            // Same fallback the backend uses for this mode: no agency-name field
            // exists, so the first contact's name is who the clerk named.
            setBlockJurisdiction(
                service.routing_config?.third_party_name
                || service.routing_config?.contacts?.[0]?.name
                || null,
            );
        }
    }

    /**
     * Put a saved draft back into the form, if it is for this category.
     * Returns whether anything was restored. Photos are not part of a draft;
     * if there were some, the form says to add them again.
     */
    function restoreDraftFor(service: ServiceDefinition): boolean {
        const draft: ResidentDraft | null = loadResidentDraft();
        if (!draft || draft.service_code !== service.service_code || !draftHasContent(draft)) return false;
        setFormData({
            service_code: service.service_code,
            description: draft.description,
            address: draft.address,
            lat: draft.lat ?? undefined,
            long: draft.lng ?? undefined,
            first_name: draft.first_name,
            last_name: draft.last_name,
            email: draft.email,
            phone: draft.phone,
            is_public: draft.is_public,
        });
        setLocation({ address: draft.address, lat: draft.lat, lng: draft.lng });
        setCustomAnswers(draft.custom_answers);
        setPhotosToReadd(draft.photo_count);
        if (draft.preferred_language && draft.preferred_language !== language && typeof setLanguage === 'function') {
            setLanguage(draft.preferred_language);
        }
        if (draft.lat != null && draft.lng != null) {
            void checkRoadBasedBlocking(service, draft.lat, draft.lng);
        }
        return true;
    }

    const handleSelectService = (service: ServiceDefinition) => {
        setSelectedService(service);
        if (!restoreDraftFor(service)) {
            setFormData((prev) => ({ ...prev, service_code: service.service_code }));
        }
        applyServiceRouting(service);

        pendingStepFocus.current = 'form';
        setStep('form');
        updateHash(`report/${service.service_code}`);
        scrollToTop('instant');
    };

    // Which road the pin landed on, shown under the map so a resident can see
    // the system agreed with them before they type anything.
    const [detectedRoad, setDetectedRoad] = useState<{ name: string; distance_m: number } | null>(null);
    const roadCheckSeq = useRef(0);

    /**
     * Ask the server whether a report here would be redirected.
     *
     * This used to lowercase the whole formatted address and substring-match
     * configured road names into it, which put the city, county and ZIP into
     * the match surface and read a corner lot's address off the cross street.
     * The server measures distance to real road geometry instead. It also
     * re-runs the same check on submit, so this is a courtesy rather than the
     * enforcement point -- and it fails open: a check that errors never blocks.
     */
    const checkRoadBasedBlocking = useCallback(async (service: ServiceDefinition, lat?: number, lng?: number) => {
        if (service.routing_mode !== 'road_based') return;
        const seq = ++roadCheckSeq.current;
        try {
            const result = await api.roadCheck(service.service_code, lat, lng);
            // A slower earlier request must not overwrite a newer answer.
            if (seq !== roadCheckSeq.current) return;
            setDetectedRoad(result.detected_road);
            setIsBlocked(result.blocked);
            setBlockMessage(result.blocked ? result.message : '');
            setBlockMessageIsDefault(Boolean(result.blocked && result.message_is_default));
            setBlockContacts(
                result.blocked
                    ? (result.contacts || []).map(c => ({
                        name: c.name || '',
                        phone: c.phone || '',
                        // Collected in the routing modal and previously dropped here,
                        // so an agency that only publishes an address was unreachable.
                        email: (c as { email?: string }).email || '',
                        url: c.url || '',
                    }))
                    : [],
            );
            setBlockJurisdiction(result.blocked ? result.jurisdiction : null);

            /* One announcement for one event (WCAG 4.1.3 Status Messages).
             * Dropping a pin used to populate two polite live regions in the
             * same tick -- the "Road detected" line and the whole redirect
             * notice, which was itself marked role="status" and so queued its
             * entire body including every phone number. Two polite regions
             * updating together means a screen reader reads neither, so the pin
             * drop was silent. Both roles are gone; this composes the same
             * facts into a single sentence and sends it through the app's one
             * live region. */
            const road = result.detected_road?.name;
            const who = result.jurisdiction || 'another agency';
            const sentence = result.blocked
                ? road
                    ? `Road detected: ${road}. ${road} is handled by ${who}. Contact details are shown below.`
                    : `This location is handled by ${who}. Contact details are shown below.`
                : road
                    ? `Road detected: ${road}.`
                    : '';
            if (sentence) announce(sentence);
        } catch {
            if (seq !== roadCheckSeq.current) return;
            setDetectedRoad(null);
            setIsBlocked(false);
            setBlockMessage('');
            setBlockContacts([]);
            setBlockJurisdiction(null);
        }
    }, [announce]);

    /* Field ids are fixed rather than generated so the error summary can link
     * straight at them. `q.id` is the clerk-assigned question id, unique within
     * a category, which is the same key the error map already uses. */
    const FIELD_IDS = {
        description: 'field-description',
        address: 'field-address',
        email: 'field-email',
        phone: 'field-phone',
    } as const;
    const customFieldId = (questionId: string) => `field-custom-${questionId}`;

    const validateForm = (): boolean => {
        const errors: Record<string, string> = {};

        if (!formData.description || formData.description.length < 10) {
            errors.description = 'Describe the issue in at least 10 characters.';
        }
        if (!formData.email || !/\S+@\S+\.\S+/.test(formData.email)) {
            errors.email = 'Enter a valid email address.';
        }
        if (formData.phone && !isValidPhone(formData.phone)) {
            errors.phone = 'Enter a valid phone number, such as (555) 123-4567.';
        }
        // The server refuses it too; checking here saves the round trip.
        if (locationMode === 'required') {
            const hasPin = formData.lat != null && formData.long != null;
            if (!(formData.address || '').trim() && !hasPin) {
                errors.address = 'Choose a spot on the map or enter an address.';
            }
        }

        // Validate required custom questions
        const questions = selectedService?.routing_config?.custom_questions;
        if (questions) {
            for (const q of questions) {
                if (q.required) {
                    const answer = customAnswers[q.label];
                    const isEmpty = answer === undefined || answer === '' || (Array.isArray(answer) && answer.length === 0);
                    if (isEmpty) {
                        errors[`custom_${q.id}`] = `${q.label} is required`;
                    }
                }
            }
        }

        setFormErrors(errors);

        /* WCAG 3.3.1 Error Identification. Failing validation used to do nothing
         * a keyboard or screen-reader user could perceive: the messages appeared
         * next to fields far up a long form, focus stayed on the submit button,
         * and nothing was announced. The summary is a named list of what is
         * wrong, each entry linking at the field it is about, and focus moves
         * onto it -- so "Submit" always leads somewhere. */
        const summary = Object.entries(errors)
            .filter(([key]) => key !== 'submit')
            .map(([key, message]) => ({
                fieldId: key.startsWith('custom_')
                    ? customFieldId(key.slice('custom_'.length))
                    : FIELD_IDS[key as keyof typeof FIELD_IDS],
                message,
            }));
        setErrorSummary(summary);

        return Object.keys(errors).length === 0;
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!validateForm()) return;

        // A photo the screen refused cannot be attached, and the resident was
        // already told so at the thumbnail. Refusing here too means a client
        // that ignores the pick-time answer gets the same one -- the server
        // refuses it a third time, which is where it actually counts.
        if (blockedPhotos.length) {
            setFormErrors({
                submit: "One of your photos can't be used. Remove it and submit again.",
            });
            return;
        }

        setIsSubmitting(true);
        try {
            // Matched asset: ONLY use user-selected asset (no automatic proximity detection)
            let matchedAsset: typeof formData.matched_asset = undefined;

            // User explicitly clicked "Select this..." on an asset marker
            if (selectedAsset) {
                matchedAsset = {
                    layer_name: selectedAsset.layerName,
                    layer_id: 0, // Will be filled in by backend
                    asset_id: selectedAsset.properties.asset_id || selectedAsset.properties.id,
                    asset_type: selectedAsset.properties.asset_type || selectedAsset.layerName,
                    properties: selectedAsset.properties,
                    distance_meters: 0, // Exact selection, no distance
                };
            }
            // Note: No automatic proximity detection - user must explicitly select an asset

            // A photo screened at pick time travels as its handle -- a short
            // string instead of megabytes of base64, and no second Vision call.
            // Anything the screen did not clear travels inline and takes the
            // original at-submit path, which is also what an Open311 client or
            // a connector does; nothing about that path changed.
            const usable = attachedPhotos.filter((p) => p.state !== 'blocked').slice(0, 3);
            const inlineFallback: Record<string, string> = {};
            usable.forEach((p) => { if (p.handle) inlineFallback[p.handle] = p.original; });

            // A category that collects no location sends none, and an empty
            // address is no address -- the server normalises both the same way.
            const blankAddress = !(formData.address || '').trim();
            const result = await api.createRequest({
                ...formData,
                address: locationMode === 'hidden' || blankAddress ? undefined : formData.address,
                lat: locationMode === 'hidden' ? undefined : formData.lat,
                long: locationMode === 'hidden' ? undefined : formData.long,
                preferred_language: language,  // Capture user's selected language for notifications
                media_urls: usable.map((p) => p.handle || p.original),
                matched_asset: matchedAsset,
                custom_fields: customAnswers,
            }, inlineFallback);
            setSubmittedId(result.service_request_id);
            setSubmittedPhotosHeld(result.photos_pending_review ?? 0);
            // Filed: the draft (contact details included) has done its job.
            clearResidentDraft();
            setPhotosToReadd(0);
            pendingStepFocus.current = 'success';
            // Save to localStorage so Track Requests can identify "your" submissions
            try {
                const myRequests: string[] = JSON.parse(localStorage.getItem('my_requests') || '[]');
                if (!myRequests.includes(result.service_request_id)) {
                    myRequests.push(result.service_request_id);
                    localStorage.setItem('my_requests', JSON.stringify(myRequests));
                }
            } catch { /* ignore localStorage errors */ }
            setStep('success');
            updateHash('success');
            scrollToTop('instant');
        } catch (err) {
            console.error('Failed to submit request:', err);
            setFormErrors({ submit: "Your request wasn't submitted. Try again." });
        } finally {
            setIsSubmitting(false);
        }
    };
    /** Empty the form and forget the last submission (in memory only). */
    const resetForm = () => {
        setFormData({
            service_code: '',
            description: '',
            address: '',
            first_name: '',
            last_name: '',
            email: '',
            phone: '',
            is_public: true,
        });
        setFormErrors({});
        setErrorSummary([]);
        setSubmittedId(null);
        submittedIdRef.current = null;
        setSubmittedPhotosHeld(0);
        resetPhotos();
        setPhotosToReadd(0);
        setLocation({ address: '', lat: null, lng: null });
        setSelectedAsset(null);
        setDetectedRoad(null);
        // Clear blocking state
        setIsBlocked(false);
        setBlockMessage('');
        setBlockContacts([]);
        setBlockJurisdiction(null);
        // Clear custom answers
        setCustomAnswers({});
    };
    resetFormRef.current = resetForm;

    /**
     * Every deliberate "go home" -- the header logo, "Back to Home" on the
     * tracker, "Back to categories" on the form, "Submit Another Request".
     *
     * These used to each flip a different subset of the view state. "Back to
     * Home" on the tracker only hid the tracker and cleared the hash, leaving
     * `step` on 'success', so the root URL showed the old confirmation until
     * the logo was pressed. One function now resets all of it: the step, the
     * submission, the form, the saved draft, the scroll position and focus.
     */
    const goHome = ({ replace = false }: { replace?: boolean } = {}) => {
        resetForm();
        clearResidentDraft();
        setShowTrackingView(false);
        setSelectedService(null);
        pendingStepFocus.current = 'categories';
        setStep('categories');
        updateHash('', replace);
        scrollToTop('instant');
    };

    // "Submit Another Request" replaces the #success entry, as it always has,
    // so Back from the fresh home page does not land on a dead confirmation.
    const handleReset = () => goHome({ replace: true });

    /* Keep the in-progress report in this tab's sessionStorage so following
     * the Terms link (or a reload) does not lose it. Only while a form is on
     * screen and nothing has been filed from it. */
    useEffect(() => {
        if (step !== 'form' || !selectedService || submittedId || showTrackingView) return;
        saveResidentDraft({
            service_code: selectedService.service_code,
            description: formData.description || '',
            address: formData.address || '',
            lat: formData.lat ?? null,
            lng: formData.long ?? null,
            first_name: formData.first_name || '',
            last_name: formData.last_name || '',
            email: formData.email || '',
            phone: formData.phone || '',
            is_public: formData.is_public !== false,
            custom_answers: customAnswers,
            preferred_language: language,
            photo_count: attachedPhotos.length || photosToReadd,
        });
    }, [step, selectedService, submittedId, showTrackingView, formData, customAnswers, language, attachedPhotos.length, photosToReadd]);

    // Once a photo is added again, the "add your photos again" note is done.
    useEffect(() => {
        if (attachedPhotos.length > 0) setPhotosToReadd(0);
    }, [attachedPhotos.length]);


    const getIcon = (iconName: string) => {
        const IconComponent = categoryIconFor(iconName);
        return <IconComponent className="w-8 h-8" />;
    };

    return (
        <div className="min-h-screen flex flex-col">
            {/* Header Container - Reorders on mobile (banner first, then nav) */}
            <div className="flex flex-col-reverse md:flex-col sticky top-0 z-40">
                {/* Navigation - Clean Mobile Header */}
                <nav className="glass-sidebar py-3 md:py-4 px-4 md:px-6 flex items-center justify-between relative z-10" aria-label="Main navigation">
                    <button
                        onClick={() => goHome()}
                        className="flex items-center gap-2 md:gap-3 hover:opacity-80 transition-opacity cursor-pointer"
                        aria-label="Go to home page"
                    >
                        {settings?.logo_url ? (
                            <img src={settings.logo_url} alt="Logo" className="h-8 md:h-10 w-auto" />
                        ) : (
                            <div className="w-8 h-8 md:w-10 md:h-10 rounded-xl bg-gradient-to-br from-primary-400 to-primary-600 flex items-center justify-center">
                                <Home className="w-4 h-4 md:w-6 md:h-6 text-white" />
                            </div>
                        )}
                        {/* A brand mark inside the home button, not a page heading.
                            As an <h1> it produced two level-one headings on every
                            view, and the button's own aria-label overrode it, so the
                            heading a screen-reader user reached said "Go to home page"
                            (WCAG 1.3.1 / 2.4.6). The page's single <h1> lives in
                            <main>, where it names the view. */}
                        <span className="text-lg md:text-xl font-semibold text-white hidden sm:block" data-no-translate>
                            {settings?.township_name || 'Municipality 311'}
                        </span>
                    </button>

                    <div className="flex items-center gap-2 md:gap-4">
                        {/* Language selector */}
                        {translationEnabled && <LanguageSelector />}
                        <div className="relative">
                            <Link
                                to="/login"
                                className="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white/70 hover:text-white text-xs md:text-sm font-medium transition-all border border-white/10 hover:border-white/20 no-underline decoration-transparent"
                            >
                                Staff Login
                            </Link>
                        </div>
                    </div>
                </nav>

                {/* Persistent Non-Emergency Warning Banner */}
                <div className="bg-slate-900/95 backdrop-blur-sm">
                    <div className="bg-gradient-to-r from-amber-500/30 via-orange-500/30 to-red-500/30 border-b border-amber-500/30">
                        <div className="max-w-6xl mx-auto px-4 py-2 flex items-center justify-center gap-2 text-center">
                            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
                            <p className="text-amber-200 text-sm">
                                <strong>Non-Emergency Only</strong> — For police, fire, or medical emergencies, call <strong className="text-white">911</strong>
                            </p>
                        </div>
                    </div>
                </div>
            </div>

            {/* Non-Emergency Disclaimer Modal - Friendly Welcome Design */}
            <AnimatePresence>
                {showDisclaimerModal && (
                    <motion.div
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 flex items-center justify-center p-4"
                    >
                        <motion.div
                            ref={disclaimerRef}
                            initial={{ scale: 0.95, opacity: 0, y: 20 }}
                            animate={{ scale: 1, opacity: 1, y: 0 }}
                            exit={{ scale: 0.95, opacity: 0, y: 20 }}
                            transition={{ type: "spring", damping: 25, stiffness: 300 }}
                            role="dialog"
                            aria-modal="true"
                            aria-labelledby="disclaimer-title"
                            aria-describedby="disclaimer-body"
                            tabIndex={-1}
                            onKeyDown={handleDisclaimerKeyDown}
                            className="bg-gradient-to-br from-slate-800 via-slate-800 to-slate-900 rounded-2xl max-w-lg w-full p-6 border border-white/10 shadow-2xl focus:outline-none"
                        >
                            {/* Friendly Welcome Header */}
                            <div className="text-center mb-6">
                                {settings?.logo_url ? (
                                    <img
                                        src={settings.logo_url}
                                        alt={settings?.township_name || "Municipality"}
                                        className="h-12 mx-auto mb-4 object-contain"
                                    />
                                ) : (
                                    <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary-500 to-purple-600 flex items-center justify-center mx-auto mb-4 shadow-lg shadow-primary-500/25">
                                        <Sparkles className="w-8 h-8 text-white" />
                                    </div>
                                )}
                                <h2 id="disclaimer-title" className="text-2xl font-bold text-white mb-1">
                                    Welcome to {settings?.township_name || "311 Services"}
                                </h2>
                                <p className="text-white/60 text-sm">Your community service request portal</p>
                            </div>

                            {/* Helpful Info Card - Not scary! */}
                            <div id="disclaimer-body" className="bg-gradient-to-r from-blue-500/10 via-indigo-500/10 to-purple-500/10 border border-blue-400/20 rounded-xl p-4 mb-6">
                                <div className="flex items-start gap-3">
                                    <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center flex-shrink-0">
                                        <Phone className="w-5 h-5 text-blue-400" />
                                    </div>
                                    <div>
                                        <h3 className="text-blue-300 font-semibold mb-1">Quick Reminder</h3>
                                        <p className="text-white/70 text-sm leading-relaxed">
                                            This portal is for <strong className="text-white">non-emergency requests</strong> like
                                            potholes, streetlights, trash pickup, and general municipal services.
                                        </p>
                                    </div>
                                </div>

                                <div className="mt-3 pt-3 border-t border-white/10">
                                    <p className="text-white/60 text-sm flex items-start gap-2">
                                        <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />
                                        <span>For emergencies (police, fire, medical), call <strong className="text-white whitespace-nowrap">911</strong></span>
                                    </p>
                                </div>
                            </div>

                            {/* Friendly Checkbox */}
                            <label className="flex items-center gap-3 mb-6 cursor-pointer group p-3 rounded-xl bg-white/5 hover:bg-white/10 transition-colors border border-transparent hover:border-white/10">
                                <div className="relative">
                                    <input
                                        type="checkbox"
                                        checked={disclaimerChecked}
                                        onChange={(e) => setDisclaimerChecked(e.target.checked)}
                                        className="sr-only peer"
                                    />
                                    {/* peer-focus-visible, not just peer-checked: the real
                                        checkbox is sr-only, so this square is the only thing
                                        on screen that can show it has focus. Without the ring
                                        a keyboard user tabbing into the one control that gates
                                        the whole portal saw nothing move (WCAG 2.4.7). */}
                                    <div className="w-6 h-6 rounded-lg border-2 border-white/30 peer-checked:border-primary-500 peer-checked:bg-primary-500 peer-focus-visible:ring-2 peer-focus-visible:ring-white peer-focus-visible:ring-offset-2 peer-focus-visible:ring-offset-slate-800 transition-all flex items-center justify-center">
                                        {disclaimerChecked && (
                                            <CheckCircle2 className="w-4 h-4 text-white" />
                                        )}
                                    </div>
                                </div>
                                <span className="text-white/80 text-sm leading-relaxed group-hover:text-white transition-colors">
                                    I'll use this portal for non-emergency requests and call 911 for emergencies.
                                </span>
                            </label>

                            {/* Welcoming Continue Button */}
                            <Button
                                onClick={handleDisclaimerAcknowledge}
                                disabled={!disclaimerChecked}
                                className={`w-full py-3 text-base font-medium ${!disclaimerChecked ? 'opacity-50 cursor-not-allowed' : 'bg-gradient-to-r from-primary-500 to-purple-600 hover:from-primary-600 hover:to-purple-700'}`}
                            >
                                {disclaimerChecked ? "Get started →" : "Check the box above to continue"}
                            </Button>
                        </motion.div>
                    </motion.div>
                )}
            </AnimatePresence>


            {/* Main Content */}
            <main id="main-content" className="flex-1 px-4 py-8 md:px-8 max-w-6xl mx-auto w-full">
                {/* Tracking View */}
                {showTrackingView ? (
                    <div className="space-y-6">
                        <button
                            type="button"
                            onClick={() => goHome()}
                            className="btn-outline btn-outline-md"
                            aria-label="Go back to home page"
                        >
                            <ArrowLeft className="w-5 h-5" />
                            <span>Back to Home</span>
                        </button>
                        <TrackRequests
                            initialRequestId={urlRequestId || hashRequestId}
                            selectedRequestId={
                                currentHash === 'track' ? null :
                                    currentHash.startsWith('track/') ? currentHash.split('/')[1] :
                                        urlRequestId || hashRequestId || null
                            }
                            onRequestSelect={(requestId) => {
                                if (requestId) {
                                    updateHash(`track/${requestId}`);
                                } else {
                                    updateHash('track');
                                }
                            }}
                        />
                    </div>
                ) : (
                    <AnimatePresence mode="wait">
                        {step === 'categories' && (
                            <motion.div
                                key="categories"
                                initial={{ opacity: 0, y: 20 }}
                                animate={{ opacity: 1, y: 0 }}
                                exit={{ opacity: 0, y: -20 }}
                                className="space-y-8"
                            >
                                {/* Hero Section. Padded above so the heading isn't crowded by
                                    the banner and navigation. */}
                                <div className="text-center space-y-6 pt-4 sm:pt-6 md:pt-8">
                                    <motion.h1
                                        ref={stepHeadingRef.categories}
                                        tabIndex={-1}
                                        initial={{ y: 20, opacity: 0 }}
                                        animate={{ y: 0, opacity: 1 }}
                                        transition={{ delay: 0.2 }}
                                        className="text-4xl md:text-5xl lg:text-6xl font-bold text-gradient focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 rounded-lg"
                                    >
                                        {settings?.hero_text || 'How can we help?'}
                                    </motion.h1>

                                    <motion.p
                                        initial={{ y: 20, opacity: 0 }}
                                        animate={{ y: 0, opacity: 1 }}
                                        transition={{ delay: 0.3 }}
                                        className="text-lg text-white/60 max-w-xl mx-auto"
                                    >
                                        {"Report issues, request services, and help make our community better. Select a category below to get started."}
                                    </motion.p>

                                    {/* Search */}
                                    <motion.div
                                        initial={{ y: 20, opacity: 0 }}
                                        animate={{ y: 0, opacity: 1 }}
                                        transition={{ delay: 0.4 }}
                                        className="max-w-md mx-auto"
                                    >
                                        <div className="relative">
                                            <label htmlFor="service-search" className="sr-only">{"Search services..."}</label>
                                            {/* z-10 is load-bearing, not decoration.
                                                `.glass-input` carries
                                                backdrop-filter: blur(10px),
                                                which makes the input its own
                                                stacking context. This icon is a
                                                positioned sibling at z-index
                                                auto and the input comes after it
                                                in the DOM, so the input painted
                                                on top and its backdrop blurred
                                                the icon into a grey smudge. The
                                                same thing hid the CSS
                                                background-image this replaced,
                                                so the escaped data URI was never
                                                the problem.

                                                The lucide component regardless:
                                                every other search field in the
                                                app uses it, so this one now
                                                matches them in stroke weight and
                                                colour. */}
                                            <Search
                                                className="absolute left-4 top-1/2 -translate-y-1/2 w-5 h-5 text-white/70 pointer-events-none z-10"
                                                aria-hidden="true"
                                            />
                                            <input
                                                id="service-search"
                                                type="text"
                                                placeholder={"Search services..."}
                                                value={searchQuery}
                                                onChange={(e) => setSearchQuery(e.target.value)}
                                                className="glass-input pl-12"
                                                aria-describedby="search-results-count"
                                            />
                                        </div>
                                        <p id="search-results-count" className="sr-only" aria-live="polite">
                                            {filteredServices.length} services found
                                        </p>
                                    </motion.div>
                                </div>

                                {/* Service Categories Grid */}
                                {isLoading ? (
                                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4" role="status" aria-label="Loading services">
                                        {Array.from({ length: 8 }).map((_, i) => (
                                            <div key={i} className="rounded-2xl border border-white/10 bg-white/5 p-6 animate-pulse">
                                                <div className="w-12 h-12 rounded-xl bg-white/10 mb-4" />
                                                <div className="h-4 bg-white/10 rounded w-3/4 mb-2" />
                                                <div className="h-3 bg-white/[.06] rounded w-full mb-1" />
                                                <div className="h-3 bg-white/[.06] rounded w-2/3" />
                                            </div>
                                        ))}
                                        <span className="sr-only">Loading service categories...</span>
                                    </div>
                                ) : (
                                    <motion.div
                                        initial={{ opacity: 0 }}
                                        animate={{ opacity: 1 }}
                                        transition={{ delay: 0.5 }}
                                        className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
                                    >
                                        {filteredServices.map((service, index) => (
                                            <motion.div
                                                key={service.id}
                                                initial={{ opacity: 0, y: 20 }}
                                                animate={{ opacity: 1, y: 0 }}
                                                transition={{ delay: 0.1 * index }}
                                            >
                                                <Card
                                                    hover
                                                    onClick={() => handleSelectService(service)}
                                                    className="h-full"
                                                >
                                                    <div className="flex flex-col items-center text-center space-y-3">
                                                        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary-500/30 to-primary-600/30 flex items-center justify-center text-primary-300">
                                                            {getIcon(service.icon)}
                                                        </div>
                                                        <h3 className="font-semibold text-white">
                                                            {service.service_name}
                                                        </h3>
                                                        <p className="text-sm text-white/50 line-clamp-2">
                                                            {service.description}
                                                        </p>
                                                    </div>
                                                </Card>
                                            </motion.div>
                                        ))}
                                    </motion.div>
                                )}

                                {filteredServices.length === 0 && !isLoading && (
                                    <div className="text-center py-12">
                                        <p className="text-white/60">No services found matching your search.</p>
                                    </div>
                                )}

                                {/* Community Map Section */}
                                {/* Section Divider - Modern Wave */}
                                <div className="my-16 relative">
                                    <svg className="w-full h-12" viewBox="0 0 1200 60" preserveAspectRatio="none">
                                        <defs>
                                            <linearGradient id="waveGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                                                <stop offset="0%" stopColor="rgba(79, 70, 229, 0)" />
                                                <stop offset="20%" stopColor="rgba(99, 102, 241, 0.7)" />
                                                <stop offset="50%" stopColor="rgba(139, 92, 246, 0.9)" />
                                                <stop offset="80%" stopColor="rgba(99, 102, 241, 0.7)" />
                                                <stop offset="100%" stopColor="rgba(79, 70, 229, 0)" />
                                            </linearGradient>
                                        </defs>
                                        <path
                                            d="M0,30 C300,10 600,50 900,30 C1050,20 1150,35 1200,30"
                                            fill="none"
                                            stroke="url(#waveGradient)"
                                            strokeWidth="4"
                                            strokeLinecap="round"
                                        />
                                    </svg>
                                </div>
                                <motion.div
                                    initial={{ opacity: 0, y: 20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ delay: 0.6 }}
                                    className="glass-card rounded-3xl border border-white/10 overflow-hidden"
                                >
                                    {/* One card: a header that says what the map is and
                                        what is on it right now, then the map itself. */}
                                    <div className="flex flex-col gap-4 p-5 sm:p-6 sm:flex-row sm:items-center sm:justify-between border-b border-white/10">
                                        <div className="flex items-start gap-3 min-w-0">
                                            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-primary-400/30 bg-primary-500/15 text-primary-200" aria-hidden="true">
                                                <MapIcon className="h-5 w-5" />
                                            </span>
                                            <div className="min-w-0">
                                                <h2 className="text-xl sm:text-2xl font-semibold text-white tracking-tight">
                                                    {"Community Requests Map"}
                                                </h2>
                                                <p className="text-sm text-white/60 mt-0.5">
                                                    {"See what neighbors have reported and the status of each request. Select a pin for details."}
                                                </p>
                                            </div>
                                        </div>
                                        {allRequests.length > 0 && (
                                            <ul className="flex flex-wrap gap-2 sm:justify-end" aria-label="Requests on the map">
                                                <li><Chip tone="danger" size="sm">{mapCounts.open} open</Chip></li>
                                                <li><Chip tone="warning" size="sm">{mapCounts.inProgress} in progress</Chip></li>
                                                <li><Chip tone="success" size="sm">{mapCounts.closed} resolved</Chip></li>
                                            </ul>
                                        )}
                                    </div>
                                    <div className="h-[500px]">
                                        <StaffDashboardMap
                                            config={mapConfig}
                                            requests={allRequests}
                                            /* No asset layers on the public map.
                                               These are the town's own
                                               infrastructure -- hydrants, catch
                                               basins, signs -- drawn as hollow
                                               rings that sit among the request
                                               pins and read as reports that are
                                               not there. A resident looking at
                                               "Community Requests" should see
                                               requests. Staff still get them on
                                               the dashboard, where the layer
                                               list explains what they are.
                                               Polygon layers an admin put on
                                               the portal (parcels, zones) are
                                               the exception: drawn as faint,
                                               shape-only outlines at parcel
                                               zoom, never as pins. */
                                            mapLayers={[]}
                                            residentOutlines
                                            services={services}
                                            departments={[]}
                                            users={[]}
                                            townshipBoundary={townshipBoundary}
                                            onRequestSelect={(requestId) => {
                                                if (requestId) {
                                                    updateHash(`track/${requestId}`);
                                                    setShowTrackingView(true);
                                                    scrollToTop('instant');
                                                }
                                            }}
                                        />
                                    </div>
                                </motion.div>

                                {/* Track Requests Button */}
                                <motion.div
                                    initial={{ opacity: 0, y: 20 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ delay: 0.7 }}
                                    className="text-center pt-8"
                                >
                                    <Button
                                        onClick={() => {
                                            setShowTrackingView(true);
                                            updateHash('track');
                                            scrollToTop('instant');
                                        }}
                                        variant="secondary"
                                        size="lg"
                                        className="px-8 py-4"
                                    >
                                        <ClipboardList className="w-5 h-5 mr-2" />
                                        {"Track My Requests"}
                                    </Button>
                                </motion.div>
                            </motion.div>
                        )}

                        {step === 'form' && selectedService && (
                            <motion.div
                                key="form"
                                initial={{ opacity: 0, x: 50 }}
                                animate={{ opacity: 1, x: 0 }}
                                exit={{ opacity: 0, x: -50 }}
                                className="max-w-2xl mx-auto space-y-6"
                            >
                                <button
                                    type="button"
                                    onClick={() => goHome()}
                                    className="btn-outline btn-outline-md"
                                >
                                    <ArrowLeft className="w-5 h-5" />
                                    <span>{"Back to categories"}</span>
                                </button>

                                {/* Selected service indicator */}
                                <div className="flex items-center gap-4 p-4 glass-card">
                                    <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-primary-500/30 to-primary-600/30 flex items-center justify-center text-primary-300">
                                        {getIcon(selectedService.icon)}
                                    </div>
                                    <div>
                                        {/* The one <h1> for this view: it names what the
                                            resident is now reporting. Focus lands here when
                                            the step changes (WCAG 2.4.3). */}
                                        <h1
                                            ref={stepHeadingRef.form}
                                            tabIndex={-1}
                                            className="text-lg font-semibold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 rounded-lg"
                                        >
                                            {selectedService.service_name}
                                        </h1>
                                        <p className="text-sm text-white/50">{selectedService.description}</p>
                                    </div>
                                </div>

                                {/* Whole service handled elsewhere -- not about a location, so the
                                    notice omits the road line. Same component as the road-based
                                    redirect so a resident meets one design, not two. */}
                                {isBlocked && selectedService.routing_mode === 'third_party' && (
                                    <RedirectNotice
                                        variant="service"
                                        jurisdiction={blockJurisdiction}
                                        message={blockMessage}
                                        messageIsDefault={blockMessageIsDefault}
                                        contacts={blockContacts}
                                        serviceName={selectedService.service_name}
                                    />
                                )}

                                {/* Form - only show if NOT blocked OR if road-based (need address first) */}
                                {(!isBlocked || selectedService.routing_mode === 'road_based') && (
                                    <form onSubmit={handleSubmit} className="space-y-6">
                                        <Card>
                                            <div className="space-y-5">
                                                <Textarea
                                                    id={FIELD_IDS.description}
                                                    label={"Description"}
                                                    placeholder="Describe the issue..."
                                                    value={formData.description}
                                                    onChange={(e) =>
                                                        setFormData((prev) => ({ ...prev, description: e.target.value }))
                                                    }
                                                    error={formErrors.description}
                                                    /* Announced by the error summary that takes
                                                       focus, not by an alert of its own -- see the
                                                       summary below. */
                                                    errorAsAlert={false}
                                                    required
                                                />

                                                {/* Location: per category, required, optional or not collected */}
                                                {locationMode === 'hidden' ? (
                                                    <div className="flex items-center gap-3 p-4 rounded-xl bg-white/5 border border-white/10 text-white/60">
                                                        <MapPinOff className="w-5 h-5 shrink-0 text-white/40" aria-hidden="true" />
                                                        <p className="text-sm">This request doesn't need a location.</p>
                                                    </div>
                                                ) : mapProviderReady(mapsRaw) ? (
                                                    <div id={FIELD_IDS.address} tabIndex={-1} className="outline-none">
                                                        <label className="block text-sm font-medium text-white/70 mb-2">
                                                            {"Location / Address"}
                                                            {locationMode === 'optional' && (
                                                                <span className="ml-1.5 font-normal text-white/40">(optional)</span>
                                                            )}
                                                            {locationMode === 'required' && (
                                                                <span className="ml-1 text-red-400" aria-hidden="true">*</span>
                                                            )}
                                                        </label>
                                                        <LocationPicker
                                                            config={mapConfig}
                                                            townshipBoundary={townshipBoundary}
                                                            customLayers={mapLayers.filter(layer => {
                                                                // Check if layer is visible
                                                                if ((layer as any).visible_on_map === false) return false;
                                                                // Layer applies if: no service_codes (applies to all) OR includes current category
                                                                const codes = layer.service_codes || [];
                                                                return codes.length === 0 || codes.includes(selectedService.service_code);
                                                            })}
                                                            outlineCategory={selectedService.service_code}
                                                            value={location}
                                                            onOutOfBounds={() => setIsLocationOutOfBounds(true)}
                                                            onAssetSelect={(asset) => {
                                                                setSelectedAsset(asset);
                                                            }}
                                                            onChange={(newLocation) => {
                                                                setLocation(newLocation);
                                                                setIsLocationOutOfBounds(false); // Reset when location changes
                                                                // Save both address AND coordinates
                                                                setFormData((prev) => ({
                                                                    ...prev,
                                                                    address: newLocation.address,
                                                                    lat: newLocation.lat ?? undefined,
                                                                    long: newLocation.lng ?? undefined,
                                                                }));
                                                                // Road rules are decided from the pin, not the address text.
                                                                checkRoadBasedBlocking(
                                                                    selectedService,
                                                                    newLocation.lat ?? undefined,
                                                                    newLocation.lng ?? undefined,
                                                                );
                                                            }}
                                                            placeholder="Search for an address or click on the map..."
                                                        />


                                                    </div>
                                                ) : (
                                                    <>
                                                        <Input
                                                            id={FIELD_IDS.address}
                                                            label={"Location / Address"}
                                                            /* WCAG 1.3.5 Identify Input Purpose: this is the
                                                               resident's own street address when no map is
                                                               configured, so a browser or an assistive tool that
                                                               fills addresses can fill it. */
                                                            autoComplete="street-address"
                                                            placeholder="Street address or intersection"
                                                            leftIcon={<MapPin className="w-5 h-5" />}
                                                            value={formData.address}
                                                            onChange={(e) => {
                                                                const newAddress = e.target.value;
                                                                setFormData((prev) => ({ ...prev, address: newAddress }));
                                                                // Typed address with no map: nothing to measure against, so
                                                                // no road rule can apply. Failing open is the point.
                                                                void newAddress;
                                                            }}
                                                        />
                                                        <div className="p-4 rounded-xl bg-white/5 border border-white/10 text-center text-white/40">
                                                            <MapPin className="w-8 h-8 mx-auto mb-2 opacity-50" />
                                                            <p className="text-sm">The interactive map needs a map provider to be configured</p>
                                                        </div>
                                                    </>
                                                )}
                                                {locationMode !== 'hidden' && formErrors.address && (
                                                    <p className="text-sm text-red-400 -mt-2">{formErrors.address}</p>
                                                )}

                                                {/* Which road the pin landed on. Shown whether or not anything
                                                    is blocked, so a resident can see the system read their pin
                                                    the way they meant it before they type a description. */}
                                                {detectedRoad && (
                                                    /* No role="status" here. The pin drop is announced
                                                       once, as a composed sentence, from
                                                       checkRoadBasedBlocking -- this line and the redirect
                                                       notice below it are the visible half of the same
                                                       event, and two polite regions firing together got
                                                       neither of them read. */
                                                    <div className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl bg-white/[0.04] border border-white/10">
                                                        <SignpostBig className="w-4 h-4 text-white/40 shrink-0" aria-hidden="true" />
                                                        <span className="text-sm text-white/60">
                                                            Road detected:{' '}
                                                            <span className="text-white/90 font-medium">{detectedRoad.name}</span>
                                                        </span>
                                                    </div>
                                                )}

                                                {/* This road belongs to someone else. detectedRoad is what
                                                    decided it, and naming it is the only way a resident can
                                                    spot a pin that landed one lane over and drag it back. */}
                                                {isBlocked && (
                                                    <RedirectNotice
                                                        variant="road"
                                                        jurisdiction={blockJurisdiction}
                                                        message={blockMessage}
                                                        messageIsDefault={blockMessageIsDefault}
                                                        contacts={blockContacts}
                                                        roadName={detectedRoad?.name}
                                                        serviceName={selectedService.service_name}
                                                    />
                                                )}

                                                {/* Photos are not kept in a saved draft. */}
                                                {photosToReadd > 0 && attachedPhotos.length === 0 && (
                                                    <p className="text-sm text-amber-200" data-testid="photos-readd-note">
                                                        Add your photos again.
                                                    </p>
                                                )}

                                                {/* Photo Upload */}
                                                <PhotoUpload
                                                    previewUrls={photoPreviewUrls}
                                                    statuses={photoStatuses}
                                                    onAdd={handlePhotoUpload}
                                                    onRemove={handleRemovePhoto}
                                                />
                                            </div>
                                        </Card>

                                        {/* Custom Questions - Dynamic */}
                                        {selectedService.routing_config?.custom_questions &&
                                            selectedService.routing_config.custom_questions.length > 0 && (
                                                <Card>
                                                    <h3 className="text-lg font-semibold text-white mb-4">
                                                        Additional Information
                                                    </h3>
                                                    <div className="space-y-4">
                                                        <CustomQuestionFields
                                                            questions={selectedService.routing_config.custom_questions}
                                                            answers={customAnswers}
                                                            onChange={(label, value) => setCustomAnswers(p => ({ ...p, [label]: value }))}
                                                            errors={formErrors}
                                                            fieldId={customFieldId}
                                                        />
                                                    </div>
                                                </Card>
                                            )}

                                        <Card>
                                            <h3 className="text-lg font-semibold text-white mb-4">
                                                {"Contact Information"}
                                            </h3>
                                            <div className="space-y-4">
                                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                                    <Input
                                                        label={"First Name"}
                                                        /* WCAG 1.3.5: personal-data fields carry their purpose,
                                                           so autofill can spare a resident with a motor or
                                                           cognitive disability from retyping their own details. */
                                                        autoComplete="given-name"
                                                        placeholder="John"
                                                        value={formData.first_name}
                                                        onChange={(e) =>
                                                            setFormData((prev) => ({ ...prev, first_name: e.target.value }))
                                                        }
                                                    />
                                                    <Input
                                                        label={"Last Name"}
                                                        autoComplete="family-name"
                                                        placeholder="Doe"
                                                        value={formData.last_name}
                                                        onChange={(e) =>
                                                            setFormData((prev) => ({ ...prev, last_name: e.target.value }))
                                                        }
                                                    />
                                                </div>

                                                <Input
                                                    id={FIELD_IDS.email}
                                                    label={"Email"}
                                                    type="email"
                                                    autoComplete="email"
                                                    placeholder="you@example.com"
                                                    value={formData.email}
                                                    onChange={(e) =>
                                                        setFormData((prev) => ({ ...prev, email: e.target.value }))
                                                    }
                                                    error={formErrors.email}
                                                    /* Announced by the error summary that takes
                                                       focus, not by an alert of its own -- see the
                                                       summary below. */
                                                    errorAsAlert={false}
                                                    required
                                                />

                                                <Input
                                                    id={FIELD_IDS.phone}
                                                    label={"Phone (optional)"}
                                                    type="tel"
                                                    inputMode="tel"
                                                    autoComplete="tel"
                                                    placeholder="(555) 123-4567"
                                                    value={formData.phone}
                                                    onChange={(e) => {
                                                        setFormData((prev) => ({ ...prev, phone: filterPhoneInput(e.target.value) }));
                                                        // A field that keeps showing "invalid" while it is
                                                        // being corrected reads as unfixable; the error
                                                        // comes back at submit if it is still wrong.
                                                        setFormErrors((prev) => (prev.phone ? { ...prev, phone: '' } : prev));
                                                    }}
                                                    error={formErrors.phone}
                                                    /* Announced by the error summary that takes
                                                       focus, not by an alert of its own -- see the
                                                       summary below. */
                                                    errorAsAlert={false}
                                                />
                                            </div>
                                        </Card>

                                        {/* A category the town keeps off the public map. Said before
                                            submitting, so the resident knows who will see the report. */}
                                        {selectedService.hidden_from_public && (
                                            <Card>
                                                <div className="flex items-start gap-3">
                                                    <div className="w-9 h-9 rounded-xl bg-slate-500/20 border border-slate-400/25 flex items-center justify-center shrink-0">
                                                        <EyeOff className="w-4 h-4 text-slate-200" aria-hidden="true" />
                                                    </div>
                                                    <div className="min-w-0">
                                                        <p className="text-sm font-medium text-white">This report won't be shown publicly</p>
                                                        <p className="text-xs text-white/55 mt-1 leading-relaxed">
                                                            Reports in this category don't appear on the public map or list. Town staff
                                                            see your report and handle it as usual, and you can follow it with your
                                                            tracking link. Anyone you share that link with can also view it. Like other
                                                            municipal records, it can be released in response to a public records request.
                                                        </p>
                                                    </div>
                                                </div>
                                            </Card>
                                        )}

                                        {/* Public-feed visibility. Only offered when the town has
                                            turned the Unlisted Reports module on. Sharing is the
                                            default; hiding is a deliberate, unchecked-by-default box.
                                            Not offered for a category that is already hidden. */}
                                        {!selectedService.hidden_from_public && (settings?.modules?.unlisted_reports ?? (settings?.modules as any)?.private_reports) && (
                                            <Card>
                                                <label className="flex items-start gap-3 cursor-pointer">
                                                    <input
                                                        type="checkbox"
                                                        checked={formData.is_public === false}
                                                        onChange={(e) =>
                                                            setFormData((prev) => ({ ...prev, is_public: !e.target.checked }))
                                                        }
                                                        className="mt-0.5 w-5 h-5 rounded border-white/20 bg-white/10 text-primary-500 shrink-0"
                                                    />
                                                    <span className="min-w-0">
                                                        <span className="block text-sm font-medium text-white">
                                                            Hide this report from the public map and feed
                                                        </span>
                                                        <span className="block text-xs text-white/50 mt-1 leading-relaxed">
                                                            {formData.is_public === false ? (
                                                                <>Your report won&apos;t appear on the public map, feed, or open
                                                                    data feeds. <strong className="text-white/70">Anyone you send
                                                                        your tracking link to can still view it.</strong> Town staff
                                                                    always see it and will work it normally, and it still counts in
                                                                    anonymized statistics.</>
                                                            ) : (
                                                                <>Leave this unchecked to share your report with neighbors on the
                                                                    public map and feed. Your name and contact details are never
                                                                    shown either way.</>
                                                            )}
                                                        </span>
                                                    </span>
                                                </label>
                                            </Card>
                                        )}

                                        {/* What went wrong, in one place, with focus on it.
                                            Kept above the submit button so the reading order
                                            matches: here is the problem, here is the control
                                            it stopped. tabIndex allows focus without putting
                                            it in the Tab sequence afterwards (WCAG 3.3.1).

                                            Deliberately not role="alert". Moving focus here is
                                            what announces it -- a screen reader reads the
                                            heading and the whole list on arrival. As an alert
                                            it was one of five: each failed field rendered its
                                            own alert in the same commit, and several alert
                                            regions appearing at once means a screen reader
                                            reliably announces none of them, so a four-error
                                            submit went silent (WCAG 4.1.3). The field
                                            messages are now plain text tied to their control
                                            by aria-describedby. */}
                                        {errorSummary.length > 0 && (
                                            <div
                                                ref={errorSummaryRef}
                                                tabIndex={-1}
                                                aria-labelledby="error-summary-heading"
                                                className="p-4 rounded-xl bg-red-500/20 border border-red-500/30 text-red-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
                                            >
                                                <h3 id="error-summary-heading" className="font-semibold text-red-100">
                                                    {errorSummary.length === 1
                                                        ? 'There is a problem with your report'
                                                        : `There are ${errorSummary.length} problems with your report`}
                                                </h3>
                                                <ul className="mt-2 space-y-1 list-disc list-inside">
                                                    {errorSummary.map(({ fieldId, message }) => (
                                                        <li key={message}>
                                                            {fieldId ? (
                                                                <a
                                                                    href={`#${fieldId}`}
                                                                    className="underline"
                                                                    onClick={(e) => {
                                                                        /* Focus the field, rather than
                                                                           letting the fragment do it.
                                                                           A `#id` jump sets only the
                                                                           sequential focus STARTING
                                                                           POINT: focus stays on the
                                                                           document, and the next Tab
                                                                           lands on whatever follows
                                                                           the field -- so an error
                                                                           about Email put the keyboard
                                                                           on Phone, past the box it
                                                                           was complaining about.
                                                                           Recovering meant shift-
                                                                           tabbing back. */
                                                                        const el = document.getElementById(fieldId);
                                                                        if (!el) return;
                                                                        e.preventDefault();
                                                                        el.focus();
                                                                        el.scrollIntoView({ block: 'center' });
                                                                    }}
                                                                >{message}</a>
                                                            ) : message}
                                                        </li>
                                                    ))}
                                                </ul>
                                            </div>
                                        )}

                                        {/* role="alert" because this appears after the resident
                                            pressed Submit and nothing else on screen moves --
                                            without it, a failed submission was completely silent
                                            (WCAG 4.1.3). */}
                                        {formErrors.submit && (
                                            <div role="alert" className="p-4 rounded-xl bg-red-500/20 border border-red-500/30 text-red-300">
                                                {formErrors.submit}
                                            </div>
                                        )}

                                        {/* The reason the button cannot be used, rendered whether
                                            or not it applies -- previously the button was removed
                                            from the DOM entirely, so a resident who had just
                                            dragged the pin out of town tabbed into a form with no
                                            submit control and no announcement of why. The button
                                            stays, disabled, and points at the reason. */}
                                        {(isBlocked || isLocationOutOfBounds) && (
                                            <div
                                                id="submit-blocked-reason"
                                                role="alert"
                                                className={`p-4 rounded-xl text-center border ${isLocationOutOfBounds
                                                    ? 'bg-red-500/20 border-red-500/30 text-red-300'
                                                    : 'bg-amber-500/20 border-amber-500/30 text-amber-300'}`}
                                            >
                                                {isLocationOutOfBounds ? (
                                                    <><strong>Outside the boundary:</strong> Choose a location within the municipality.</>
                                                ) : (
                                                    <>Can&apos;t submit yet. See the notice above.</>
                                                )}
                                            </div>
                                        )}

                                        {/* Two separate reasons this can be unusable, and they
                                            are announced differently on purpose. Blocked or
                                            out-of-bounds is a state the resident has to fix, so it
                                            points at the reason block above. A photo still being
                                            screened is a wait that clears on its own, so it is said
                                            in the label rather than described elsewhere -- and the
                                            screening starts at photo-pick time, so by the time
                                            anyone has finished typing a description it is almost
                                            always already over. */}
                                        <Button
                                            type="submit"
                                            size="lg"
                                            className="w-full"
                                            isLoading={isSubmitting || photosStillChecking}
                                            disabled={isBlocked || isLocationOutOfBounds || photosStillChecking}
                                            aria-describedby={(isBlocked || isLocationOutOfBounds) ? 'submit-blocked-reason' : undefined}
                                            rightIcon={<Send className="w-5 h-5" />}
                                        >
                                            {photosStillChecking ? "Checking your photos…" : "Submit Request"}
                                        </Button>

                                        {/* WCAG 3.3.4: the Terms say that submitting is the act of
                                            agreeing to them, so they have to be reachable at the
                                            moment of submitting rather than only from the footer. */}
                                        <p className="text-sm text-white/60 text-center">
                                            By submitting this request you agree to the{' '}
                                            <Link to="/terms" className="underline text-white/80 hover:text-white">
                                                Terms of Service
                                            </Link>.
                                        </p>

                                    </form>
                                )}
                            </motion.div>
                        )}

                        {step === 'success' && (
                            <motion.div
                                key="success"
                                initial={{ opacity: 0, scale: 0.9 }}
                                animate={{ opacity: 1, scale: 1 }}
                                className="max-w-lg mx-auto text-center space-y-8 py-12"
                            >
                                <motion.div
                                    initial={{ scale: 0 }}
                                    animate={{ scale: 1 }}
                                    transition={{ type: 'spring', delay: 0.2 }}
                                    className="w-24 h-24 mx-auto rounded-full bg-green-500/20 border border-green-500/30 flex items-center justify-center glow-effect"
                                    style={{ boxShadow: '0 0 60px rgba(34, 197, 94, 0.4)' }}
                                >
                                    <CheckCircle2 className="w-12 h-12 text-green-400" />
                                </motion.div>

                                <div className="space-y-4">
                                    <h1
                                        ref={stepHeadingRef.success}
                                        tabIndex={-1}
                                        className="text-3xl font-bold text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 rounded-lg"
                                    >
                                        Request submitted
                                    </h1>
                                    <p className="text-white/60">
                                        Thank you. We've received your request and staff will review it.
                                    </p>
                                    {submittedId && (
                                        <div className="inline-block px-4 py-2 rounded-lg bg-white/10 border border-white/20">
                                            <span className="text-white/50 text-sm">Request ID: </span>
                                            <span className="font-mono text-white font-medium">{submittedId}</span>
                                        </div>
                                    )}
                                    {/* The one moment the resident can be told, and the
                                        only one they will notice: their report is filed
                                        and the photo they attached is not on it. Said
                                        plainly, because "where did my photo go" is
                                        otherwise unanswerable from the tracker. */}
                                    {submittedPhotosHeld > 0 && (
                                        <div
                                            role="status"
                                            className="text-left mx-auto max-w-md px-4 py-3 rounded-lg bg-amber-500/10 border border-amber-500/30"
                                        >
                                            <p className="text-sm text-amber-200 font-medium">
                                                {submittedPhotosHeld === 1
                                                    ? 'Your photo is waiting to be checked'
                                                    : `${submittedPhotosHeld} of your photos are waiting to be checked`}
                                            </p>
                                            <p className="text-xs text-amber-200/70 mt-1">
                                                We couldn&apos;t blur faces and license plates automatically, so
                                                {submittedPhotosHeld === 1 ? ' it isn\'t ' : ' they aren\'t '}
                                                on the public tracker yet. Your report is filed. Staff will review
                                                {submittedPhotosHeld === 1 ? ' it' : ' them'} and publish or delete
                                                {submittedPhotosHeld === 1 ? ' it' : ' them'}.
                                            </p>
                                        </div>
                                    )}
                                </div>

                                <div className="space-y-3">
                                    {/* Tracking is the thing a resident actually
                                        wants next, and until now the only way to
                                        reach it was to notice a link elsewhere on
                                        the page and retype the reference. The id
                                        is already in hand here, so the button goes
                                        straight to that one request. */}
                                    {submittedId && (
                                        <button
                                            type="button"
                                            onClick={() => {
                                                /* The hash alone does not move
                                                   the page: the tracking view is
                                                   its own piece of state, and
                                                   every other route into it sets
                                                   both. Changing only the hash
                                                   left the resident on the
                                                   confirmation screen with a
                                                   button that appeared dead. */
                                                updateHash(`track/${submittedId}`);
                                                setShowTrackingView(true);
                                                scrollToTop('instant');
                                            }}
                                            className="w-full inline-flex items-center justify-center gap-2.5 rounded-2xl px-6 py-4 font-semibold text-white
                                                       bg-gradient-to-r from-primary-500 to-primary-600 hover:from-primary-400 hover:to-primary-500
                                                       border border-white/15 shadow-[0_10px_35px_rgba(59,130,246,0.35)]
                                                       transition-all hover:shadow-[0_14px_45px_rgba(59,130,246,0.45)] hover:-translate-y-0.5
                                                       focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70"
                                        >
                                            <Search className="w-5 h-5" aria-hidden="true" />
                                            Track this request
                                        </button>
                                    )}
                                    <Button onClick={handleReset} size="lg" variant="secondary" className="w-full">
                                        Submit Another Request
                                    </Button>
                                </div>

                                {/* Moved here from the footer. It used to sit in
                                    the smallest type on the page, deliberately, so
                                    that it could not compete with somebody still
                                    filing a report. On this screen the report is
                                    filed and there is nothing left to interrupt,
                                    so the question is asked properly instead of
                                    hidden. */}
                                <PlatformFeedback
                                    enabled={settings?.modules?.platform_feedback}
                                    feedbackEmail={settings?.platform_feedback_email}
                                    variant="card"
                                />
                            </motion.div>
                        )}
                    </AnimatePresence>
                )}
            </main>

            {/* Footer */}
            <footer className="glass-sidebar py-6 px-4 mt-auto">
                <div className="max-w-6xl mx-auto flex flex-col items-center gap-4">
                    {/* Copyright */}
                    <p className="text-white/40 text-sm text-center">
                        © {new Date().getFullYear()} {settings?.township_name || 'Municipality 311'}. {"All rights reserved"}
                    </p>

                    {/* Social Links */}
                    {settings?.social_links && settings.social_links.length > 0 && (
                        <div className="flex items-center justify-center flex-wrap gap-2">
                            {settings.social_links.map((link, index) => {
                                // Ensure URL is absolute
                                const url = link.url.startsWith('http') ? link.url : `https://${link.url}`;
                                const platform = link.platform.charAt(0).toUpperCase() + link.platform.slice(1);
                                return (
                                    <a
                                        key={index}
                                        href={url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="w-9 h-9 rounded-lg bg-white/10 hover:bg-white/20 flex items-center justify-center transition-all hover:scale-110"
                                        title={platform}
                                        /* The only content is a lucide <svg>, which ships no
                                           aria-hidden and no title of its own, so the link had
                                           no accessible name at all -- a screen reader read six
                                           links called "link" (WCAG 1.1.1, 2.4.4). title= is a
                                           tooltip, not a name, on a link with content. The new
                                           tab is named because it is an unannounced context
                                           change (WCAG 3.2.5 advisory). */
                                        aria-label={`${platform} (opens in a new tab)`}
                                    >
                                        <span aria-hidden="true">
                                            {link.icon === 'Globe' && <Globe className="w-4 h-4 text-white/70" />}
                                            {link.icon === 'Facebook' && <Facebook className="w-4 h-4 text-blue-400" />}
                                            {link.icon === 'Instagram' && <Instagram className="w-4 h-4 text-pink-400" />}
                                            {link.icon === 'Youtube' && <Youtube className="w-4 h-4 text-red-400" />}
                                            {link.icon === 'Twitter' && <Twitter className="w-4 h-4 text-sky-400" />}
                                            {link.icon === 'Linkedin' && <Linkedin className="w-4 h-4 text-blue-500" />}
                                        </span>
                                    </a>
                                );
                            })}
                        </div>
                    )}

                    {/* Legal Links */}
                    <div className="flex items-center justify-center flex-wrap gap-x-4 gap-y-2 text-sm">
                        <Link to="/privacy" className="text-white/40 hover:text-white/80 transition-colors">
                            {"Privacy"}
                        </Link>
                        <span className="text-white/20 hidden sm:inline">•</span>
                        <Link to="/accessibility" className="text-white/40 hover:text-white/80 transition-colors">
                            {"Accessibility"}
                        </Link>
                        <span className="text-white/20 hidden sm:inline">•</span>
                        <Link to="/terms" className="text-white/40 hover:text-white/80 transition-colors">
                            {"Terms"}
                        </Link>
                        <span className="text-white/20 hidden sm:inline">•</span>
                        {/* Moved here from the product credit below. The bundled
                            open-source dependencies require their notices be
                            available, so the link stays -- but it is a legal
                            link, and a resident reading a byline does not need
                            other people's licences in it. */}
                        <a href="/third-party-licenses.txt" className="text-white/40 hover:text-white/80 transition-colors">
                            {"Notices"}
                        </a>
                    </div>
                </div>
                {/* Powered by Pinpoint 311 */}
                <div className="max-w-6xl mx-auto mt-5 pt-5 border-t border-white/10 flex flex-col items-center gap-2.5">
                    <a
                        href="https://pinpoint311.org"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="brand-link group inline-flex items-center gap-2.5"
                        data-no-translate
                    >
                        {/* A kicker, not a sentence.
                            "Powered by" at body size put a ~10px cap height next
                            to a ~24px wordmark, which reads as two mismatched
                            things rather than one lockup. Setting it as a small
                            tracked label makes the size difference deliberate,
                            and matches how the staff sidebar already pairs these
                            two. The logo carries ~8% transparent padding top and
                            bottom, symmetric, so centring aligns correctly. */}
                        <span className="text-[11px] uppercase tracking-[0.18em] font-medium text-white/40 group-hover:text-white/60 transition-colors">
                            {"Powered by"}
                        </span>
                        <img
                            src="/pinpoint311_logo_dark_transparent.png"
                            alt="Pinpoint 311"
                            width={952}
                            height={139}
                            className="h-7 sm:h-8 w-auto opacity-85 group-hover:opacity-100 transition-opacity"
                        />
                    </a>
                    {/* The credit line proper.

                        It used to read "Free & Open Source Municipal Platform",
                        which names a category rather than the project, and made
                        an open-source claim with nothing to check it against --
                        the weakest form of that claim, and the one a town
                        evaluating this platform is most likely to want to
                        verify. So the licence is named and the source is linked.

                        The nonprofit line is here because for a municipal
                        audience "who is behind this and what happens if they
                        lose interest" is a real question, and a 501(c)(3) fiscal
                        sponsor is a better answer than a website. Worded exactly
                        as the README does -- fiscally sponsored by, not "a
                        project of", because those mean different things. */}
                    <p className="text-white/30 text-xs text-center" data-no-translate>
                        {"Free, open-source software for local government"}
                    </p>
                </div>
            </footer>
        </div>
    );
}
