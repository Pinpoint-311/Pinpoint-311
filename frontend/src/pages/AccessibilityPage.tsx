import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Accessibility, Check } from 'lucide-react';
import { useSettings } from '../context/SettingsContext';

// Default accessibility statement based on WCAG and government best practices
const DEFAULT_ACCESSIBILITY_STATEMENT = `
## Our Commitment

We are committed to ensuring digital accessibility for all users, including people with disabilities. We continually improve the user experience for everyone and apply the relevant accessibility standards.

## Accessibility Standards

This 311 portal is designed to conform to:

- **WCAG 2.1 Level AA** - Web Content Accessibility Guidelines
- **Section 508** - Federal accessibility requirements
- **ADA** - Americans with Disabilities Act requirements

## Accessibility Features

This portal includes the following accessibility features:

- **Keyboard Navigation**: All functionality is accessible via keyboard
- **Screen Reader Support**: Semantic HTML and ARIA labels for assistive technologies
- **Color Contrast**: Text meets WCAG AA contrast ratios
- **Resizable Text**: Content remains functional when text is resized up to 200%
- **Focus Indicators**: Visible focus states for keyboard navigation
- **Skip Links**: Skip to main content functionality
- **Form Labels**: All form inputs have associated labels
- **Error Identification**: Form errors are clearly identified and described
- **Language**: Page language is properly declared

## Alternative Submission Methods

If you are unable to use this web portal, you can submit service requests via:

- **Phone**: Call 311 or your municipality's main number
- **In Person**: Visit your municipal building during business hours
- **Email**: Contact your municipal clerk

## Known Limitations

We are aware of and working to address:

- Some third-party content may not fully conform to accessibility standards
- Dynamic content updates may require manual refresh for some screen readers
- Map interfaces provide text alternatives but may have limited functionality for some users

## Feedback

We welcome your feedback on the accessibility of this portal. Please let us know if you encounter accessibility barriers:

- Report an accessibility issue through the service request form
- Contact your municipal clerk's office
- Email the IT department

We try to respond to accessibility feedback within 5 business days.

## Continuous Improvement

We conduct regular accessibility audits and training to:

- Identify and remediate accessibility issues
- Train staff on accessibility best practices
- Test with assistive technologies
- Incorporate user feedback

---

*This statement was last reviewed and updated on the date shown below. We regularly review our accessibility practices.*
`;

export default function AccessibilityPage() {
    const { settings } = useSettings();

    const content = settings?.accessibility_statement || DEFAULT_ACCESSIBILITY_STATEMENT;
    const townshipName = settings?.township_name || 'Your Township';

    return (
        <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900">
            {/* Header */}
            <header className="glass-sidebar border-b border-white/10">
                <div className="max-w-4xl mx-auto px-4 py-4 flex items-center gap-4">
                    <Link
                        to="/"
                        className="p-2 rounded-lg hover:bg-white/10 transition-colors"
                        aria-label="Back to home"
                    >
                        <ArrowLeft className="w-5 h-5 text-white/70" />
                    </Link>
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-xl bg-emerald-500/20 flex items-center justify-center">
                            <Accessibility className="w-5 h-5 text-emerald-400" />
                        </div>
                        <div>
                            <h1 className="text-xl font-bold text-white">Accessibility Statement</h1>
                            <p className="text-sm text-white/50">{townshipName} 311 Service</p>
                        </div>
                    </div>
                </div>
            </header>

            {/* Accessibility Commitment Banner */}
            <div className="bg-emerald-500/20 border-b border-emerald-500/30">
                <div className="max-w-4xl mx-auto px-4 py-3 flex items-center gap-3">
                    <Check className="w-5 h-5 text-emerald-400 flex-shrink-0" />
                    <p className="text-emerald-200 text-sm">
                        This portal is designed to meet <strong>WCAG 2.1 Level AA</strong> accessibility standards.
                    </p>
                </div>
            </div>

            {/* Content */}
            <main className="max-w-4xl mx-auto px-4 py-8">
                <div className="glass-card rounded-2xl p-8">
                    <div className="prose prose-invert prose-sm max-w-none">
                        {/* Simple markdown-like rendering */}
                        {content.split('\n').map((line, i) => {
                            if (line.startsWith('## ')) {
                                return <h2 key={i} className="text-xl font-bold text-white mt-8 mb-4 first:mt-0">{line.replace('## ', '')}</h2>;
                            }
                            if (line.startsWith('### ')) {
                                return <h3 key={i} className="text-lg font-semibold text-white/90 mt-6 mb-3">{line.replace('### ', '')}</h3>;
                            }
                            if (line.startsWith('- **')) {
                                const match = line.match(/- \*\*(.+?)\*\*:? ?(.+)?/);
                                if (match) {
                                    return (
                                        <li key={i} className="text-white/70 ml-4 my-1 flex items-start gap-2">
                                            <Check className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" />
                                            <span><strong className="text-white">{match[1]}</strong>{match[2] ? `: ${match[2]}` : ''}</span>
                                        </li>
                                    );
                                }
                            }
                            if (line.startsWith('- ')) {
                                return (
                                    <li key={i} className="text-white/70 ml-4 my-1 flex items-start gap-2">
                                        <span className="text-emerald-400">•</span>
                                        <span>{line.replace('- ', '')}</span>
                                    </li>
                                );
                            }
                            if (line.startsWith('**') && line.endsWith('**')) {
                                return <p key={i} className="text-white font-semibold my-2">{line.replace(/\*\*/g, '')}</p>;
                            }
                            if (line.startsWith('*') && line.endsWith('*')) {
                                return <p key={i} className="text-white/50 italic text-sm my-4">{line.replace(/\*/g, '')}</p>;
                            }
                            if (line === '---') {
                                return <hr key={i} className="border-white/10 my-8" />;
                            }
                            if (line.trim()) {
                                return <p key={i} className="text-white/70 my-3">{line}</p>;
                            }
                            return null;
                        })}
                    </div>
                </div>

                <p className="text-center text-white/30 text-sm mt-8">
                    Last updated: {new Date().toLocaleDateString()}
                </p>
            </main>
        </div>
    );
}
