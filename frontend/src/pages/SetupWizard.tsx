import React, { useState, useEffect } from 'react';
import { Shield, Cloud, Check, AlertCircle, Loader2, ExternalLink, Lock, Upload, Database, Key, Sparkles, RefreshCw } from 'lucide-react';
import { api } from '../services/api';

interface SetupStatus {
    gcp_configured: boolean;
    auth0_configured: boolean;
    gcp_details?: any;
    auth0_details?: any;
}

export function SetupWizard() {
    const [currentStep, setCurrentStep] = useState<'check' | 'gcp' | 'auth0' | 'complete'>('check');
    const [status, setStatus] = useState<SetupStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Reconfigure mode - allows re-running even if already configured
    const [gcpReconfigureMode, setGcpReconfigureMode] = useState(false);
    const [auth0ReconfigureMode, setAuth0ReconfigureMode] = useState(false);

    // GCP form state
    const [gcpForm, setGcpForm] = useState({
        project_id: '',
        service_account_json: ''
    });
    const [gcpLoading, setGcpLoading] = useState(false);
    const [gcpSuccess, setGcpSuccess] = useState(false);

    // Auth0 form state
    const [auth0Form, setAuth0Form] = useState({
        domain: '',
        client_id: '',
        client_secret: '',
        callback_url: window.location.origin + '/api/auth/callback'
    });
    const [auth0Loading, setAuth0Loading] = useState(false);
    const [auth0Success, setAuth0Success] = useState(false);

    useEffect(() => {
        checkStatus();
    }, []);

    const checkStatus = async () => {
        try {
            setLoading(true);
            const response = await api.getSetupStatus();
            setStatus(response);

            // Determine which step to show (GCP first, then Auth0)
            if (response.gcp_configured && response.auth0_configured) {
                setCurrentStep('complete');
            } else if (!response.gcp_configured) {
                setCurrentStep('gcp');
            } else if (!response.auth0_configured) {
                setCurrentStep('auth0');
            }
        } catch (err: any) {
            setError(err.response?.detail || 'Failed to check setup status');
        } finally {
            setLoading(false);
        }
    };

    const configureGCP = async () => {
        try {
            setGcpLoading(true);
            setError(null);

            await api.configureGCP(gcpForm);

            setGcpSuccess(true);
            setTimeout(() => {
                setCurrentStep('auth0');
                checkStatus();
            }, 2000);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Failed to configure Google Cloud');
        } finally {
            setGcpLoading(false);
        }
    };

    const configureAuth0 = async () => {
        try {
            setAuth0Loading(true);
            setError(null);

            await api.configureAuth0({
                domain: auth0Form.domain,
                management_client_id: auth0Form.client_id,
                management_client_secret: auth0Form.client_secret,
                callback_url: auth0Form.callback_url
            });

            setAuth0Success(true);
            setTimeout(() => {
                checkStatus();
            }, 2000);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Failed to configure Auth0');
        } finally {
            setAuth0Loading(false);
        }
    };

    const skipGCP = () => {
        setCurrentStep('auth0');
    };

    if (loading) {
        return (
            <div className="min-h-screen bg-gradient-to-br from-indigo-900 via-purple-900 to-slate-900 flex items-center justify-center">
                <div className="text-center">
                    <Loader2 className="w-12 h-12 text-indigo-400 animate-spin mx-auto mb-4" />
                    <p className="text-white/70">Checking system status...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-indigo-900 via-purple-900 to-slate-900 py-12 px-4">
            <div className="max-w-4xl mx-auto">
                {/* Header */}
                <div className="text-center mb-12">
                    <div className="inline-flex items-center justify-center w-16 h-16 bg-indigo-600 rounded-2xl mb-4">
                        <Shield className="w-8 h-8 text-white" />
                    </div>
                    <h1 className="text-4xl font-bold text-white mb-2">Automated Setup Wizard</h1>
                    <p className="text-lg text-white/60">Configure Google Cloud and Auth0 in minutes</p>
                </div>

                {/* Progress Steps - GCP First, then Auth0 */}
                <div className="mb-12">
                    <div className="flex items-center justify-center space-x-4">
                        <StepIndicator
                            label="Google Cloud"
                            active={currentStep === 'gcp'}
                            completed={status?.gcp_configured || gcpSuccess}
                            icon={Cloud}
                        />
                        <div className="w-16 h-1 bg-white/20 rounded-full">
                            <div className={`h-full bg-green-500 rounded-full transition-all ${status?.gcp_configured || gcpSuccess ? 'w-full' : 'w-0'}`} />
                        </div>
                        <StepIndicator
                            label="Auth0 SSO"
                            active={currentStep === 'auth0'}
                            completed={status?.auth0_configured || auth0Success}
                            icon={Shield}
                        />
                        <div className="w-16 h-1 bg-white/20 rounded-full">
                            <div className={`h-full bg-green-500 rounded-full transition-all ${status?.auth0_configured || auth0Success ? 'w-full' : 'w-0'}`} />
                        </div>
                        <StepIndicator
                            label="Complete"
                            active={currentStep === 'complete'}
                            completed={currentStep === 'complete'}
                            icon={Check}
                        />
                    </div>
                </div>

                {/* Error Display */}
                {error && (
                    <div className="mb-6 bg-red-500/20 border border-red-400/30 rounded-xl p-4 flex items-start space-x-3">
                        <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                        <div>
                            <p className="text-red-200 font-medium">Configuration Error</p>
                            <p className="text-red-300/80 text-sm mt-1">{error}</p>
                        </div>
                    </div>
                )}

                {/* Step Content */}
                <div className="bg-white/10 backdrop-blur-xl rounded-2xl shadow-xl border border-white/20 p-8">
                    {currentStep === 'gcp' && (
                        <GCPSetupForm
                            form={gcpForm}
                            setForm={setGcpForm}
                            onSubmit={configureGCP}
                            onSkip={skipGCP}
                            loading={gcpLoading}
                            success={gcpSuccess}
                            alreadyConfigured={status?.gcp_configured && !gcpReconfigureMode}
                            onReconfigure={() => setGcpReconfigureMode(true)}
                        />
                    )}

                    {currentStep === 'auth0' && (
                        <Auth0SetupForm
                            form={auth0Form}
                            setForm={setAuth0Form}
                            onSubmit={configureAuth0}
                            loading={auth0Loading}
                            success={auth0Success}
                            gcpConfigured={status?.gcp_configured || gcpSuccess}
                        />
                    )}

                    {currentStep === 'complete' && (
                        <CompletionScreen
                            status={status}
                            onReconfigureGCP={() => {
                                setGcpReconfigureMode(true);
                                setGcpSuccess(false);
                                setCurrentStep('gcp');
                            }}
                            onReconfigureAuth0={() => {
                                setAuth0ReconfigureMode(true);
                                setAuth0Success(false);
                                setCurrentStep('auth0');
                            }}
                        />
                    )}
                </div>
            </div>
        </div>
    );
}

// Step Indicator Component
interface StepIndicatorProps {
    label: string;
    active: boolean;
    completed: boolean;
    icon: React.ElementType;
}

function StepIndicator({ label, active, completed, icon: Icon }: StepIndicatorProps) {
    return (
        <div className="flex flex-col items-center">
            <div className={`
                w-14 h-14 rounded-full flex items-center justify-center transition-all
                ${completed ? 'bg-green-500 text-white' : active ? 'bg-indigo-500 text-white' : 'bg-white/20 text-white/50'}
            `}>
                {completed ? <Check className="w-6 h-6" /> : <Icon className="w-6 h-6" />}
            </div>
            <p className={`mt-2 text-sm font-medium ${active ? 'text-indigo-300' : completed ? 'text-green-400' : 'text-white/50'}`}>
                {label}
            </p>
        </div>
    );
}

// GCP Setup Form
interface GCPSetupFormProps {
    form: { project_id: string; service_account_json: string };
    setForm: (form: any) => void;
    onSubmit: () => void;
    onSkip: () => void;
    loading: boolean;
    success: boolean;
    alreadyConfigured?: boolean;
    onReconfigure?: () => void;
}


function GCPSetupForm({ form, setForm, onSubmit, onSkip, loading, success, alreadyConfigured, onReconfigure }: GCPSetupFormProps) {
    const [fileUploaded, setFileUploaded] = useState(false);
    const [reconfiguring, setReconfiguring] = useState(false);

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) {
            const reader = new FileReader();
            reader.onload = (event) => {
                const content = event.target?.result as string;
                try {
                    const json = JSON.parse(content);
                    setForm({
                        ...form,
                        project_id: json.project_id || form.project_id,
                        service_account_json: content
                    });
                    setFileUploaded(true);
                } catch (err) {
                    alert('Invalid JSON file');
                }
            };
            reader.readAsText(file);
        }
    };

    if (success && !alreadyConfigured) {
        return (
            <div className="text-center py-12">
                <div className="inline-flex items-center justify-center w-16 h-16 bg-green-500/30 rounded-full mb-4">
                    <Check className="w-8 h-8 text-green-400" />
                </div>
                <h2 className="text-2xl font-bold text-white mb-2">Google Cloud Configured!</h2>
                <p className="text-white/60">Secret Manager and KMS have been set up.</p>
            </div>
        );
    }

    // Show reconfigure option if already configured
    if (alreadyConfigured && !reconfiguring) {
        return (
            <div className="text-center py-8">
                <div className="inline-flex items-center justify-center w-16 h-16 bg-green-500/30 rounded-full mb-4">
                    <Check className="w-8 h-8 text-green-400" />
                </div>
                <h2 className="text-2xl font-bold text-white mb-2">Google Cloud Already Configured</h2>
                <p className="text-white/60 mb-6">Your GCP credentials are already set up. You can update them if needed.</p>
                <button
                    onClick={() => {
                        setReconfiguring(true);
                        if (onReconfigure) onReconfigure();
                    }}
                    className="inline-flex items-center px-6 py-3 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-medium transition-all"
                >
                    <RefreshCw className="w-5 h-5 mr-2" />
                    Reconfigure GCP
                </button>
            </div>
        );
    }

    return (
        <div>
            <div className="mb-6">
                <h2 className="text-2xl font-bold text-white mb-2 flex items-center">
                    <Cloud className="w-7 h-7 text-blue-400 mr-3" />
                    Configure Google Cloud Platform
                </h2>
                <p className="text-white/60">
                    GCP provides Secret Manager for secure credential storage, KMS for encryption, and AI services.
                </p>
            </div>

            {/* Why GCP First */}
            <div className="bg-blue-500/20 border border-blue-400/30 rounded-xl p-4 mb-6">
                <div className="flex items-start space-x-3">
                    <Database className="w-5 h-5 text-blue-400 flex-shrink-0 mt-0.5" />
                    <div>
                        <p className="text-blue-200 font-medium text-sm">Why Configure GCP First?</p>
                        <p className="text-blue-100 text-sm mt-1">
                            Google Cloud Secret Manager securely stores Auth0 credentials. If you skip this, credentials will be stored locally with Fernet encryption.
                        </p>
                    </div>
                </div>
            </div>

            {/* Required Services */}
            <div className="grid grid-cols-2 gap-4 mb-8">
                {[
                    { name: 'Secret Manager', desc: 'Credential storage', icon: Key },
                    { name: 'Cloud KMS', desc: 'PII encryption', icon: Lock },
                    { name: 'Translation API', desc: 'Multi-language', icon: Sparkles },
                    { name: 'Vertex AI', desc: 'AI analysis', icon: Database },
                ].map(({ name, desc, icon: ItemIcon }) => (
                    <div key={name} className="bg-white/5 border border-white/10 rounded-xl p-4 flex items-center gap-4">
                        <div className="w-10 h-10 rounded-lg bg-white/10 flex items-center justify-center">
                            <ItemIcon className="w-5 h-5 text-indigo-400" />
                        </div>
                        <div>
                            <p className="text-white text-sm font-semibold">{name}</p>
                            <p className="text-white/75 text-xs">{desc}</p>
                        </div>
                    </div>
                ))}
            </div>

            {/* Required IAM Permissions */}
            <div className="bg-amber-500/20 border border-amber-400/30 rounded-xl p-4 mb-6">
                <div className="flex items-start space-x-3">
                    <Key className="w-5 h-5 text-amber-400 flex-shrink-0 mt-0.5" />
                    <div>
                        <p className="text-amber-200 font-medium text-sm mb-2">Required Service Account Permissions</p>
                        <p className="text-amber-100/80 text-sm mb-3">
                            Your service account needs these IAM roles. Add them at{' '}
                            <a
                                href="https://console.cloud.google.com/iam-admin/iam"
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-amber-300 underline hover:text-amber-200"
                            >
                                GCP Console → IAM & Admin
                            </a>
                        </p>
                        <ul className="text-amber-100 text-sm space-y-1">
                            <li className="flex items-center">
                                <Check className="w-4 h-4 mr-2 text-amber-400" />
                                <code className="bg-black/20 px-1.5 py-0.5 rounded text-xs">Cloud KMS Admin</code>
                                <span className="text-amber-200/70 ml-2">— creates encryption keys</span>
                            </li>
                            <li className="flex items-center">
                                <Check className="w-4 h-4 mr-2 text-amber-400" />
                                <code className="bg-black/20 px-1.5 py-0.5 rounded text-xs">Secret Manager Admin</code>
                                <span className="text-amber-200/70 ml-2">— manages secrets</span>
                            </li>
                            <li className="flex items-center">
                                <Check className="w-4 h-4 mr-2 text-amber-400" />
                                <code className="bg-black/20 px-1.5 py-0.5 rounded text-xs">Cloud Translation API User</code>
                                <span className="text-amber-200/70 ml-2">— multi-language support</span>
                            </li>
                            <li className="flex items-center">
                                <Check className="w-4 h-4 mr-2 text-amber-400" />
                                <code className="bg-black/20 px-1.5 py-0.5 rounded text-xs">Vertex AI User</code>
                                <span className="text-amber-200/70 ml-2">— AI analysis features</span>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>

            <div className="space-y-5 mb-8">
                <div>
                    <label className="block text-sm font-medium text-white/80 mb-3">
                        GCP Project ID
                    </label>
                    <input
                        type="text"
                        value={form.project_id}
                        onChange={(e) => setForm({ ...form, project_id: e.target.value })}
                        placeholder="my-gcp-project-123"
                        className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white placeholder-white/40 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                </div>

                <div>
                    <label className="block text-sm font-medium text-white/80 mb-2">
                        Service Account JSON Key
                    </label>
                    <div className="relative">
                        <input
                            type="file"
                            accept=".json"
                            onChange={handleFileUpload}
                            className="hidden"
                            id="sa-file-upload"
                        />
                        <label
                            htmlFor="sa-file-upload"
                            className={`w-full px-4 py-8 rounded-lg border-2 border-dashed cursor-pointer flex flex-col items-center justify-center transition-colors ${fileUploaded ? 'bg-green-500/20 border-green-400/50' : 'bg-white/5 border-white/20 hover:border-indigo-400/50'
                                }`}
                        >
                            {fileUploaded ? (
                                <>
                                    <Check className="w-8 h-8 text-green-400 mb-2" />
                                    <span className="text-green-300 font-medium">Service Account Uploaded</span>
                                    <span className="text-green-400/60 text-sm mt-1">Project: {form.project_id}</span>
                                </>
                            ) : (
                                <>
                                    <Upload className="w-8 h-8 text-white/40 mb-2" />
                                    <span className="text-white/70">Drop your service account JSON here</span>
                                    <span className="text-white/40 text-sm mt-1">or click to browse</span>
                                </>
                            )}
                        </label>
                    </div>
                </div>
            </div>

            <div className="bg-white/5 border border-white/10 rounded-xl p-4 mb-8">
                <p className="text-sm font-medium text-white/70 mb-2">Need a service account?</p>
                <a
                    href="https://console.cloud.google.com/iam-admin/serviceaccounts"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-indigo-300 hover:text-indigo-200 flex items-center"
                >
                    <ExternalLink className="w-4 h-4 mr-2" />
                    Google Cloud Console → IAM → Service Accounts
                </a>
            </div>

            <div className="flex gap-4 pt-2">
                <button
                    onClick={onSkip}
                    className="flex-1 bg-white/10 hover:bg-white/15 border border-white/20 text-white font-medium py-3.5 px-6 rounded-xl transition-all"
                >
                    Skip for Now
                </button>
                <button
                    onClick={onSubmit}
                    disabled={loading || !form.project_id || !form.service_account_json}
                    className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-white/10 disabled:text-white/60 disabled:cursor-not-allowed text-white font-semibold py-3.5 px-6 rounded-xl transition-all shadow-lg shadow-indigo-500/25 disabled:shadow-none flex items-center justify-center"
                >
                    {loading ? (
                        <>
                            <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                            Configuring...
                        </>
                    ) : (
                        'Configure GCP'
                    )}
                </button>
            </div>
        </div>
    );
}

// Auth0 Setup Form
interface Auth0SetupFormProps {
    form: any;
    setForm: (form: any) => void;
    onSubmit: () => void;
    loading: boolean;
    success: boolean;
    gcpConfigured: boolean;
}

function Auth0SetupForm({ form, setForm, onSubmit, loading, success, gcpConfigured }: Auth0SetupFormProps) {
    const [showGuide, setShowGuide] = useState(true);
    const [expandedStep, setExpandedStep] = useState<number | null>(1);

    const callbackUrl = typeof window !== 'undefined' ? `${window.location.origin}/auth/callback` : form.callback_url;

    const setupSteps = [
        {
            num: 1,
            title: "Create Auth0 Account & Tenant",
            content: (
                <div className="space-y-3 text-sm text-white/70">
                    <p>1. Go to <a href="https://auth0.com/signup" target="_blank" rel="noopener noreferrer" className="text-indigo-400 hover:text-indigo-300 inline-flex items-center">auth0.com/signup <ExternalLink className="w-3 h-3 ml-1" /></a></p>
                    <p>2. Sign up with your email or SSO provider</p>
                    <p>3. Choose a <strong className="text-white">tenant name</strong> (e.g., "pinpoint311" or your org name)</p>
                    <p>4. Select your <strong className="text-white">region</strong> (US, EU, or AU)</p>
                    <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 mt-2">
                        <p className="text-blue-300 text-xs">💡 Your tenant domain will be: <code className="bg-white/10 px-1 rounded">tenant-name.region.auth0.com</code></p>
                    </div>
                </div>
            )
        },
        {
            num: 2,
            title: "Create Application",
            content: (
                <div className="space-y-3 text-sm text-white/70">
                    <p>1. In Auth0 Dashboard, go to <strong className="text-white">Applications → Applications</strong></p>
                    <p>2. Click <strong className="text-white">"+ Create Application"</strong></p>
                    <p>3. Enter name: <code className="bg-white/10 px-2 py-0.5 rounded text-white">Pinpoint 311</code></p>
                    <p>4. Select <strong className="text-white">"Regular Web Application"</strong></p>
                    <p>5. Click <strong className="text-white">Create</strong></p>
                </div>
            )
        },
        {
            num: 3,
            title: "Configure Callback URLs",
            content: (
                <div className="space-y-3 text-sm text-white/70">
                    <p>1. In your new app, go to the <strong className="text-white">Settings</strong> tab</p>
                    <p>2. Scroll to <strong className="text-white">"Allowed Callback URLs"</strong></p>
                    <p>3. Add this URL (your current location):</p>
                    <div className="bg-white/10 rounded-lg p-3 flex items-center justify-between">
                        <code className="text-green-400 text-xs break-all">{callbackUrl}</code>
                        <button
                            onClick={() => navigator.clipboard.writeText(callbackUrl)}
                            className="ml-2 px-2 py-1 bg-white/10 hover:bg-white/20 rounded text-xs text-white/70 flex-shrink-0"
                        >
                            Copy
                        </button>
                    </div>
                    <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 mt-2">
                        <p className="text-blue-300 text-xs">💡 <strong>Tip:</strong> If you have a custom domain (e.g., <code className="bg-white/10 px-1 rounded">311.yourorg.gov</code>), also add:</p>
                        <code className="text-blue-200 text-xs block mt-1">https://your-domain.gov/auth/callback</code>
                        <p className="text-blue-300/70 text-xs mt-1">You can add multiple URLs separated by commas.</p>
                    </div>
                    <p>4. Scroll to <strong className="text-white">"Allowed Logout URLs"</strong> and add: <code className="bg-white/10 px-1 rounded">{typeof window !== 'undefined' ? window.location.origin : ''}</code></p>
                    <p>5. Click <strong className="text-white">Save Changes</strong></p>
                </div>
            )
        },
        {
            num: 4,
            title: "Enable Management API (Optional - For Branding)",
            content: (
                <div className="space-y-3 text-sm text-white/70">
                    <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-3 mb-3">
                        <p className="text-blue-300 text-xs">💡 This step enables automatic branding configuration on your Auth0 login page</p>
                    </div>
                    <p>1. Go to <strong className="text-white">Applications → APIs</strong></p>
                    <p>2. Click on <strong className="text-white">"Auth0 Management API"</strong></p>
                    <p>3. Go to the <strong className="text-white">"Machine to Machine Applications"</strong> tab</p>
                    <p>4. Find <strong className="text-white">"Pinpoint 311"</strong> and toggle it <strong className="text-green-400">ON</strong></p>
                    <p>5. Click the <strong className="text-white">dropdown arrow</strong> to expand permissions</p>
                    <p>6. Select these scopes:</p>
                    <div className="bg-white/5 rounded-lg p-3 space-y-1">
                        <code className="block text-purple-400 text-xs">✓ read:branding</code>
                        <code className="block text-purple-400 text-xs">✓ update:branding</code>
                    </div>
                    <p>7. Click <strong className="text-white">Update</strong></p>
                </div>
            )
        },
        {
            num: 5,
            title: "Copy Credentials",
            content: (
                <div className="space-y-3 text-sm text-white/70">
                    <p>1. Go back to <strong className="text-white">Applications → Applications</strong></p>
                    <p>2. Click on <strong className="text-white">"Pinpoint 311"</strong></p>
                    <p>3. In the <strong className="text-white">Settings</strong> tab, copy:</p>
                    <div className="bg-white/5 rounded-lg p-3 space-y-2">
                        <p><strong className="text-white">Domain:</strong> <span className="text-white/50">e.g., yourorg.us.auth0.com</span></p>
                        <p><strong className="text-white">Client ID:</strong> <span className="text-white/50">e.g., abc123xyz...</span></p>
                        <p><strong className="text-white">Client Secret:</strong> <span className="text-white/50">Click "Reveal" first</span></p>
                    </div>
                    <p>4. Paste them into the fields below ↓</p>
                </div>
            )
        }
    ];

    if (success) {
        return (
            <div className="text-center py-12">
                <div className="inline-flex items-center justify-center w-16 h-16 bg-green-500/30 rounded-full mb-4">
                    <Check className="w-8 h-8 text-green-400" />
                </div>
                <h2 className="text-2xl font-bold text-white mb-2">Auth0 Configured!</h2>
                <p className="text-white/60">Your Auth0 application has been created and configured.</p>
            </div>
        );
    }

    return (
        <div>
            <div className="mb-6">
                <h2 className="text-2xl font-bold text-white mb-2 flex items-center">
                    <Shield className="w-7 h-7 text-orange-400 mr-3" />
                    Configure Auth0 SSO
                </h2>
                <p className="text-white/60">
                    Set up enterprise Single Sign-On with MFA and passkeys.
                </p>
            </div>

            {/* Expandable Setup Guide */}
            <div className="mb-6">
                <button
                    onClick={() => setShowGuide(!showGuide)}
                    className="w-full flex items-center justify-between text-left bg-gradient-to-r from-indigo-500/20 to-purple-500/20 hover:from-indigo-500/30 hover:to-purple-500/30 border border-indigo-500/30 rounded-xl p-4 transition-colors"
                >
                    <span className="flex items-center">
                        <Sparkles className="w-5 h-5 text-indigo-400 mr-2" />
                        <span className="font-medium text-white">New to Auth0? Complete Setup Guide</span>
                    </span>
                    <span className={`text-white/60 transition-transform ${showGuide ? 'rotate-180' : ''}`}>▼</span>
                </button>

                {showGuide && (
                    <div className="mt-3 bg-white/5 rounded-xl border border-white/10 overflow-hidden">
                        {setupSteps.map((step) => (
                            <div key={step.num} className="border-b border-white/10 last:border-b-0">
                                <button
                                    onClick={() => setExpandedStep(expandedStep === step.num ? null : step.num)}
                                    className="w-full flex items-center p-4 hover:bg-white/5 transition-colors"
                                >
                                    <span className={`w-7 h-7 rounded-full flex items-center justify-center text-sm font-medium mr-3 ${expandedStep === step.num ? 'bg-indigo-500 text-white' : 'bg-white/10 text-white/60'
                                        }`}>
                                        {step.num}
                                    </span>
                                    <span className="font-medium text-white">{step.title}</span>
                                    <span className={`ml-auto text-white/40 transition-transform ${expandedStep === step.num ? 'rotate-180' : ''}`}>
                                        ▼
                                    </span>
                                </button>
                                {expandedStep === step.num && (
                                    <div className="px-4 pb-4 pl-14">
                                        {step.content}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Storage Info */}
            <div className={`rounded-xl p-4 mb-6 ${gcpConfigured ? 'bg-green-500/20 border border-green-400/30' : 'bg-amber-500/20 border border-amber-400/30'}`}>
                <div className="flex items-start space-x-3">
                    <Lock className={`w-5 h-5 flex-shrink-0 mt-0.5 ${gcpConfigured ? 'text-green-400' : 'text-amber-400'}`} />
                    <div>
                        <p className={`font-medium text-sm ${gcpConfigured ? 'text-green-200' : 'text-amber-200'}`}>
                            {gcpConfigured ? 'Credentials stored in Secret Manager' : 'Local Encrypted Storage'}
                        </p>
                        <p className={`text-sm mt-1 ${gcpConfigured ? 'text-green-300/80' : 'text-amber-300/80'}`}>
                            {gcpConfigured
                                ? 'Your credentials will be securely stored in Google Cloud Secret Manager with full audit logging.'
                                : 'GCP not configured. Credentials will be stored locally with Fernet encryption.'
                            }
                        </p>
                    </div>
                </div>
            </div>

            <div className="space-y-4 mb-6">
                <div>
                    <label className="block text-sm font-medium text-white/80 mb-2">
                        Auth0 Domain
                    </label>
                    <input
                        type="text"
                        value={form.domain}
                        onChange={(e) => setForm({ ...form, domain: e.target.value })}
                        placeholder="yourorg.us.auth0.com"
                        className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white placeholder-white/40 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                    <p className="text-xs text-white/40 mt-1">Your Auth0 tenant domain</p>
                </div>

                <div>
                    <label className="block text-sm font-medium text-white/80 mb-2">
                        Client ID
                    </label>
                    <input
                        type="text"
                        value={form.client_id}
                        onChange={(e) => setForm({ ...form, client_id: e.target.value })}
                        placeholder="Enter client ID"
                        className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white placeholder-white/40 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                </div>

                <div>
                    <label className="block text-sm font-medium text-white/80 mb-2">
                        Client Secret
                    </label>
                    <input
                        type="password"
                        value={form.client_secret}
                        onChange={(e) => setForm({ ...form, client_secret: e.target.value })}
                        placeholder="Enter client secret"
                        className="w-full px-4 py-3 rounded-lg bg-white/10 border border-white/20 text-white placeholder-white/40 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                </div>

                <div>
                    <label className="block text-sm font-medium text-white/80 mb-2">
                        Callback URL
                    </label>
                    <input
                        type="text"
                        value={form.callback_url}
                        className="w-full px-4 py-3 rounded-lg bg-white/5 border border-white/10 text-white/60"
                        readOnly
                    />
                    <p className="text-xs text-white/40 mt-1">Add this URL to your Auth0 application's allowed callbacks</p>
                </div>
            </div>

            <div className="bg-white/5 rounded-xl p-4 mb-6">
                <p className="text-sm font-medium text-white/70 mb-2">Need help?</p>
                <a
                    href="https://auth0.com/docs/get-started/auth0-overview/create-applications"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-indigo-400 hover:text-indigo-300 flex items-center"
                >
                    <ExternalLink className="w-4 h-4 mr-1" />
                    Auth0 Application Setup Guide
                </a>
            </div>

            <button
                onClick={onSubmit}
                disabled={loading || !form.domain || !form.client_id || !form.client_secret}
                className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-white/10 disabled:cursor-not-allowed text-white font-medium py-3 px-6 rounded-lg transition-colors flex items-center justify-center"
            >
                {loading ? (
                    <>
                        <Loader2 className="w-5 h-5 mr-2 animate-spin" />
                        Configuring Auth0...
                    </>
                ) : (
                    'Configure Auth0'
                )}
            </button>
        </div>
    );
}

// Completion Screen
interface CompletionScreenProps {
    status: SetupStatus | null;
    onReconfigureGCP?: () => void;
    onReconfigureAuth0?: () => void;
}

function CompletionScreen({ status, onReconfigureGCP, onReconfigureAuth0 }: CompletionScreenProps) {
    const [migrating, setMigrating] = useState(false);
    const [migrationResult, setMigrationResult] = useState<{
        status: string;
        migrated: number;
        scrubbed: number;
        failed: number;
        error?: string;
        reason?: string;
    } | null>(null);

    const handleMigration = async () => {
        try {
            setMigrating(true);
            setMigrationResult(null);
            const result = await api.migrateToSecretManager();
            setMigrationResult(result);
        } catch (err: any) {
            setMigrationResult({
                status: 'error',
                migrated: 0,
                scrubbed: 0,
                failed: 0,
                error: err.message || 'Migration failed'
            });
        } finally {
            setMigrating(false);
        }
    };

    return (
        <div className="text-center py-12">
            <div className="inline-flex items-center justify-center w-20 h-20 bg-green-500/30 rounded-full mb-6">
                <Check className="w-10 h-10 text-green-400" />
            </div>
            <h2 className="text-3xl font-bold text-white mb-3">Setup Complete!</h2>
            <p className="text-lg text-white/60 mb-8">
                Your system is fully configured and ready to use.
            </p>

            <div className="grid grid-cols-2 gap-4 max-w-md mx-auto mb-8">
                <button
                    onClick={onReconfigureGCP}
                    className={`${status?.gcp_configured ? 'bg-green-500/20 border-green-400/30 hover:bg-green-500/30' : 'bg-white/10 border-white/20 hover:bg-white/20'} border rounded-lg p-4 transition-all cursor-pointer`}
                >
                    <Cloud className={`w-8 h-8 ${status?.gcp_configured ? 'text-green-400' : 'text-white/40'} mx-auto mb-2`} />
                    <p className={`text-sm font-medium ${status?.gcp_configured ? 'text-green-200' : 'text-white/60'}`}>Google Cloud</p>
                    <p className={`text-xs ${status?.gcp_configured ? 'text-green-400' : 'text-white/40'}`}>
                        {status?.gcp_configured ? 'Configured' : 'Skipped'}
                    </p>
                    <p className="text-xs text-indigo-300 mt-2 flex items-center justify-center">
                        <RefreshCw className="w-3 h-3 mr-1" /> Reconfigure
                    </p>
                </button>
                <button
                    onClick={onReconfigureAuth0}
                    className={`${status?.auth0_configured ? 'bg-green-500/20 border-green-400/30 hover:bg-green-500/30' : 'bg-white/10 border-white/20 hover:bg-white/20'} border rounded-lg p-4 transition-all cursor-pointer`}
                >
                    <Shield className={`w-8 h-8 ${status?.auth0_configured ? 'text-green-400' : 'text-white/40'} mx-auto mb-2`} />
                    <p className={`text-sm font-medium ${status?.auth0_configured ? 'text-green-200' : 'text-white/60'}`}>Auth0 SSO</p>
                    <p className={`text-xs ${status?.auth0_configured ? 'text-green-400' : 'text-white/40'}`}>
                        {status?.auth0_configured ? 'Configured' : 'Not Configured'}
                    </p>
                    <p className="text-xs text-indigo-300 mt-2 flex items-center justify-center">
                        <RefreshCw className="w-3 h-3 mr-1" /> Reconfigure
                    </p>
                </button>
            </div>

            {/* Secret Manager Migration Section */}
            {status?.gcp_configured && (
                <div className="max-w-md mx-auto mb-8">
                    <div className="bg-indigo-500/20 border border-indigo-400/30 rounded-xl p-4">
                        <div className="flex items-center justify-center mb-3">
                            <Database className="w-5 h-5 text-indigo-400 mr-2" />
                            <span className="text-indigo-200 font-medium">Migrate Secrets to Google Cloud</span>
                        </div>
                        <p className="text-sm text-indigo-300/70 mb-4">
                            Move all secrets from the database to Google Secret Manager for enterprise-grade security.
                            Secrets will be scrubbed from the database after migration.
                        </p>

                        {migrationResult && (
                            <div className={`mb-4 p-3 rounded-lg text-sm ${migrationResult.status === 'success'
                                ? 'bg-green-500/20 border border-green-400/30'
                                : migrationResult.status === 'skipped'
                                    ? 'bg-amber-500/20 border border-amber-400/30'
                                    : 'bg-red-500/20 border border-red-400/30'
                                }`}>
                                {migrationResult.status === 'success' ? (
                                    <div className="text-green-200">
                                        <Check className="w-4 h-4 inline mr-1" />
                                        Migrated {migrationResult.migrated} secrets, scrubbed {migrationResult.scrubbed} from database
                                        {migrationResult.failed > 0 && (
                                            <span className="text-amber-300"> ({migrationResult.failed} failed)</span>
                                        )}
                                    </div>
                                ) : migrationResult.status === 'skipped' ? (
                                    <div className="text-amber-200">
                                        {migrationResult.reason || 'Migration skipped'}
                                    </div>
                                ) : (
                                    <div className="text-red-200">
                                        <AlertCircle className="w-4 h-4 inline mr-1" />
                                        {migrationResult.error || 'Migration failed'}
                                    </div>
                                )}
                            </div>
                        )}

                        <button
                            onClick={handleMigration}
                            disabled={migrating}
                            className="w-full bg-indigo-600 hover:bg-indigo-500 disabled:bg-indigo-600/50 text-white font-medium py-2.5 px-4 rounded-lg transition-all flex items-center justify-center"
                        >
                            {migrating ? (
                                <>
                                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                                    Migrating...
                                </>
                            ) : (
                                <>
                                    <Database className="w-4 h-4 mr-2" />
                                    Migrate to Secret Manager
                                </>
                            )}
                        </button>
                    </div>
                </div>
            )}

            <a
                href="/admin"
                className="inline-flex items-center bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-3 px-8 rounded-lg transition-colors"
            >
                Go to Admin Console
            </a>
        </div>
    );
}

