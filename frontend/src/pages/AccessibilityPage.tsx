import { useEffect } from 'react';
import type { ReactNode } from 'react';
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

This portal includes the following accessibility features. This list describes
the resident-facing portal — the pages for reporting an issue, tracking a
request, and these information pages.

- **Skip Link**: A "skip to main content" link appears on the first press of Tab on every page
- **Keyboard Navigation**: The reporting form, the request tracker and the address search can be completed with the keyboard alone
- **Screen Reader Support**: Semantic HTML, with ARIA used only where HTML has no equivalent
- **Focus Order**: Moving between steps of a report moves keyboard focus to the new step's heading, rather than leaving it at the top of the document
- **Color Contrast**: Text meets WCAG AA contrast ratios
- **Resizable Text**: Content remains functional when text is resized up to 200%
- **Focus Indicators**: Visible focus states for keyboard navigation, including on custom-styled checkboxes
- **Form Labels**: Every input in the reporting form has an associated label, including the questions your municipality adds to a category
- **Autofill**: Name, email, phone and address fields declare their purpose so a browser or assistive tool can fill them
- **Error Identification**: A failed submission lists what needs fixing, moves focus to that list, and links each message to the field it is about
- **Status Messages**: Copying a tracking link, dropping a map pin, and a blocked submission are announced to screen readers
- **Language**: Page language is properly declared, including on machine-translated content

## Alternative Submission Methods

If you are unable to use this web portal, you can submit service requests via:

- **Phone**: Call 311 or your municipality's main number
- **In Person**: Visit your municipal building during business hours
- **Email**: Contact your municipal clerk

## Known Limitations

We would rather name these than imply they are solved. We are aware of and
working to address:

- Placing a pin by dragging it on the map is a pointer gesture with no keyboard equivalent. Typing an address, or using "Use my current location", sets the same location, so a report can always be filed without the map — but the map itself is not keyboard operable
- Map tiles, markers and the map provider's own controls come from a third party and have not been audited by us
- The staff and administrator console has not been through the same review as the resident portal, and should not be assumed to meet AA
- Photos uploaded by other residents carry generic descriptions ("Submitted photo 2"), because the person who uploaded them is not asked for alternative text
- Automatic translations are machine-generated; wording and phrasing may be less clear than the English original
- This statement describes our own assessment. It has not yet been confirmed by an independent audit

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

/* Consecutive "- " lines become one <ul>.
 *
 * The renderer emitted bare <li> elements with no list parent at all, which is
 * not just invalid markup: a screen reader has nothing to announce as a list,
 * so there is no "list, 6 items", no item numbering, and no way to skip past it
 * (WCAG 1.3.1 Info and Relationships). Grouping happens before rendering, so
 * every item keeps exactly the markup it had.
 */
function renderStatement(content: string): ReactNode[] {
    const out: ReactNode[] = [];
    let items: ReactNode[] = [];

    const flushList = () => {
        if (items.length === 0) return;
        out.push(<ul key={`list-${out.length}`} className="list-none pl-0 my-3">{items}</ul>);
        items = [];
    };

    content.split('\n').forEach((line, i) => {
        if (line.startsWith('- ')) {
            const match = line.match(/- \*\*(.+?)\*\*:? ?(.+)?/);
            items.push(match ? (
                <li key={i} className="text-white/70 ml-4 my-1 flex items-start gap-2">
                    <Check className="w-4 h-4 text-emerald-400 mt-0.5 flex-shrink-0" aria-hidden="true" />
                    <span><strong className="text-white">{match[1]}</strong>{match[2] ? `: ${match[2]}` : ''}</span>
                </li>
            ) : (
                <li key={i} className="text-white/70 ml-4 my-1 flex items-start gap-2">
                    <span className="text-emerald-400" aria-hidden="true">&bull;</span>
                    <span>{line.replace('- ', '')}</span>
                </li>
            ));
            return;
        }

        flushList();

        if (line.startsWith('## ')) {
            out.push(<h2 key={i} className="text-xl font-bold text-white mt-8 mb-4 first:mt-0">{line.replace('## ', '')}</h2>);
        } else if (line.startsWith('### ')) {
            out.push(<h3 key={i} className="text-lg font-semibold text-white/90 mt-6 mb-3">{line.replace('### ', '')}</h3>);
        } else if (line.startsWith('**') && line.endsWith('**')) {
            out.push(<p key={i} className="text-white font-semibold my-2">{line.replace(/\*\*/g, '')}</p>);
        } else if (line.startsWith('*') && line.endsWith('*')) {
            out.push(<p key={i} className="text-white/50 italic text-sm my-4">{line.replace(/\*/g, '')}</p>);
        } else if (line === '---') {
            out.push(<hr key={i} className="border-white/10 my-8" />);
        } else if (line.trim()) {
            out.push(<p key={i} className="text-white/70 my-3">{line}</p>);
        }
    });

    flushList();
    return out;
}

export default function AccessibilityPage() {
    const { settings } = useSettings();

    const content = settings?.accessibility_statement || DEFAULT_ACCESSIBILITY_STATEMENT;
    const townshipName = settings?.township_name || 'Your Municipality';

    /* Every one of the static pages kept index.html's default title, so a
     * screen-reader user tabbing through browser tabs, and anyone reading their
     * history or bookmarks, saw the same string on four different pages (WCAG
     * 2.4.2 Page Titled). Restored on unmount so the portal's own title logic
     * takes over again. */
    useEffect(() => {
        const previousTitle = document.title;
        document.title = `Accessibility Statement | ${settings?.township_name || 'Municipality 311'}`;
        return () => { document.title = previousTitle; };
    }, [settings?.township_name]);

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
            <main id="main-content" className="max-w-4xl mx-auto px-4 py-8">
                <div className="glass-card rounded-2xl p-8">
                    <div className="prose prose-invert prose-sm max-w-none">
                        {renderStatement(content)}
                    </div>
                </div>

                <p className="text-center text-white/30 text-sm mt-8">
                    Last updated: {new Date().toLocaleDateString()}
                </p>
            </main>
        </div>
    );
}
