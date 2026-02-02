import React from 'react';
import { Link } from 'react-router-dom';
import { ArrowLeft, FileText, AlertTriangle } from 'lucide-react';
import { useSettings } from '../context/SettingsContext';

// Default terms of service based on 311 best practices
const DEFAULT_TERMS_OF_SERVICE = `
## ⚠️ NON-EMERGENCY SERVICE ONLY

**This is a NON-EMERGENCY service request system.**

**For emergencies, call 911 immediately.**

This includes but is not limited to:
- Medical emergencies
- Fires
- Crimes in progress
- Immediate threats to life or property
- Downed power lines
- Gas leaks

Do NOT use this system for urgent matters that require immediate response.

---

## Service Description

This 311 portal provides a convenient way for residents to submit non-emergency service requests to your municipal government. Common request types include:

- Pothole repairs
- Streetlight outages
- Graffiti removal
- Missed trash collection
- Code enforcement concerns
- Parks and facilities maintenance
- General municipal inquiries

## User Responsibilities

By using this service, you agree to:

- **Provide Accurate Information**: Submit truthful and accurate information in your requests
- **Use Appropriately**: Use this service only for legitimate municipal service requests
- **No Abuse**: Not submit false, fraudulent, or malicious requests
- **Respect Staff**: Communicate respectfully with municipal staff
- **Emergency Protocol**: Call 911 for any emergency situations

## Service Limitations

- **No Guaranteed Response Time**: While we strive to address requests promptly, response times vary based on priority, resources, and request volume
- **Municipal Jurisdiction Only**: We can only address issues within municipal jurisdiction
- **Third-Party Issues**: We cannot resolve issues related to private property, utilities managed by other entities, or matters outside municipal control
- **Resource Availability**: Services are subject to available resources and staffing

## Request Processing

- Requests are reviewed and routed to the appropriate department
- You may receive status updates if contact information was provided
- Request status can be tracked using your confirmation number
- Some requests may require additional information or inspection

## Disclaimer of Warranties

This service is provided "as is" without warranties of any kind. The municipality:

- Does not guarantee uninterrupted service availability
- Does not guarantee resolution of all reported issues
- Is not liable for issues arising from delayed responses
- Reserves the right to prioritize requests based on public safety and available resources

## Limitation of Liability

To the fullest extent permitted by law, the municipality shall not be liable for:

- Indirect, incidental, or consequential damages
- Issues arising from information provided by users
- Delays in addressing service requests
- Actions taken by third-party contractors

## Modifications

We reserve the right to modify these terms at any time. Continued use of the service constitutes acceptance of modified terms.

## Governing Law

These terms are governed by applicable state and local laws. Any disputes shall be resolved in accordance with the municipality's existing policies and procedures.

## Contact

For questions about this service or these terms, please contact your municipal clerk or the appropriate department.

---

*By submitting a service request, you acknowledge that you have read and agree to these terms.*
`;

export default function TermsOfService() {
    const { settings } = useSettings();

    const content = settings?.terms_of_service || DEFAULT_TERMS_OF_SERVICE;
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
                        <div className="w-10 h-10 rounded-xl bg-amber-500/20 flex items-center justify-center">
                            <FileText className="w-5 h-5 text-amber-400" />
                        </div>
                        <div>
                            <h1 className="text-xl font-bold text-white">Terms of Service</h1>
                            <p className="text-sm text-white/50">{townshipName} 311 Service</p>
                        </div>
                    </div>
                </div>
            </header>

            {/* Emergency Warning Banner */}
            <div className="bg-red-500/20 border-b border-red-500/30">
                <div className="max-w-4xl mx-auto px-4 py-3 flex items-center gap-3">
                    <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0" />
                    <p className="text-red-200 text-sm">
                        <strong>This is NOT for emergencies.</strong> For police, fire, or medical emergencies, call <strong>911</strong> immediately.
                    </p>
                </div>
            </div>

            {/* Content */}
            <main className="max-w-4xl mx-auto px-4 py-8">
                <div className="glass-card rounded-2xl p-8">
                    <div className="prose prose-invert prose-sm max-w-none">
                        {/* Simple markdown-like rendering */}
                        {content.split('\n').map((line, i) => {
                            if (line.startsWith('## ⚠️')) {
                                return (
                                    <div key={i} className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 mb-6">
                                        <h2 className="text-xl font-bold text-red-400 flex items-center gap-2">
                                            <AlertTriangle className="w-6 h-6" />
                                            {line.replace('## ⚠️ ', '')}
                                        </h2>
                                    </div>
                                );
                            }
                            if (line.startsWith('## ')) {
                                return <h2 key={i} className="text-xl font-bold text-white mt-8 mb-4">{line.replace('## ', '')}</h2>;
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
