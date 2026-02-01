import { useState, useEffect } from 'react';
import { Shield, Trash2, CheckCircle, AlertTriangle, Loader2, Key, Lock, Unlock } from 'lucide-react';
import { Card, Button, Badge } from './ui';
import api, { FederationStatus } from '../services/api';

export default function FederationCard() {
    const [status, setStatus] = useState<FederationStatus | null>(null);
    const [loading, setLoading] = useState(true);
    const [actionLoading, setActionLoading] = useState(false);
    const [showConfirmation, setShowConfirmation] = useState(false);
    const [confirmText, setConfirmText] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [success, setSuccess] = useState<string | null>(null);

    const fetchStatus = async () => {
        try {
            setLoading(true);
            const data = await api.getFederationStatus();
            setStatus(data);
        } catch (err) {
            console.error('Failed to fetch federation status:', err);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchStatus();
    }, []);

    const handleDeleteKey = async () => {
        if (confirmText !== 'DELETE') return;

        setActionLoading(true);
        setError(null);
        setSuccess(null);

        try {
            const result = await api.completeFederation();
            if (result.status === 'success' || result.federation_active) {
                setSuccess('Bootstrap key deleted! All future GCP access uses Auth0 federation.');
                setShowConfirmation(false);
                setConfirmText('');
                fetchStatus();
            } else {
                setError(result.error || 'Failed to delete key');
            }
        } catch (err: any) {
            setError(err.message || 'Failed to delete bootstrap key');
        } finally {
            setActionLoading(false);
        }
    };

    const handleTestFederation = async () => {
        setActionLoading(true);
        setError(null);
        setSuccess(null);

        try {
            const result = await api.testFederation();
            if (result.status === 'success') {
                setSuccess('Federation test passed! You can now safely delete the bootstrap key.');
            } else {
                setError(result.error || 'Federation test failed');
            }
        } catch (err: any) {
            setError(err.message || 'Federation test failed');
        } finally {
            setActionLoading(false);
        }
    };

    const handleSetupFederation = async () => {
        setActionLoading(true);
        setError(null);
        setSuccess(null);

        try {
            const result = await api.setupFederation();
            if (result.status === 'success') {
                setSuccess('Workload Identity Federation configured! You can now test it or delete the bootstrap key.');
                fetchStatus();
            } else {
                setError(result.error || 'Federation setup failed');
            }
        } catch (err: any) {
            setError(err.message || 'Federation setup failed');
        } finally {
            setActionLoading(false);
        }
    };

    if (loading) {
        return (
            <Card className="bg-gradient-to-br from-slate-800/50 to-slate-900/50 border-slate-700/50">
                <div className="flex items-center justify-center py-8">
                    <Loader2 className="w-6 h-6 text-white/50 animate-spin" />
                </div>
            </Card>
        );
    }

    // Only show if GCP is configured (bootstrap key present or federation active)
    if (!status?.bootstrap_key_present && !status?.federation_available) {
        return null;
    }

    return (
        <Card className="bg-gradient-to-br from-emerald-900/30 to-teal-900/30 border-emerald-500/30">
            <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-lg bg-emerald-500/20 flex items-center justify-center">
                        <Shield className="w-5 h-5 text-emerald-400" />
                    </div>
                    <div>
                        <h3 className="font-semibold text-white">Workload Identity Federation</h3>
                        <p className="text-gray-300 text-xs">Keyless GCP authentication via Auth0</p>
                    </div>
                </div>
                {status?.federation_available ? (
                    <Badge variant="success">Active</Badge>
                ) : status?.bootstrap_key_present ? (
                    <Badge variant="warning">Key Present</Badge>
                ) : (
                    <Badge variant="default">Not Configured</Badge>
                )}
            </div>

            {/* Status Details */}
            <div className="space-y-3 mb-4">
                <div className="flex items-center gap-2 text-sm">
                    {status?.federation_available ? (
                        <>
                            <Lock className="w-4 h-4 text-emerald-400" />
                            <span className="text-emerald-300">Federation active — using Auth0 for GCP access</span>
                        </>
                    ) : (
                        <>
                            <Unlock className="w-4 h-4 text-amber-400" />
                            <span className="text-amber-300">Service account key stored in database</span>
                        </>
                    )}
                </div>

                {status?.bootstrap_key_present && status?.federation_available && (
                    <div className="flex items-center gap-2 text-sm">
                        <Key className="w-4 h-4 text-amber-400" />
                        <span className="text-amber-300">Bootstrap key can be deleted for maximum security</span>
                    </div>
                )}
            </div>

            {/* Error/Success Messages */}
            {error && (
                <div className="mb-4 p-3 rounded-lg bg-red-500/20 border border-red-500/30 text-red-300 text-sm flex items-start gap-2">
                    <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                    <span>{error}</span>
                </div>
            )}

            {success && (
                <div className="mb-4 p-3 rounded-lg bg-emerald-500/20 border border-emerald-500/30 text-emerald-300 text-sm flex items-start gap-2">
                    <CheckCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
                    <span>{success}</span>
                </div>
            )}

            {/* Actions */}
            {status?.bootstrap_key_present && (
                <div className="space-y-3">
                    {status?.federation_available ? (
                        <>
                            {!showConfirmation ? (
                                <div className="flex gap-2">
                                    <Button
                                        size="sm"
                                        variant="secondary"
                                        onClick={handleTestFederation}
                                        disabled={actionLoading}
                                    >
                                        {actionLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                                        <span className="ml-2">Test Federation</span>
                                    </Button>
                                    <Button
                                        size="sm"
                                        variant="danger"
                                        onClick={() => setShowConfirmation(true)}
                                        disabled={actionLoading}
                                    >
                                        <Trash2 className="w-4 h-4" />
                                        <span className="ml-2">Delete Bootstrap Key</span>
                                    </Button>
                                </div>
                            ) : (
                                <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/30 space-y-3">
                                    <div className="flex items-start gap-2">
                                        <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
                                        <div>
                                            <p className="text-red-300 font-semibold">This action is irreversible!</p>
                                            <p className="text-red-300/70 text-sm mt-1">
                                                The service account key will be permanently deleted from the database.
                                                All future GCP access will use Auth0 federation.
                                            </p>
                                        </div>
                                    </div>
                                    <div>
                                        <label className="text-sm text-red-300/70 block mb-1">
                                            Type <strong>DELETE</strong> to confirm:
                                        </label>
                                        <input
                                            type="text"
                                            value={confirmText}
                                            onChange={(e) => setConfirmText(e.target.value)}
                                            className="w-full px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-white text-sm focus:outline-none focus:ring-2 focus:ring-red-500/50"
                                            placeholder="DELETE"
                                        />
                                    </div>
                                    <div className="flex gap-2">
                                        <Button
                                            size="sm"
                                            variant="ghost"
                                            onClick={() => {
                                                setShowConfirmation(false);
                                                setConfirmText('');
                                            }}
                                            disabled={actionLoading}
                                        >
                                            Cancel
                                        </Button>
                                        <Button
                                            size="sm"
                                            variant="danger"
                                            onClick={handleDeleteKey}
                                            disabled={confirmText !== 'DELETE' || actionLoading}
                                        >
                                            {actionLoading ? (
                                                <Loader2 className="w-4 h-4 animate-spin" />
                                            ) : (
                                                <Trash2 className="w-4 h-4" />
                                            )}
                                            <span className="ml-2">Permanently Delete Key</span>
                                        </Button>
                                    </div>
                                </div>
                            )}
                        </>
                    ) : status?.can_setup ? (
                        <div className="space-y-2">
                            <p className="text-amber-300 text-sm">
                                GCP and Auth0 are configured. Click below to enable keyless authentication.
                            </p>
                            <Button
                                size="sm"
                                variant="primary"
                                onClick={handleSetupFederation}
                                disabled={actionLoading}
                            >
                                {actionLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Shield className="w-4 h-4" />}
                                <span className="ml-2">Setup Workload Identity Federation</span>
                            </Button>
                        </div>
                    ) : (
                        <p className="text-gray-400 text-sm">
                            Configure Auth0 in the Setup Wizard to enable federation.
                        </p>
                    )}
                </div>
            )}

            {/* Federation already complete without key */}
            {!status?.bootstrap_key_present && status?.federation_available && (
                <div className="flex items-center gap-2 text-emerald-300 text-sm">
                    <CheckCircle className="w-4 h-4" />
                    <span>Bootstrap key deleted — maximum security achieved!</span>
                </div>
            )}
        </Card>
    );
}
