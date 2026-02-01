import React, { useState, useEffect } from 'react';
import { Shield, Cloud, Check, AlertCircle, Loader2, ExternalLink, Lock } from 'lucide-react';
import { api } from '../services/api';

interface SetupStatus {
    auth0_configured: boolean;
    gcp_configured: boolean;
    auth0_details?: any;
    gcp_details?: any;
}

export function SetupWizard() {
    const [currentStep, setCurrentStep] = useState<'check' | 'auth0' | 'gcp' | 'complete'>('check');
    const [status, setStatus] = useState<SetupStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    // Auth0 form state
    const [auth0Form, setAuth0Form] = useState({
        domain: '',
        management_client_id: '',
        management_client_secret: '',
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

            // Determine which step to show
            if (response.auth0_configured && response.gcp_configured) {
                setCurrentStep('complete');
            } else if (!response.auth0_configured) {
                setCurrentStep('auth0');
            } else if (!response.gcp_configured) {
                setCurrentStep('gcp');
            }
        } catch (err: any) {
            setError(err.response?.detail || 'Failed to check setup status');
        } finally {
            setLoading(false);
        }
    };

    const configureAuth0 = async () => {
        try {
            setAuth0Loading(true);
            setError(null);

            await api.configureAuth0(auth0Form);

            setAuth0Success(true);
            setTimeout(() => {
                checkStatus(); // Refresh status
            }, 2000);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Failed to configure Auth0');
        } finally {
            setAuth0Loading(false);
        }
    };

    if (loading) {
        return (
            <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-purple-50 flex items-center justify-center">
                <div className="text-center">
                    <Loader2 className="w-12 h-12 text-indigo-600 animate-spin mx-auto mb-4" />
                    <p className="text-gray-600">Checking system status...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-purple-50 py-12 px-4">
            <div className="max-w-4xl mx-auto">
                {/* Header */}
                <div className="text-center mb-12">
                    <div className="inline-flex items-center justify-center w-16 h-16 bg-indigo-600 rounded-2xl mb-4">
                        <Shield className="w-8 h-8 text-white" />
                    </div>
                    <h1 className="text-4xl font-bold text-gray-900 mb-2">Automated Setup Wizard</h1>
                    <p className="text-lg text-gray-600">Configure Auth0 and Google Cloud in minutes</p>
                </div>

                {/* Progress Steps */}
                <div className="mb-12">
                    <div className="flex items-center justify-center space-x-4">
                        <StepIndicator
                            step={1}
                            label="Auth0"
                            active={currentStep === 'auth0'}
                            completed={status?.auth0_configured || false}
                            icon={Shield}
                        />
                        <div className="w-16 h-1 bg-gray-200 rounded-full">
                            <div className={`h-full bg-indigo-600 rounded-full transition-all ${status?.auth0_configured ? 'w-full' : 'w-0'}`} />
                        </div>
                        <StepIndicator
                            step={2}
                            label="Google Cloud"
                            active={currentStep === 'gcp'}
                            completed={status?.gcp_configured || false}
                            icon={Cloud}
                        />
                        <div className="w-16 h-1 bg-gray-200 rounded-full">
                            <div className={`h-full bg-indigo-600 rounded-full transition-all ${status?.gcp_configured ? 'w-full' : 'w-0'}`} />
                        </div>
                        <StepIndicator
                            step={3}
                            label="Complete"
                            active={currentStep === 'complete'}
                            completed={currentStep === 'complete'}
                            icon={Check}
                        />
                    </div>
                </div>

                {/* Error Display */}
                {error && (
                    <div className="mb-6 bg-red-50 border border-red-200 rounded-xl p-4 flex items-start space-x-3">
                        <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                        <div>
                            <p className="text-red-800 font-medium">Configuration Error</p>
                            <p className="text-red-700 text-sm mt-1">{error}</p>
                        </div>
                    </div>
                )}

                {/* Step Content */}
                <div className="bg-white rounded-2xl shadow-xl border border-gray-100 p-8">
                    {currentStep === 'auth0' && (
                        <Auth0SetupForm
                            form={auth0Form}
                            setForm={setAuth0Form}
                            onSubmit={configureAuth0}
                            loading={auth0Loading}
                            success={auth0Success}
                        />
                    )}

                    {currentStep === 'gcp' && (
                        <GCPSetupForm />
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
    step: number;
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
        ${completed ? 'bg-green-500 text-white' : active ? 'bg-indigo-600 text-white' : 'bg-gray-200 text-gray-500'}
      `}>
                {completed ? <Check className="w-6 h-6" /> : <Icon className="w-6 h-6" />}
            </div>
            <p className={`mt-2 text-sm font-medium ${active ? 'text-indigo-600' : completed ? 'text-green-600' : 'text-gray-500'}`}>
                {label}
            </p>
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
}

function Auth0SetupForm({ form, setForm, onSubmit, loading, success }: Auth0SetupFormProps) {
    if (success) {
        return (
            <div className="text-center py-12">
                <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
                    <Check className="w-8 h-8 text-green-600" />
                </div>
                <h2 className="text-2xl font-bold text-gray-900 mb-2">Auth0 Configured!</h2>
                <p className="text-gray-600">Your Auth0 application has been created and configured.</p>
            </div>
        );
    }

    return (
        <div>
            <div className="mb-6">
                <h2 className="text-2xl font-bold text-gray-900 mb-2 flex items-center">
                    <Shield className="w-7 h-7 text-indigo-600 mr-3" />
                    Configure Auth0 SSO
                </h2>
                <p className="text-gray-600">
                    Provide your Auth0 Management API credentials to automatically configure your tenant.
                </p>
            </div>

            <div className="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-6">
                <div className="flex items-start space-x-3">
                    <Lock className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                    <div>
                        <p className="text-blue-900 font-medium text-sm">Secure Configuration</p>
                        <p className="text-blue-800 text-sm mt-1">
                            All credentials are encrypted before storage and transmitted securely. This action is audited.
                        </p>
                    </div>
                </div>
            </div>

            <div className="space-y-4 mb-6">
                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Auth0 Domain
                    </label>
                    <input
                        type="text"
                        value={form.domain}
                        onChange={(e) => setForm({ ...form, domain: e.target.value })}
                        placeholder="yourorg.us.auth0.com"
                        className="w-full px-4 py-3 rounded-lg border border-gray-300 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                    <p className="text-xs text-gray-500 mt-1">Your Auth0 tenant domain</p>
                </div>

                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Management API Client ID
                    </label>
                    <input
                        type="text"
                        value={form.management_client_id}
                        onChange={(e) => setForm({ ...form, management_client_id: e.target.value })}
                        placeholder="Enter client ID"
                        className="w-full px-4 py-3 rounded-lg border border-gray-300 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                </div>

                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Management API Client Secret
                    </label>
                    <input
                        type="password"
                        value={form.management_client_secret}
                        onChange={(e) => setForm({ ...form, management_client_secret: e.target.value })}
                        placeholder="Enter client secret"
                        className="w-full px-4 py-3 rounded-lg border border-gray-300 focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                    />
                </div>

                <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                        Callback URL
                    </label>
                    <input
                        type="text"
                        value={form.callback_url}
                        onChange={(e) => setForm({ ...form, callback_url: e.target.value })}
                        className="w-full px-4 py-3 rounded-lg border border-gray-300 bg-gray-50"
                        readOnly
                    />
                    <p className="text-xs text-gray-500 mt-1">Automatically detected from your domain</p>
                </div>
            </div>

            <div className="bg-gray-50 rounded-xl p-4 mb-6">
                <p className="text-sm font-medium text-gray-700 mb-2">Need help finding these credentials?</p>
                <a
                    href="https://auth0.com/docs/get-started/auth0-overview/create-applications/machine-to-machine-apps"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm text-indigo-600 hover:text-indigo-700 flex items-center"
                >
                    <ExternalLink className="w-4 h-4 mr-1" />
                    Auth0 Management API Documentation
                </a>
            </div>

            <button
                onClick={onSubmit}
                disabled={loading || !form.domain || !form.management_client_id || !form.management_client_secret}
                className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white font-medium py-3 px-6 rounded-lg transition-colors flex items-center justify-center"
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

// GCP Setup Form (placeholder)
function GCPSetupForm() {
    return (
        <div className="text-center py-12">
            <Cloud className="w-16 h-16 text-gray-400 mx-auto mb-4" />
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Google Cloud Setup</h2>
            <p className="text-gray-600 mb-6">GCP configuration coming soon...</p>
            <button className="bg-gray-300 text-gray-700 font-medium py-3 px-6 rounded-lg cursor-not-allowed">
                Skip for Now
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
            <div className="inline-flex items-center justify-center w-20 h-20 bg-green-100 rounded-full mb-6">
                <Check className="w-10 h-10 text-green-600" />
            </div>
            <h2 className="text-3xl font-bold text-gray-900 mb-3">Setup Complete!</h2>
            <p className="text-lg text-gray-600 mb-8">
                Your system is fully configured and ready to use.
            </p>

            <div className="grid grid-cols-2 gap-4 max-w-md mx-auto mb-8">
                <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                    <Shield className="w-8 h-8 text-green-600 mx-auto mb-2" />
                    <p className="text-sm font-medium text-green-900">Auth0</p>
                    <p className="text-xs text-green-700">Configured</p>
                </div>
                <div className={`${status?.gcp_configured ? 'bg-green-50 border-green-200' : 'bg-gray-50 border-gray-200'} border rounded-lg p-4`}>
                    <Cloud className={`w-8 h-8 ${status?.gcp_configured ? 'text-green-600' : 'text-gray-400'} mx-auto mb-2`} />
                    <p className={`text-sm font-medium ${status?.gcp_configured ? 'text-green-900' : 'text-gray-600'}`}>Google Cloud</p>
                    <p className={`text-xs ${status?.gcp_configured ? 'text-green-700' : 'text-gray-500'}`}>
                        {status?.gcp_configured ? 'Configured' : 'Optional'}
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
