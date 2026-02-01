import React, { useState, useEffect } from 'react';
import { Shield, Cloud, Check, AlertCircle, Loader2, ExternalLink, Lock, Upload, Database, Key, Sparkles } from 'lucide-react';
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
                        <CompletionScreen status={status} />
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
}

function GCPSetupForm({ form, setForm, onSubmit, onSkip, loading, success }: GCPSetupFormProps) {
    const [fileUploaded, setFileUploaded] = useState(false);

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

    if (success) {
        return (
            <div className="text-center py-12">
                <div className="inline-flex items-center justify-center w-16 h-16 bg-green-500/30 rounded-full mb-4">
                    <Check className="w-8 h-8 text-green-400" />
                </div>
                <h2 className="text-2xl font-bold text-white mb-2">Google Cloud Configured!</h2>
                <p className="text-white/60">Secret Manager and APIs have been set up.</p>
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
                        <p className="text-blue-300/80 text-sm mt-1">
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
                            <p className="text-white/50 text-xs">{desc}</p>
                        </div>
                    </div>
                ))}
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
                    className="text-sm text-indigo-400 hover:text-indigo-300 flex items-center"
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
                    className="flex-1 bg-indigo-600 hover:bg-indigo-500 disabled:bg-white/10 disabled:text-white/40 disabled:cursor-not-allowed text-white font-semibold py-3.5 px-6 rounded-xl transition-all shadow-lg shadow-indigo-500/25 disabled:shadow-none flex items-center justify-center"
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
                    Provide your Auth0 credentials for Single Sign-On with MFA and passkeys.
                </p>
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
}

function CompletionScreen({ status }: CompletionScreenProps) {
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
                <div className={`${status?.gcp_configured ? 'bg-green-500/20 border-green-400/30' : 'bg-white/10 border-white/20'} border rounded-lg p-4`}>
                    <Cloud className={`w-8 h-8 ${status?.gcp_configured ? 'text-green-400' : 'text-white/40'} mx-auto mb-2`} />
                    <p className={`text-sm font-medium ${status?.gcp_configured ? 'text-green-200' : 'text-white/60'}`}>Google Cloud</p>
                    <p className={`text-xs ${status?.gcp_configured ? 'text-green-400' : 'text-white/40'}`}>
                        {status?.gcp_configured ? 'Configured' : 'Skipped'}
                    </p>
                </div>
                <div className={`${status?.auth0_configured ? 'bg-green-500/20 border-green-400/30' : 'bg-white/10 border-white/20'} border rounded-lg p-4`}>
                    <Shield className={`w-8 h-8 ${status?.auth0_configured ? 'text-green-400' : 'text-white/40'} mx-auto mb-2`} />
                    <p className={`text-sm font-medium ${status?.auth0_configured ? 'text-green-200' : 'text-white/60'}`}>Auth0 SSO</p>
                    <p className={`text-xs ${status?.auth0_configured ? 'text-green-400' : 'text-white/40'}`}>
                        {status?.auth0_configured ? 'Configured' : 'Not Configured'}
                    </p>
                </div>
            </div>

            <a
                href="/admin"
                className="inline-flex items-center bg-indigo-600 hover:bg-indigo-700 text-white font-medium py-3 px-8 rounded-lg transition-colors"
            >
                Go to Admin Console
            </a>
        </div>
    );
}
