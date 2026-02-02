import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, Shield } from 'lucide-react';
import { useSettings } from '../context/SettingsContext';

// Default privacy policy based on 311 best practices
const DEFAULT_PRIVACY_POLICY = `
## Information We Collect

When you submit a service request, we collect only the information necessary to process and respond to your request:

- **Contact Information**: Name, email address, and/or phone number (optional for anonymous submissions)
- **Location Data**: Address or geographic coordinates related to your service request
- **Request Details**: Description of the issue, photos, and any additional context you provide
- **Technical Data**: Browser type, device information, and IP address for security purposes

### Anonymous Submissions

For most request types, you may submit anonymously. However, providing contact information allows us to:
- Send you status updates on your request
- Request additional information if needed
- Notify you when your issue has been resolved

## How We Use Your Information

Your information is used exclusively for municipal service purposes:

- Processing and tracking your service requests
- Routing requests to the appropriate department
- Communicating with you about your request status
- Improving our services based on aggregate data
- Complying with public records laws

**We do not:**
- Sell your personal information
- Use your information for marketing purposes
- Share your information with third parties for commercial purposes

## Information Sharing

We may share your information with:

- **Municipal Departments**: Staff members responsible for addressing your service request
- **Contractors**: Third-party vendors working on behalf of the municipality
- **Legal Requirements**: When required by law, court order, or public records request

## Data Retention

Your service request data is retained in accordance with applicable state public records retention schedules. Personal identifying information may be anonymized after the required retention period.

## Your Rights

You have the right to:
- Request access to your personal information
- Request correction of inaccurate information
- Submit requests anonymously (for most request types)
- Contact us with privacy concerns

## Security

We implement appropriate technical and organizational measures to protect your personal information, including encryption of data in transit and at rest.

## Contact Us

For privacy-related questions or concerns, please contact your municipal clerk or the department of administration.

---

*This privacy policy applies to service requests submitted through the 311 portal. For the municipality's general privacy policy, please visit the main municipal website.*
`;

export default function PrivacyPolicy() {
    const { settings } = useSettings();

    const content = settings?.privacy_policy || DEFAULT_PRIVACY_POLICY;
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
                        <div className="w-10 h-10 rounded-xl bg-primary-500/20 flex items-center justify-center">
                            <Shield className="w-5 h-5 text-primary-400" />
                        </div>
                        <div>
                            <h1 className="text-xl font-bold text-white">Privacy Policy</h1>
                            <p className="text-sm text-white/50">{townshipName} 311 Service</p>
                        </div>
                    </div>
                </div>
            </header>

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
                                const match = line.match(/- \*\*(.+?)\*\*: (.+)/);
                                if (match) {
                                    return (
                                        <li key={i} className="text-white/70 ml-4 my-1">
                                            <strong className="text-white">{match[1]}:</strong> {match[2]}
                                        </li>
                                    );
                                }
                            }
                            if (line.startsWith('- ')) {
                                return <li key={i} className="text-white/70 ml-4 my-1">{line.replace('- ', '')}</li>;
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
