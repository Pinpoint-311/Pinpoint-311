import { createContext, useContext, useState, useEffect, ReactNode, useCallback } from 'react';
import { Languages } from 'lucide-react';

interface TranslationContextType {
    t: (text: string) => string;
    language: string;
    setLanguage: (lang: string) => void;
    isLoading: boolean;
    refreshKey: number; // Used to trigger re-fetches in components
    showDisclaimer: boolean;
    setShowDisclaimer: (show: boolean) => void;
}

const TranslationContext = createContext<TranslationContextType | null>(null);

// All UI strings that need translation (excluding proper nouns like township name and Pinpoint 311)
const UI_STRINGS = [
    // Hero section
    'How can we help?',
    'Report issues, request services, and help make our community better. Select a category below to get started.',
    'Search services...',
    'Community Support Active',

    // Navigation & Actions
    'Track My Requests',
    'Staff Login',
    'Submit Request',
    'Back',
    'Next',
    'Submit',
    'Cancel',
    'Close',
    'Save',
    'Delete',
    'Edit',
    'View',
    'Loading...',

    // Map section
    'Community Requests Map',
    'View all reported issues and service requests in our community',
    'Filters',
    'Recent Status',
    'New',
    'In Progress',
    'Resolved',
    'On Hold',
    'Categories',
    'Departments',
    'Assigned Staff',
    'Priority Level',

    // Form steps
    'Step 1 of 4',
    'Step 2 of 4',
    'Step 3 of 4',
    'Step 4 of 4',
    'Select a Category',
    'Describe the Issue',
    'Choose Location',
    'Your Information',

    // Form fields
    'Description',
    'Location',
    'Photos',
    'Contact Information',
    'First Name',
    'Last Name',
    'Email',
    'Phone',
    'Phone (optional)',
    'Address',
    'Enter your address',
    'Describe the issue in detail...',
    'Add up to 3 photos',
    'Optional: Add photos to help us understand the issue',
    'Drag and drop or click to upload',

    // Validation messages
    'This field is required',
    'Please enter a valid email address',
    'Please select a location on the map',
    'Please describe the issue',

    // Success page
    'Request Submitted!',
    'Thank you for your submission',
    'Your request has been submitted successfully.',
    'We will review your request and get back to you soon.',
    'Request ID',
    'Submit Another Request',
    'Track This Request',

    // Service categories
    'No services found matching your search.',
    'Loading service categories...',
    'Select a service category to report an issue',

    // Footer
    'Privacy Policy',
    'Accessibility',
    'Terms of Service',
    'All rights reserved',
    'Free & Open Source Municipal Platform',
    'Powered by',

    // Tracking page
    'Track Requests',
    'Track Your Request',
    'View the status of community-reported issues',
    'Back to all requests',
    'Timeline & Status',
    'Community Discussion',
    'Enter your Request ID or Email',
    'Request ID or Email',
    'Track',
    'Request Status',
    'Submitted',
    'Updated',
    'Status',
    'Priority',
    'Category',
    'Department',
    'Assigned To',
    'Timeline',
    'Comments',
    'Add a Comment',
    'Post Comment',
    'Share',
    'Link Copied!',
    'No comments yet',
    'Be the first to share an update!',
    'No requests found',
    'All Requests',
    'Open',
    'Try adjusting your search or filters',
    'Search by ID, category, or address...',
    'Click anywhere to close',
    'Submitted Photos',
    'Completion Photo',
    'Share your thoughts or updates...',
    'Enter your request ID or email to track your submission',

    // Misc
    'or',
    'and',
    'Show more',
    'Show less',
    'See all',
    'Clear',
    'Search',
    'Filter',
    'Sort by',
    'Date',
    'Newest first',
    'Oldest first',

    // Translation disclaimer
    'Translated by Google Translate',
    'This page has been automatically translated and may contain inaccuracies. User-submitted content may not reflect the original meaning.',

    // Additional missing strings
    'Back to Home',
    'Posting...',
    'Assigned',
    'Public Works',
    'Filters',
    'Request Status',
    'Categories',
    'Departments',
    'Assigned Staff',
    'Priority Level',
    'Map',
    'Satellite',
    'events',
    'photo',
    'photos',
    'comment',
    'comments',

    // Timeline events
    'Request submitted',
    'Assigned to',
    'Closed',
    'Reopened',
    'Marked as In Progress',
    'Reverted to Open',
    'Status set to Open',
    'Reopened as In Progress',
    'Closed - Resolved',
    'Closed - No Action Needed',
    'Closed - Third Party',
    'Comment added',

    // Search and filter UI
    'Search by ID, category, or address...',
    'All Requests',
    'All Priorities',
    'High (8-10)',
    'Medium (5-7)',
    'Low (1-4)',

    // Map component
    'Map Layers',
    'Show All',
    'Hide All',
    'Search Requests',
    'Staff, address, description...',
    'Filter by assigned staff, address, or description',
    'Search services...',
    'Unassigned',
    'View Full Details',

    // Form labels and fields
    'Description',
    'Location / Address',
    'Photos (optional, max 3)',
    'Add Photos',
    'Contact Information',
    'First Name',
    'Last Name',
    'Email',
    'Phone (optional)',
    'Submit Request',
    'Back to categories',

    // Third-party routing
    'Third-Party Service',
    'Please contact:',
    'Visit Website',

    // Asset selection
    'Select This Street Light',
    'Select This Sign',
    'Select This Asset',
    'Asset Id',
    'Asset Type',
    'Street Light',
    'Sign',
    'Luminaire Type',
    'Wattage W',
    'Pole Height M',
    'Install Date',

    // Error messages
    'Failed to submit request. Please try again.',
    'Please fill in all required fields',
    'Description must be at least 10 characters',
];

interface TranslationProviderProps {
    children: ReactNode;
}

export function TranslationProvider({ children }: TranslationProviderProps) {
    const [language, setLanguageState] = useState(() => {
        return localStorage.getItem('preferredLanguage') || 'en';
    });
    const [translations, setTranslations] = useState<Record<string, string>>({});
    const [isLoading, setIsLoading] = useState(false);
    const [refreshKey, setRefreshKey] = useState(0);
    const [showDisclaimer, setShowDisclaimer] = useState(false);

    const setLanguage = useCallback((lang: string) => {
        setLanguageState(lang);
        localStorage.setItem('preferredLanguage', lang);
        // Trigger refresh in dependent components
        setRefreshKey(prev => prev + 1);
    }, []);

    // Load translations when language changes
    useEffect(() => {
        if (language === 'en') {
            setTranslations({});
            return;
        }

        // Check localStorage cache first
        const cacheKey = `translations_v4_${language}`;
        const cached = localStorage.getItem(cacheKey);
        if (cached) {
            try {
                setTranslations(JSON.parse(cached));
                // Show disclaimer after loading cached translations
                if (language !== 'en') {
                    setShowDisclaimer(true);
                    setTimeout(() => setShowDisclaimer(false), 8000);
                }
                return;
            } catch {
                // Invalid cache, fetch fresh
            }
        }

        // Fetch translations from API
        const fetchTranslations = async () => {
            setIsLoading(true);
            try {
                const response = await fetch('/api/system/translate/batch', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        texts: UI_STRINGS,
                        target_lang: language
                    })
                });

                if (response.ok) {
                    const data = await response.json();
                    const translationMap: Record<string, string> = {};
                    UI_STRINGS.forEach((text, index) => {
                        if (data.translations[index]) {
                            translationMap[text] = data.translations[index];
                        }
                    });
                    setTranslations(translationMap);
                    // Cache in localStorage
                    localStorage.setItem(cacheKey, JSON.stringify(translationMap));
                    // Show disclaimer after translations are loaded
                    if (language !== 'en') {
                        setShowDisclaimer(true);
                        setTimeout(() => setShowDisclaimer(false), 8000);
                    }
                }
            } catch (error) {
                console.error('Failed to fetch translations:', error);
            } finally {
                setIsLoading(false);
            }
        };

        fetchTranslations();
    }, [language]);

    const t = useCallback((text: string): string => {
        if (language === 'en') return text;
        return translations[text] || text;
    }, [language, translations]);

    return (
        <TranslationContext.Provider value={{ t, language, setLanguage, isLoading, refreshKey, showDisclaimer, setShowDisclaimer }}>
            {children}

            {/* Translation Disclaimer */}
            {showDisclaimer && language !== 'en' && (
                <div className="fixed bottom-4 right-4 z-[9999] max-w-sm">
                    <div className="bg-slate-900 border-2 border-blue-400/60 rounded-xl shadow-2xl p-4">
                        <div className="flex items-start gap-3">
                            <div className="p-2 bg-blue-500/20 rounded-lg">
                                <Languages className="w-5 h-5 text-blue-400" />
                            </div>
                            <div className="flex-1">
                                <p className="text-white text-sm font-semibold mb-1">{t('Translated by Google Translate')}</p>
                                <p className="text-white/90 text-xs leading-relaxed">
                                    {t('This page has been automatically translated and may contain inaccuracies. User-submitted content may not reflect the original meaning.')}
                                </p>
                            </div>
                            <button
                                onClick={() => setShowDisclaimer(false)}
                                className="text-white/60 hover:text-white transition-colors flex-shrink-0"
                                aria-label="Close disclaimer"
                            >
                                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </TranslationContext.Provider>
    );
}

export function useTranslation() {
    const context = useContext(TranslationContext);
    if (!context) {
        throw new Error('useTranslation must be used within a TranslationProvider');
    }
    return context;
}
