import { useState, useEffect, useId } from 'react';
import { Bell, Mail, Smartphone, Loader2, Check, AlertCircle } from 'lucide-react';
import { api, NotificationPreferences } from '../services/api';
import { Modal } from './ui';
import { useAnnounce } from '../context/AccessibilityContext';

interface NotificationSettingsProps {
    isOpen: boolean;
    onClose: () => void;
    userName: string;
}

export default function NotificationSettings({ isOpen, onClose, userName }: NotificationSettingsProps) {
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [saveSuccess, setSaveSuccess] = useState(false);
    const [prefs, setPrefs] = useState<NotificationPreferences>({
        email_new_requests: true,
        email_status_changes: true,
        email_comments: true,
        email_assigned_only: false,
        sms_new_requests: false,
        sms_status_changes: false,
        phone: null
    });
    const [phone, setPhone] = useState('');
    const announce = useAnnounce();
    const phoneId = useId();

    useEffect(() => {
        if (isOpen) {
            loadPreferences();
        }
    }, [isOpen]);

    const loadPreferences = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const data = await api.getNotificationPreferences();
            setPrefs(data);
            setPhone(data.phone || '');
        } catch (err) {
            console.error('Failed to load notification preferences:', err);
            setError('Failed to load preferences');
            announce('Failed to load notification preferences', 'assertive');
        } finally {
            setIsLoading(false);
        }
    };

    const handleSave = async () => {
        setIsSaving(true);
        setError(null);
        setSaveSuccess(false);
        try {
            const updateData = {
                ...prefs,
                phone: phone.trim() || null
            };
            const updated = await api.updateNotificationPreferences(updateData);
            setPrefs(updated);
            setSaveSuccess(true);
            /* Both outcomes used to be visual only: a green strip that appears
             * and then removes itself after three seconds, or a red one. Focus
             * stays on the Save button either way, so a screen reader user
             * pressed Save and got silence — and by the time they went looking,
             * the success strip had already timed out (WCAG 4.1.3). */
            announce('Notification preferences saved');
            setTimeout(() => setSaveSuccess(false), 3000);
        } catch (err) {
            console.error('Failed to save notification preferences:', err);
            setError('Failed to save preferences');
            announce('Failed to save notification preferences', 'assertive');
        } finally {
            setIsSaving(false);
        }
    };

    const togglePref = (key: keyof NotificationPreferences) => {
        if (key === 'phone') return;
        setPrefs(prev => ({ ...prev, [key]: !prev[key] }));
    };

    /* The SMS toggles are inert until a phone number exists. That condition was
     * previously carried by opacity alone (WCAG 1.4.1) and by nothing at all in
     * the accessibility tree, so it is spelled out here once and handed to each
     * switch as its reason. */
    const smsDisabledReason = phone.trim() ? undefined : 'Add a phone number above to enable SMS alerts';

    /* Was a hand-rolled backdrop + panel with no dialog role, no name, no focus
     * trap, no Escape and no focus restore — the same gap its sibling
     * ManualIntake.tsx had before it moved to ui/Modal.tsx. Nothing about this
     * dialog needs bespoke chrome, so it uses the shared one rather than
     * reimplementing (and re-breaking) the trap. */
    return (
        <Modal
            isOpen={isOpen}
            onClose={onClose}
            title="Notification Settings"
            size="md"
            panelClassName="bg-slate-900 border border-white/10 shadow-2xl"
            headerClassName="bg-slate-900/95 backdrop-blur-xl"
        >
            <div className="flex items-center gap-3 mb-6">
                <div className="w-10 h-10 rounded-full bg-primary-500/20 flex items-center justify-center">
                    <Bell className="w-5 h-5 text-primary-400" aria-hidden="true" />
                </div>
                <p className="text-sm text-white/50">{userName}</p>
            </div>

            {/* Content */}
            <div className="max-h-[60vh] overflow-y-auto">
                {isLoading ? (
                    <div className="flex items-center justify-center py-8">
                        <Loader2 className="w-8 h-8 text-primary-400 animate-spin" aria-hidden="true" />
                        <span className="sr-only">Loading notification preferences…</span>
                    </div>
                ) : (
                    <div className="space-y-6">
                        {/* Email Notifications */}
                        <div>
                            <div className="flex items-center gap-2 mb-4">
                                <Mail className="w-4 h-4 text-white/60" aria-hidden="true" />
                                <h3 className="text-sm font-medium text-white/80 uppercase tracking-wider">Email Notifications</h3>
                            </div>
                            <div className="space-y-3">
                                <ToggleRow
                                    channel="Email"
                                    label="New Requests"
                                    description="Get notified when new requests are submitted"
                                    enabled={prefs.email_new_requests}
                                    onChange={() => togglePref('email_new_requests')}
                                />
                                <ToggleRow
                                    channel="Email"
                                    label="Status Changes"
                                    description="Get notified when request status changes"
                                    enabled={prefs.email_status_changes}
                                    onChange={() => togglePref('email_status_changes')}
                                />
                                <ToggleRow
                                    channel="Email"
                                    label="Comments"
                                    description="Get notified when comments are added"
                                    enabled={prefs.email_comments}
                                    onChange={() => togglePref('email_comments')}
                                />
                                <div className="pt-2 border-t border-white/5">
                                    <ToggleRow
                                        channel="Email"
                                        label="Assigned Only"
                                        description="Only notify for requests assigned to me"
                                        enabled={prefs.email_assigned_only}
                                        onChange={() => togglePref('email_assigned_only')}
                                    />
                                </div>
                            </div>
                        </div>

                        {/* SMS Notifications */}
                        <div>
                            <div className="flex items-center gap-2 mb-4">
                                <Smartphone className="w-4 h-4 text-white/60" aria-hidden="true" />
                                <h3 className="text-sm font-medium text-white/80 uppercase tracking-wider">SMS Notifications</h3>
                            </div>
                            <div className="space-y-3">
                                <div className="mb-4">
                                    <label htmlFor={phoneId} className="block text-sm text-white/60 mb-2">Phone Number</label>
                                    <input
                                        id={phoneId}
                                        type="tel"
                                        value={phone}
                                        onChange={(e) => setPhone(e.target.value)}
                                        placeholder="+1 555-123-4567"
                                        className="w-full px-4 py-2.5 bg-white/5 border border-white/10 rounded-lg text-white placeholder-white/30 focus:outline-none focus:ring-2 focus:ring-primary-500/50 focus:border-primary-500/50"
                                    />
                                </div>
                                <ToggleRow
                                    channel="SMS"
                                    label="New Requests"
                                    description="SMS alert for new requests"
                                    enabled={prefs.sms_new_requests}
                                    onChange={() => togglePref('sms_new_requests')}
                                    disabledReason={smsDisabledReason}
                                />
                                <ToggleRow
                                    channel="SMS"
                                    label="Status Changes"
                                    description="SMS alert when status changes"
                                    enabled={prefs.sms_status_changes}
                                    onChange={() => togglePref('sms_status_changes')}
                                    disabledReason={smsDisabledReason}
                                />
                            </div>
                        </div>

                        {/* Error/Success Messages — the spoken half of these is
                          * announce(), above; these strips stay purely visual so
                          * only one live region in the app is ever written. */}
                        {error && (
                            <div className="flex items-center gap-2 p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-red-300 text-sm">
                                <AlertCircle className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
                                {error}
                            </div>
                        )}
                        {saveSuccess && (
                            <div className="flex items-center gap-2 p-3 bg-green-500/10 border border-green-500/20 rounded-lg text-green-300 text-sm">
                                <Check className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
                                Preferences saved successfully
                            </div>
                        )}
                    </div>
                )}
            </div>

            {/* Footer */}
            <div className="pt-4 mt-4 border-t border-white/10 flex justify-end gap-3">
                <button
                    type="button"
                    onClick={onClose}
                    className="px-4 py-2 text-white/60 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                >
                    Cancel
                </button>
                <button
                    type="button"
                    onClick={handleSave}
                    disabled={isLoading || isSaving}
                    className="px-6 py-2 bg-primary-500 hover:bg-primary-600 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                    {isSaving ? (
                        <>
                            <Loader2 className="w-4 h-4 animate-spin" aria-hidden="true" />
                            Saving...
                        </>
                    ) : (
                        'Save Changes'
                    )}
                </button>
            </div>
        </Modal>
    );
}

// Toggle Row Component
function ToggleRow({
    channel,
    label,
    description,
    enabled,
    onChange,
    disabledReason
}: {
    /** "Email" or "SMS" — the switches repeat labels across the two sections
     *  ("New Requests" appears in both), so the visible label alone leaves two
     *  controls in the dialog with the same accessible name and no way to tell
     *  from speech which one is focused. */
    channel: string;
    label: string;
    description: string;
    enabled: boolean;
    onChange: () => void;
    /** When set, the switch is unavailable and this says why — shown to
     *  everyone and used as the switch's description. */
    disabledReason?: string;
}) {
    const reasonId = useId();
    const disabled = !!disabledReason;
    return (
        <div className={`flex items-center justify-between p-3 bg-white/5 rounded-lg ${disabled ? 'opacity-60' : ''}`}>
            <div className="flex-1 mr-4">
                <p className="text-sm font-medium text-white">{label}</p>
                <p className="text-xs text-white/50">{description}</p>
                {disabledReason && (
                    <p id={reasonId} className="text-xs text-amber-300 mt-1">{disabledReason}</p>
                )}
            </div>
            {/* A real <button role="switch">, not a div wearing the role. The div
              * version kept tabIndex={0} and reported aria-checked even while
              * inert, so a keyboard user tabbed to it, pressed Space, and got
              * nothing back — no state change, and no aria-disabled to explain
              * the silence (WCAG 4.1.2). It also had a click handler with no
              * type, no button element, and no native Space/Enter behaviour to
              * fall back on. `disabled` gives all of that for free, and the
              * reason text above replaces the opacity-only cue (1.4.1). */}
            <button
                type="button"
                role="switch"
                aria-checked={enabled}
                aria-label={`${channel} notifications for ${label}`}
                aria-describedby={disabledReason ? reasonId : undefined}
                disabled={disabled}
                onClick={onChange}
                className={`shrink-0 rounded-full focus-visible:ring-2 focus-visible:ring-amber-400 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 ${disabled ? 'cursor-not-allowed' : 'cursor-pointer'}`}
            >
                <div
                    className={`flex items-center rounded-full p-[2px] transition-colors duration-200 ${enabled ? 'bg-primary-500' : 'bg-slate-600'
                        }`}
                    style={{ width: '44px', height: '24px' }}
                >
                    <div
                        className="bg-white rounded-full shadow transition-all duration-200"
                        style={{
                            width: '20px',
                            height: '20px',
                            marginLeft: enabled ? '20px' : '0px'
                        }}
                    />
                </div>
            </button>
        </div>
    );
}
