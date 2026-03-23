import { useState, useEffect, useRef } from 'react';
import { X } from 'lucide-react';

interface TourStep {
    target: string;        // CSS selector for the element to highlight
    title: string;
    description: string;
    position: 'bottom' | 'right' | 'left';
}

const TOUR_STEPS: TourStep[] = [
    {
        target: '[aria-label="Staff portal navigation"]',
        title: 'Navigate the Dashboard',
        description: 'Switch between Open, In Progress, and Resolved queues from the sidebar.',
        position: 'right',
    },
    {
        target: '[aria-label="Staff portal navigation"] button:nth-child(2)',
        title: 'Request Queue',
        description: 'Click any request to see full details, AI-powered analysis, and location on the map.',
        position: 'right',
    },
    {
        target: '[aria-label="Staff portal navigation"] button:nth-child(1)',
        title: 'Dashboard Overview',
        description: 'The main dashboard shows the geospatial map with all requests plotted by priority.',
        position: 'right',
    },
    {
        target: '[aria-label="Staff portal navigation"] button:last-child',
        title: 'Analytics & Insights',
        description: 'View trends, response times, and ask the AI Analytics Advisor questions about your data.',
        position: 'right',
    },
];

const STORAGE_KEY = 'demo_tour_dismissed';

export default function DemoTour() {
    const [currentStep, setCurrentStep] = useState(0);
    const [visible, setVisible] = useState(false);
    const [position, setPosition] = useState({ top: 0, left: 0 });
    const tooltipRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        // Only show if not dismissed and data has loaded
        if (localStorage.getItem(STORAGE_KEY)) return;
        // Delay to let dashboard render
        const timer = setTimeout(() => setVisible(true), 2000);
        return () => clearTimeout(timer);
    }, []);

    useEffect(() => {
        if (!visible) return;
        const step = TOUR_STEPS[currentStep];
        const el = document.querySelector(step.target);
        if (!el) return;

        const rect = el.getBoundingClientRect();
        const pos = { top: 0, left: 0 };

        if (step.position === 'right') {
            pos.top = rect.top + rect.height / 2 - 60;
            pos.left = rect.right + 16;
        } else if (step.position === 'bottom') {
            pos.top = rect.bottom + 12;
            pos.left = rect.left + rect.width / 2 - 150;
        } else {
            pos.top = rect.top + rect.height / 2 - 60;
            pos.left = rect.left - 316;
        }

        // Clamp to viewport
        pos.top = Math.max(16, Math.min(pos.top, window.innerHeight - 200));
        pos.left = Math.max(16, Math.min(pos.left, window.innerWidth - 320));
        setPosition(pos);
    }, [currentStep, visible]);

    const dismiss = () => {
        setVisible(false);
        localStorage.setItem(STORAGE_KEY, '1');
    };

    const next = () => {
        if (currentStep < TOUR_STEPS.length - 1) {
            setCurrentStep(currentStep + 1);
        } else {
            dismiss();
        }
    };

    if (!visible) return null;

    const step = TOUR_STEPS[currentStep];

    return (
        <>
            {/* Backdrop */}
            <div
                className="fixed inset-0 bg-black/40 z-[9998]"
                onClick={dismiss}
            />
            {/* Tooltip */}
            <div
                ref={tooltipRef}
                className="fixed z-[9999] w-[300px]"
                style={{ top: position.top, left: position.left }}
            >
                <div
                    className="rounded-xl p-4 border border-primary-400/40 shadow-2xl shadow-black/50"
                    style={{ background: 'rgb(30, 27, 75)' }}
                >
                    <div className="flex items-start justify-between mb-2">
                        <div>
                            <p className="text-[10px] font-bold text-primary-300 uppercase tracking-widest mb-1">
                                Demo Tour — {currentStep + 1}/{TOUR_STEPS.length}
                            </p>
                            <h3 className="text-sm font-semibold text-white">{step.title}</h3>
                        </div>
                        <button
                            onClick={dismiss}
                            className="text-white/30 hover:text-white transition-colors p-1"
                            aria-label="Close tour"
                        >
                            <X className="w-4 h-4" />
                        </button>
                    </div>
                    <p className="text-xs text-white/70 leading-relaxed mb-3">{step.description}</p>
                    <div className="flex items-center justify-between">
                        {/* Progress dots */}
                        <div className="flex gap-1.5">
                            {TOUR_STEPS.map((_, i) => (
                                <div
                                    key={i}
                                    className={`w-1.5 h-1.5 rounded-full transition-colors ${
                                        i === currentStep ? 'bg-primary-400' : i < currentStep ? 'bg-primary-400/40' : 'bg-white/15'
                                    }`}
                                />
                            ))}
                        </div>
                        <div className="flex gap-2">
                            <button
                                onClick={dismiss}
                                className="text-xs text-white/40 hover:text-white/70 transition-colors"
                            >
                                Skip
                            </button>
                            <button
                                onClick={next}
                                className="text-xs font-semibold text-primary-300 hover:text-white transition-colors"
                            >
                                {currentStep < TOUR_STEPS.length - 1 ? 'Next →' : 'Done ✓'}
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </>
    );
}
