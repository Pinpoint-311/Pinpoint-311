import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { resolveMapProviderConfig, mapProviderReady, RawMapsConfig } from '../maps';
import { motion, AnimatePresence } from 'framer-motion';
import { Link, useParams } from 'react-router-dom';
import {
    ArrowLeft,
    MapPin,
    CheckCircle2,
    Send,
    AlertCircle,
    Circle,
    Lightbulb,
    Trash2,
    Footprints,
    SignpostBig,
    Volume2,
    HelpCircle,
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
} from 'lucide-react';
import { Button, Input, Textarea, Card } from '../components/ui';
import LocationPicker from '../components/LocationPicker';
import PhotoUpload, { PhotoState, PhotoStatus } from '../components/PhotoUpload';
import { filterPhoneInput, isValidPhone } from '../utils/phone';
import RedirectNotice, { RedirectContact } from '../components/RedirectNotice';
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

// Icon mapping for service categories
const iconMap: Record<string, React.FC<{ className?: string }>> = {
    Circle,
    Lightbulb,
    Trash2,
    Footprints,
    SignpostBig,
    Volume2,
    HelpCircle,
    AlertCircle,
    Spray: AlertCircle, // Fallback
};

type Step = 'categories' | 'form' | 'success';




export default function ResidentPortal() {
    const { settings } = useSettings();
    const { language } = useTranslation();
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
    const [showTrackingView, setShowTrackingView] = useState(urlRequestId || initialHash === 'track');
    const [step, setStep] = useState<Step>('categories');
    const [services, setServices] = useState<ServiceDefinition[]>([]);
    const [selectedService, setSelectedService] = useState<ServiceDefinition | null>(null);
    const [searchQuery, setSearchQuery] = useState('');
    const [isLoading, setIsLoading] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [submittedId, setSubmittedId] = useState<string | null>(null);
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
            announce('Please confirm the non-emergency notice to continue.', 'assertive');
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
            setShowTrackingView(false);
            setStep('categories');
            setSelectedService(null);
        } else if (hash.startsWith('report/')) {
            setShowTrackingView(false);
            setStep('form');
            // Service will be selected based on the hash - handled in useEffect after services load
        } else if (hash === 'success') {
            setShowTrackingView(false);
            setStep('success');
        }
    }, []);

    // URL hashing, dynamic titles, and scroll-to-top
    const { updateHash, updateTitle, scrollToTop, currentHash } = usePageNavigation({
        baseTitle: settings?.township_name || 'Resident Portal',
        scrollContainerRef: contentRef,
        onHashChange: handleHashChange,
    });

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
                // Also set formData.service_code - critical for submission!
                setFormData((prev) => ({ ...prev, service_code: service.service_code }));
                setStep('form');
            }
        }
    }, [services, currentHash, selectedService]);

    // Requests for staff map
    const [allRequests, setAllRequests] = useState<ServiceRequest[]>([]);

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

    /**
     * Photos, and where each one has got to in screening.
     *
     * Screening -- moderation plus the face and plate blur -- used to happen
     * inside the create-request POST, which put a Google Vision round trip on
     * the Submit button: attach a 6MB photo and the form sat under a generic
     * spinner long enough that residents pressed Submit twice. It happens here
     * instead, the moment the photo is picked, while they are still writing the
     * description. By the time they submit, the answer is already in.
     *
     * Each entry keeps three things that look redundant and are not:
     *   previewUrl  what the resident sees. Swapped for the REDACTED image once
     *               screening finishes, so the thumbnail is what the town will
     *               actually publish rather than the original they chose.
     *   original    the bytes as picked, in memory only, kept solely so a handle
     *               that expires mid-form can fall back to the inline path.
     *   handle      what goes into media_urls in place of megabytes of base64.
     */
    type AttachedPhoto = {
        id: string;
        previewUrl: string;
        original: string;
        state: PhotoState;
        message?: string;
        handle?: string;
    };
    const [attachedPhotos, setAttachedPhotos] = useState<AttachedPhoto[]>([]);
    const photoPreviewUrls = attachedPhotos.map((p) => p.previewUrl);
    const photoStatuses: PhotoStatus[] = attachedPhotos.map(
        ({ state, message }) => ({ state, message }),
    );
    const blockedPhotos = attachedPhotos.filter((p) => p.state === 'blocked');
    const photosStillChecking = attachedPhotos.some(
        (p) => p.state === 'uploading' || p.state === 'checking',
    );

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

    const handleSelectService = (service: ServiceDefinition) => {
        setSelectedService(service);
        setFormData((prev) => ({ ...prev, service_code: service.service_code }));

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
            errors.description = 'Please provide a detailed description (at least 10 characters)';
        }
        if (!formData.email || !/\S+@\S+\.\S+/.test(formData.email)) {
            errors.email = 'Please enter a valid email address';
        }
        if (formData.phone && !isValidPhone(formData.phone)) {
            errors.phone = 'Please enter a valid phone number, e.g. (555) 123-4567';
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
                submit: "One of your photos can't be used. Please remove it and try again.",
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

            const result = await api.createRequest({
                ...formData,
                preferred_language: language,  // Capture user's selected language for notifications
                media_urls: usable.map((p) => p.handle || p.original),
                matched_asset: matchedAsset,
                custom_fields: customAnswers,
            }, inlineFallback);
            setSubmittedId(result.service_request_id);
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
            setFormErrors({ submit: 'Failed to submit request. Please try again.' });
        } finally {
            setIsSubmitting(false);
        }
    };
    const handleReset = () => {
        pendingStepFocus.current = 'categories';
        setStep('categories');
        setSelectedService(null);
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
        setAttachedPhotos([]);
        setLocation({ address: '', lat: null, lng: null });
        // Clear blocking state
        setIsBlocked(false);
        setBlockMessage('');
        setBlockContacts([]);
        // Clear custom answers
        setCustomAnswers({});
        // Strip hash from URL
        window.history.replaceState(null, '', window.location.pathname);
    };

    /* Screening verdicts that arrived before their photo row existed, keyed by
     * photo id. Screening and the FileReader preview run in parallel and either
     * can finish first; this is where the fast one waits. */
    const pendingPhotoPatches = useRef<Record<string, Partial<AttachedPhoto>>>({});

    /** Update one photo by identity rather than position.
     *
     * Positions move: a resident can remove the first photo while the third is
     * still being screened, and an index captured when the upload started would
     * by then name someone else's photo. Every screening result is applied by
     * id, and a result for a photo that has since been removed lands nowhere,
     * which is what should happen. */
    const updatePhoto = (id: string, patch: Partial<AttachedPhoto>) => {
        setAttachedPhotos((prev) => {
            if (!prev.some((p) => p.id === id)) {
                // The result beat the preview. Screening starts in parallel with
                // the FileReader and is often faster, so the row this patch names
                // may not exist yet -- and mapping over a list that does not
                // contain it drops the verdict on the floor, after which the
                // insert below writes `uploading` and the photo sits there
                // forever. Hold the patch and let the insert apply it.
                pendingPhotoPatches.current[id] = {
                    ...(pendingPhotoPatches.current[id] || {}),
                    ...patch,
                };
                return prev;
            }
            return prev.map((p) => (p.id === id ? { ...p, ...patch } : p));
        });
    };

    const handlePhotoUpload = (files: FileList) => {
        const remaining = 3 - attachedPhotos.length;
        const chosen = Array.from(files).slice(0, Math.max(0, remaining)); // Max 3 photos

        chosen.forEach((file) => {
            const id = `${Date.now()}-${Math.random().toString(36).slice(2)}`;

            // The preview still arrives one FileReader at a time, so the photo
            // count climbs one render at a time -- PhotoUpload's focus handling
            // is built on that and must not be collapsed into a single update.
            const reader = new FileReader();
            reader.onloadend = () => {
                const dataUrl = reader.result as string;
                setAttachedPhotos((prev) => {
                    if (prev.length >= 3) return prev;
                    // Anything screening decided while this preview was loading.
                    const early = pendingPhotoPatches.current[id];
                    delete pendingPhotoPatches.current[id];
                    return [...prev, {
                        id,
                        previewUrl: dataUrl,
                        original: dataUrl,
                        state: 'uploading',
                        ...(early || {}),
                    }];
                });
            };
            reader.readAsDataURL(file);

            // Screening starts immediately and in parallel with the preview:
            // the network round trip is the slow half, and there is no reason
            // for it to wait on a local FileReader.
            api.screenPhoto(file, () => updatePhoto(id, { state: 'checking' }))
                .then((result) => {
                    if (result.status === 'blocked') {
                        updatePhoto(id, {
                            state: 'blocked',
                            message: result.message
                                || "This photo can't be used. Please choose a different one.",
                            handle: undefined,
                        });
                        return;
                    }
                    if (result.status === 'needs_review') {
                        // The handle holds no bytes -- nothing was screened --
                        // so this photo is submitted inline and the server
                        // parks it for staff. Say so plainly: it is attached,
                        // it is just not going public unlooked-at.
                        updatePhoto(id, { state: 'review', message: result.message });
                        return;
                    }
                    updatePhoto(id, {
                        state: 'ready',
                        handle: result.handle,
                        // Show them the blurred version, not the original.
                        ...(result.preview ? { previewUrl: result.preview } : {}),
                        message: result.faces || result.plates
                            ? 'Ready to send — faces and licence plates blurred'
                            : undefined,
                    });
                })
                .catch(() => {
                    // The screen call itself failed (offline, rate limited).
                    // The photo is still attachable; it goes inline with the
                    // report and the server decides what to do with it.
                    updatePhoto(id, { state: 'error' });
                });
        });
    };

    const handleRemovePhoto = (index: number) => {
        setAttachedPhotos((prev) => prev.filter((_, i) => i !== index));
    };

    const getIcon = (iconName: string) => {
        const IconComponent = iconMap[iconName] || AlertCircle;
        return <IconComponent className="w-8 h-8" />;
    };

    return (
        <div className="min-h-screen flex flex-col">
            {/* Header Container - Reorders on mobile (banner first, then nav) */}
            <div className="flex flex-col-reverse md:flex-col sticky top-0 z-40">
                {/* Navigation - Clean Mobile Header */}
                <nav className="glass-sidebar py-3 md:py-4 px-4 md:px-6 flex items-center justify-between relative z-10" aria-label="Main navigation">
                    <button
                        onClick={() => {
                            setShowTrackingView(false);
                            updateHash('');
                            window.scrollTo(0, 0);
                            setStep('categories');
                            setSelectedService(null);
                        }}
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
                                    Welcome to {settings?.township_name || "311 Services"}!
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
                                        <span>For emergencies (police, fire, medical), please dial <strong className="text-white whitespace-nowrap">911</strong></span>
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
                                    Got it! I'll use this for non-emergency requests and call 911 for emergencies.
                                </span>
                            </label>

                            {/* Welcoming Continue Button */}
                            <Button
                                onClick={handleDisclaimerAcknowledge}
                                disabled={!disclaimerChecked}
                                className={`w-full py-3 text-base font-medium ${!disclaimerChecked ? 'opacity-50 cursor-not-allowed' : 'bg-gradient-to-r from-primary-500 to-purple-600 hover:from-primary-600 hover:to-purple-700'}`}
                            >
                                {disclaimerChecked ? "Let's Get Started! →" : "Check the box above to continue"}
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
                            onClick={() => {
                                setShowTrackingView(false);
                                updateHash('');
                            }}
                            className="flex items-center gap-2 text-white/60 hover:text-white transition-colors"
                            aria-label="Go back to home page"
                        >
                            <ArrowLeft className="w-5 h-5" />
                            <span>Back to Home</span>
                        </button>
                        <TrackRequests
                            initialRequestId={urlRequestId}
                            selectedRequestId={
                                currentHash === 'track' ? null :
                                    currentHash.startsWith('track/') ? currentHash.split('/')[1] :
                                        urlRequestId || null
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
                                {/* Hero Section */}
                                <div className="text-center space-y-6">
                                    <motion.div
                                        initial={{ scale: 0.9, opacity: 0 }}
                                        animate={{ scale: 1, opacity: 1 }}
                                        transition={{ delay: 0.1 }}
                                        className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary-500/20 border border-primary-500/30"
                                    >
                                        <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
                                        <span className="text-sm font-medium text-primary-200">
                                            Report Requests Online
                                        </span>
                                    </motion.div>

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
                                            <div
                                                className="absolute top-1/2 -translate-y-1/2 w-5 h-5 pointer-events-none"
                                                style={{
                                                    left: '1rem',
                                                    backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='rgba(255,255,255,0.7)' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'%3E%3C/circle%3E%3Cline x1='21' y1='21' x2='16.65' y2='16.65'%3E%3C/line%3E%3C/svg%3E")`,
                                                    backgroundSize: 'contain',
                                                    backgroundRepeat: 'no-repeat'
                                                }}
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
                                    className="space-y-4"
                                >
                                    <h2 className="text-2xl font-bold text-white text-center">
                                        {"Community Requests Map"}
                                    </h2>
                                    <p className="text-white/60 text-center mb-6">
                                        {"View all reported issues and service requests in our community"}
                                    </p>
                                    <div className="h-[500px] rounded-2xl overflow-hidden">
                                        <StaffDashboardMap
                                            config={mapConfig}
                                            requests={allRequests}
                                            mapLayers={mapLayers}
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
                                    onClick={() => {
                                        setStep('categories');
                                        setSelectedService(null);
                                        updateHash('');
                                    }}
                                    className="flex items-center gap-2 text-white/60 hover:text-white transition-colors"
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
                                                    placeholder="Please describe the issue in detail..."
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

                                                {/* Google Maps Location Picker */}
                                                {mapProviderReady(mapsRaw) ? (
                                                    <div>
                                                        <label className="block text-sm font-medium text-white/70 mb-2">
                                                            {"Location / Address"}
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
                                                        {/* Each question is rendered from a clerk-authored
                                                            definition, so nothing here can rely on hand-written
                                                            markup being right. Every control gets an id that its
                                                            <label> (or <legend>) points at, and the error message
                                                            gets an id the control points back at -- the same
                                                            association ui/Input.tsx already makes. Before this,
                                                            the label was floating text, so each field was
                                                            announced as "edit, blank" with the placeholder read
                                                            as if it were the question (WCAG 1.3.1, 3.3.1,
                                                            3.3.2, 4.1.2). */}
                                                        {selectedService.routing_config.custom_questions.map((q) => {
                                                            const fieldId = customFieldId(q.id);
                                                            const errorId = `${fieldId}-error`;
                                                            const error = formErrors[`custom_${q.id}`];
                                                            const describedBy = error ? errorId : undefined;
                                                            const labelText = (
                                                                <>
                                                                    {q.label}
                                                                    {q.required && <span className="text-red-400" aria-hidden="true"> *</span>}
                                                                    {q.required && <span className="sr-only"> (required)</span>}
                                                                </>
                                                            );
                                                            /* Plain text, not role="alert": the control
                                                               above points at it with aria-describedby, so
                                                               it is read on focus, and the error summary
                                                               that takes focus on a failed submit already
                                                               speaks every message once. As an alert each
                                                               question added another region firing in the
                                                               same commit as the summary, and a pile of
                                                               simultaneous alerts announces as nothing. */
                                                            const errorNode = error ? (
                                                                <p id={errorId} className="text-red-400 text-sm">
                                                                    {error}
                                                                </p>
                                                            ) : null;

                                                            /* Radios, checkboxes and yes/no are groups of controls
                                                               answering one question, which is what fieldset and
                                                               legend are for. As bare divs the question text was
                                                               not attached to the options at all, so a screen
                                                               reader read "Yes" and "No" with nothing saying what
                                                               was being asked. Native grouping, not role= --
                                                               fieldset/legend needs no ARIA to say the same thing. */
                                                            if (q.type === 'radio' || q.type === 'checkbox' || q.type === 'yes_no') {
                                                                const multi = q.type === 'checkbox';
                                                                const options = q.type === 'yes_no' ? ['Yes', 'No'] : (q.options ?? []);
                                                                const selected = customAnswers[q.label];
                                                                return (
                                                                    <fieldset
                                                                        key={q.id}
                                                                        id={fieldId}
                                                                        tabIndex={-1}
                                                                        aria-describedby={describedBy}
                                                                        className="space-y-2 m-0 p-0 border-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-white/70 rounded-lg"
                                                                    >
                                                                        <legend className="block text-sm font-medium text-white/70 mb-2">
                                                                            {labelText}
                                                                        </legend>
                                                                        <div className={q.type === 'yes_no' ? 'flex gap-3' : 'space-y-2'}>
                                                                            {options.map(opt => {
                                                                                /* Selection used to be a background colour on a
                                                                                   <button> and nothing else: invisible to a screen
                                                                                   reader, and gone entirely in forced-colours mode
                                                                                   (WCAG 1.4.1, 4.1.2). A real radio carries its own
                                                                                   state, its own focus ring and its own arrow-key
                                                                                   behaviour, so no aria-pressed is needed. */
                                                                                const checked = multi
                                                                                    ? ((selected as string[] | undefined) ?? []).includes(opt)
                                                                                    : selected === opt;
                                                                                return (
                                                                                    <label
                                                                                        key={opt}
                                                                                        className={`flex items-center gap-3 text-white/80 cursor-pointer ${q.type === 'yes_no'
                                                                                            ? `flex-1 justify-center py-2 rounded-lg border transition-colors ${checked
                                                                                                ? 'bg-primary-500/30 border-primary-500 text-white'
                                                                                                : 'bg-white/5 border-white/20 hover:border-white/40'}`
                                                                                            : ''}`}
                                                                                    >
                                                                                        <input
                                                                                            type={multi ? 'checkbox' : 'radio'}
                                                                                            name={multi ? undefined : `custom_${q.id}`}
                                                                                            value={opt}
                                                                                            checked={checked}
                                                                                            onChange={(e) => {
                                                                                                if (!multi) {
                                                                                                    setCustomAnswers(p => ({ ...p, [q.label]: opt }));
                                                                                                    return;
                                                                                                }
                                                                                                const current = (customAnswers[q.label] as string[]) || [];
                                                                                                const updated = e.target.checked
                                                                                                    ? [...current, opt]
                                                                                                    : current.filter(v => v !== opt);
                                                                                                setCustomAnswers(p => ({ ...p, [q.label]: updated }));
                                                                                            }}
                                                                                            className={`w-4 h-4 accent-primary-500 ${multi ? 'rounded' : ''}`}
                                                                                        />
                                                                                        <span>{opt}</span>
                                                                                    </label>
                                                                                );
                                                                            })}
                                                                        </div>
                                                                        {errorNode}
                                                                    </fieldset>
                                                                );
                                                            }

                                                            return (
                                                                <div key={q.id} className="space-y-2">
                                                                    <label htmlFor={fieldId} className="block text-sm font-medium text-white/70">
                                                                        {labelText}
                                                                    </label>

                                                                    {/* Text Input */}
                                                                    {q.type === 'text' && (
                                                                        <input
                                                                            id={fieldId}
                                                                            type="text"
                                                                            placeholder={q.placeholder || ''}
                                                                            value={(customAnswers[q.label] as string) || ''}
                                                                            onChange={(e) => setCustomAnswers(p => ({ ...p, [q.label]: e.target.value }))}
                                                                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                                                                            required={q.required}
                                                                            aria-required={q.required || undefined}
                                                                            aria-invalid={error ? 'true' : undefined}
                                                                            aria-describedby={describedBy}
                                                                        />
                                                                    )}

                                                                    {/* Textarea */}
                                                                    {q.type === 'textarea' && (
                                                                        <textarea
                                                                            id={fieldId}
                                                                            rows={3}
                                                                            placeholder={q.placeholder || ''}
                                                                            value={(customAnswers[q.label] as string) || ''}
                                                                            onChange={(e) => setCustomAnswers(p => ({ ...p, [q.label]: e.target.value }))}
                                                                            className="w-full rounded-lg bg-white/10 border border-white/20 text-white px-3 py-2"
                                                                            required={q.required}
                                                                            aria-required={q.required || undefined}
                                                                            aria-invalid={error ? 'true' : undefined}
                                                                            aria-describedby={describedBy}
                                                                        />
                                                                    )}

                                                                    {/* Number */}
                                                                    {q.type === 'number' && (
                                                                        <input
                                                                            id={fieldId}
                                                                            type="number"
                                                                            placeholder={q.placeholder || ''}
                                                                            value={(customAnswers[q.label] as string) || ''}
                                                                            onChange={(e) => setCustomAnswers(p => ({ ...p, [q.label]: e.target.value }))}
                                                                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                                                                            required={q.required}
                                                                            aria-required={q.required || undefined}
                                                                            aria-invalid={error ? 'true' : undefined}
                                                                            aria-describedby={describedBy}
                                                                        />
                                                                    )}

                                                                    {/* Date */}
                                                                    {q.type === 'date' && (
                                                                        <input
                                                                            id={fieldId}
                                                                            type="date"
                                                                            value={(customAnswers[q.label] as string) || ''}
                                                                            onChange={(e) => setCustomAnswers(p => ({ ...p, [q.label]: e.target.value }))}
                                                                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                                                                            required={q.required}
                                                                            aria-required={q.required || undefined}
                                                                            aria-invalid={error ? 'true' : undefined}
                                                                            aria-describedby={describedBy}
                                                                        />
                                                                    )}

                                                                    {/* Select Dropdown. The aria-label it used to carry is
                                                                        gone: it now has a real <label>, and an aria-label
                                                                        alongside one silently wins over it. */}
                                                                    {q.type === 'select' && (
                                                                        <select
                                                                            id={fieldId}
                                                                            value={(customAnswers[q.label] as string) || ''}
                                                                            onChange={(e) => setCustomAnswers(p => ({ ...p, [q.label]: e.target.value }))}
                                                                            className="w-full h-10 rounded-lg bg-white/10 border border-white/20 text-white px-3"
                                                                            required={q.required}
                                                                            aria-required={q.required || undefined}
                                                                            aria-invalid={error ? 'true' : undefined}
                                                                            aria-describedby={describedBy}
                                                                        >
                                                                            <option value="">Select...</option>
                                                                            {q.options?.map(opt => (
                                                                                <option key={opt} value={opt}>{opt}</option>
                                                                            ))}
                                                                        </select>
                                                                    )}

                                                                    {errorNode}
                                                                </div>
                                                            );
                                                        })}
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

                                        {/* Public-feed visibility. Only offered when the town has
                                            turned the Unlisted Reports module on. Sharing is the
                                            default; hiding is a deliberate, unchecked-by-default box. */}
                                        {(settings?.modules?.unlisted_reports ?? (settings?.modules as any)?.private_reports) && (
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
                                                                <a href={`#${fieldId}`} className="underline">{message}</a>
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
                                                    <><strong>Cannot submit:</strong> The selected location is outside the municipality boundary. Please choose a location within the jurisdiction.</>
                                                ) : (
                                                    <>Submission blocked - see notice above</>
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
                                        Request Submitted!
                                    </h1>
                                    <p className="text-white/60">
                                        Thank you for helping improve our community. Your request has been
                                        received and will be reviewed shortly.
                                    </p>
                                    {submittedId && (
                                        <div className="inline-block px-4 py-2 rounded-lg bg-white/10 border border-white/20">
                                            <span className="text-white/50 text-sm">Request ID: </span>
                                            <span className="font-mono text-white font-medium">{submittedId}</span>
                                        </div>
                                    )}
                                </div>

                                <Button onClick={handleReset} size="lg">
                                    Submit Another Request
                                </Button>
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

                    {/* Optional platform-feedback question.
                        In the footer, collapsed to one line, and deliberately
                        NOT a modal: a prompt that interrupts somebody filing a
                        report competes with the job they came to do. Renders
                        nothing at all unless the town enabled the module — the
                        component returns null, and the endpoint behind it 404s
                        regardless. */}
                    <PlatformFeedback
                        enabled={settings?.modules?.platform_feedback}
                        feedbackEmail={settings?.platform_feedback_email}
                    />

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
