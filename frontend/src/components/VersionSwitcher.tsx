import { useState, useEffect } from 'react';
import {
    RefreshCw,
    ChevronDown,
    Check,
    X,
    Clock,
    ExternalLink,
    GitBranch,
    Shield,
    Package,
    AlertCircle,
    Loader2
} from 'lucide-react';

interface Release {
    tag: string;
    name: string;
    body: string;
    published_at: string;
    author: string | null;
    html_url: string;
    prerelease: boolean;
}

interface RecentCommit {
    sha: string;
    full_sha: string;
    message: string;
    date: string;
    author: string;
}

interface SecurityCheck {
    name: string;
    icon: string;
    status: string;
    conclusion: string | null;
    run_url: string | null;
    passed: boolean | null;
}

interface SecuritySummary {
    passed: number;
    total: number;
    all_passed: boolean;
    score: string;
}

export default function VersionSwitcher() {
    const [currentVersion, setCurrentVersion] = useState<{ sha: string; tag: string | null; display: string } | null>(null);
    const [releases, setReleases] = useState<Release[]>([]);
    const [recentCommits, setRecentCommits] = useState<RecentCommit[]>([]);
    const [selectedRef, setSelectedRef] = useState<string | null>(null);
    const [selectedRelease, setSelectedRelease] = useState<Release | null>(null);
    const [security, setSecurity] = useState<{ verification: Record<string, SecurityCheck>; summary: SecuritySummary } | null>(null);

    const [isLoading, setIsLoading] = useState(false);
    const [isLoadingSecurity, setIsLoadingSecurity] = useState(false);
    const [isSwitching, setIsSwitching] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [message, setMessage] = useState<string | null>(null);
    const [dropdownOpen, setDropdownOpen] = useState(false);

    const fetchCurrentVersion = async () => {
        try {
            const token = localStorage.getItem('token');
            const response = await fetch('/api/system/current-version', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (response.ok) {
                const data = await response.json();
                setCurrentVersion(data);
            }
        } catch (err) {
            console.error('Failed to fetch current version:', err);
        }
    };

    const fetchReleases = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const token = localStorage.getItem('token');
            const response = await fetch('/api/system/releases', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (response.ok) {
                const data = await response.json();
                setReleases(data.releases || []);
                setRecentCommits(data.recent_commits || []);
            } else {
                const errData = await response.json();
                setError(errData.detail || 'Failed to fetch releases');
            }
        } catch (err: any) {
            setError(err.message || 'Failed to fetch releases');
        } finally {
            setIsLoading(false);
        }
    };

    const fetchSecurity = async (ref: string) => {
        setIsLoadingSecurity(true);
        setSecurity(null);
        try {
            const token = localStorage.getItem('token');
            const response = await fetch(`/api/system/releases/${encodeURIComponent(ref)}/security`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (response.ok) {
                const data = await response.json();
                setSecurity(data);
            }
        } catch (err) {
            console.error('Failed to fetch security info:', err);
        } finally {
            setIsLoadingSecurity(false);
        }
    };

    const handleSelectRef = (ref: string, release: Release | null) => {
        setSelectedRef(ref);
        setSelectedRelease(release);
        setDropdownOpen(false);
        fetchSecurity(ref);
    };

    const handleSwitchVersion = async () => {
        if (!selectedRef) return;

        if (!confirm(`Switch to version ${selectedRef}? This may require a container restart.`)) {
            return;
        }

        setIsSwitching(true);
        setMessage(null);
        try {
            const token = localStorage.getItem('token');
            const response = await fetch(`/api/system/switch-version?ref=${encodeURIComponent(selectedRef)}`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });

            if (response.ok) {
                const data = await response.json();
                setMessage(data.message);
                fetchCurrentVersion();
            } else {
                const errData = await response.json();
                setError(errData.detail || 'Failed to switch version');
            }
        } catch (err: any) {
            setError(err.message || 'Failed to switch version');
        } finally {
            setIsSwitching(false);
        }
    };

    useEffect(() => {
        fetchCurrentVersion();
        fetchReleases();
    }, []);

    const formatDate = (dateStr: string) => {
        return new Date(dateStr).toLocaleDateString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric'
        });
    };

    const getStatusIcon = (check: SecurityCheck) => {
        if (check.status === 'not_found') return <span className="text-white/30">—</span>;
        if (check.status === 'in_progress' || check.status === 'queued') {
            return <Loader2 className="w-4 h-4 text-amber-400 animate-spin" />;
        }
        if (check.passed === true) return <Check className="w-4 h-4 text-emerald-400" />;
        if (check.passed === false) return <X className="w-4 h-4 text-red-400" />;
        return <Clock className="w-4 h-4 text-white/50" />;
    };

    return (
        <div className="space-y-4">
            {/* Current Version */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-indigo-500/20 flex items-center justify-center">
                        <GitBranch className="w-5 h-5 text-indigo-400" />
                    </div>
                    <div>
                        <p className="text-sm text-white/50">Current Version</p>
                        <p className="font-mono text-white font-medium">
                            {currentVersion?.display || 'Loading...'}
                        </p>
                    </div>
                </div>
                <button
                    onClick={() => { fetchCurrentVersion(); fetchReleases(); }}
                    className="p-2 hover:bg-white/10 rounded-lg transition-colors"
                    title="Refresh"
                >
                    <RefreshCw className={`w-4 h-4 text-white/60 ${isLoading ? 'animate-spin' : ''}`} />
                </button>
            </div>

            {/* Version Selector */}
            <div className="relative">
                <button
                    onClick={() => setDropdownOpen(!dropdownOpen)}
                    className="w-full flex items-center justify-between bg-white/10 border border-white/20 rounded-lg px-4 py-3 text-white hover:bg-white/15 transition-colors"
                >
                    <span className="flex items-center gap-2">
                        <Package className="w-4 h-4 text-white/60" />
                        {selectedRef ? (
                            <span className="font-mono">{selectedRef}</span>
                        ) : (
                            <span className="text-white/50">Select a version...</span>
                        )}
                    </span>
                    <ChevronDown className={`w-4 h-4 text-white/60 transition-transform ${dropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {dropdownOpen && (
                    <div className="absolute z-50 mt-2 w-full bg-slate-800 border border-white/20 rounded-xl shadow-xl max-h-80 overflow-y-auto">
                        {/* Releases */}
                        {releases.length > 0 && (
                            <>
                                <p className="px-4 py-2 text-xs font-medium text-white/40 uppercase tracking-wider border-b border-white/10">
                                    Releases
                                </p>
                                {releases.map((release) => (
                                    <button
                                        key={release.tag}
                                        onClick={() => handleSelectRef(release.tag, release)}
                                        className={`w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/10 transition-colors ${selectedRef === release.tag ? 'bg-indigo-500/20' : ''
                                            }`}
                                    >
                                        <div>
                                            <span className="font-mono text-white">{release.tag}</span>
                                            {release.prerelease && (
                                                <span className="ml-2 text-xs bg-amber-500/20 text-amber-400 px-1.5 py-0.5 rounded">
                                                    pre-release
                                                </span>
                                            )}
                                            <p className="text-xs text-white/50 mt-0.5">{release.name}</p>
                                        </div>
                                        <span className="text-xs text-white/40">{formatDate(release.published_at)}</span>
                                    </button>
                                ))}
                            </>
                        )}

                        {/* Recent Commits */}
                        {recentCommits.length > 0 && (
                            <>
                                <p className="px-4 py-2 text-xs font-medium text-white/40 uppercase tracking-wider border-y border-white/10">
                                    Recent Commits (main)
                                </p>
                                {recentCommits.map((commit) => (
                                    <button
                                        key={commit.sha}
                                        onClick={() => handleSelectRef(commit.full_sha, null)}
                                        className={`w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/10 transition-colors ${selectedRef === commit.full_sha ? 'bg-indigo-500/20' : ''
                                            }`}
                                    >
                                        <div>
                                            <span className="font-mono text-white">@{commit.sha}</span>
                                            <p className="text-xs text-white/50 mt-0.5 truncate max-w-[280px]">
                                                {commit.message}
                                            </p>
                                        </div>
                                        <span className="text-xs text-white/40">{formatDate(commit.date)}</span>
                                    </button>
                                ))}
                            </>
                        )}

                        {releases.length === 0 && recentCommits.length === 0 && (
                            <p className="px-4 py-6 text-center text-white/50 text-sm">
                                {isLoading ? 'Loading...' : 'No releases found'}
                            </p>
                        )}
                    </div>
                )}
            </div>

            {/* Selected Release Details */}
            {selectedRef && (
                <div className="bg-white/5 border border-white/10 rounded-xl p-4 space-y-4">
                    {/* Release Info */}
                    {selectedRelease && (
                        <div>
                            <div className="flex items-center justify-between mb-2">
                                <h4 className="font-semibold text-white">{selectedRelease.name}</h4>
                                <a
                                    href={selectedRelease.html_url}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-xs text-indigo-400 hover:text-indigo-300 flex items-center gap-1"
                                >
                                    View on GitHub <ExternalLink className="w-3 h-3" />
                                </a>
                            </div>
                            <div className="text-sm text-white/70 prose prose-invert prose-sm max-w-none">
                                {selectedRelease.body.split('\n').slice(0, 5).map((line, i) => (
                                    <p key={i} className="my-1">{line || '\u00A0'}</p>
                                ))}
                                {selectedRelease.body.split('\n').length > 5 && (
                                    <p className="text-white/40 italic">...more in release notes</p>
                                )}
                            </div>
                        </div>
                    )}

                    {/* Security Verification */}
                    <div>
                        <h4 className="text-sm font-medium text-white/70 mb-3 flex items-center gap-2">
                            <Shield className="w-4 h-4" />
                            Security Verification
                            {security?.summary && (
                                <span className={`ml-auto px-2 py-0.5 rounded text-xs font-medium ${security.summary.all_passed
                                        ? 'bg-emerald-500/20 text-emerald-400'
                                        : 'bg-amber-500/20 text-amber-400'
                                    }`}>
                                    {security.summary.score} passed
                                </span>
                            )}
                        </h4>

                        {isLoadingSecurity ? (
                            <div className="flex items-center gap-2 text-white/50 text-sm">
                                <Loader2 className="w-4 h-4 animate-spin" />
                                Loading security checks...
                            </div>
                        ) : security ? (
                            <div className="grid grid-cols-2 gap-2">
                                {Object.entries(security.verification).map(([key, check]) => (
                                    <div
                                        key={key}
                                        className="flex items-center gap-2 text-sm bg-white/5 rounded-lg px-3 py-2"
                                    >
                                        {getStatusIcon(check)}
                                        <span className="text-white/70 truncate">{check.name.replace(' (', '\n(').split('\n')[0]}</span>
                                        {check.run_url && (
                                            <a
                                                href={check.run_url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="text-white/40 hover:text-white/60 ml-auto"
                                            >
                                                <ExternalLink className="w-3 h-3" />
                                            </a>
                                        )}
                                    </div>
                                ))}
                            </div>
                        ) : (
                            <p className="text-sm text-white/40">Select a version to view security checks</p>
                        )}
                    </div>

                    {/* Switch Button */}
                    <button
                        onClick={handleSwitchVersion}
                        disabled={isSwitching || !selectedRef || (security && !security.summary.all_passed)}
                        className={`w-full flex items-center justify-center gap-2 py-3 rounded-lg font-medium transition-colors ${security?.summary.all_passed
                                ? 'bg-indigo-600 hover:bg-indigo-500 text-white'
                                : 'bg-white/10 text-white/50 cursor-not-allowed'
                            }`}
                    >
                        {isSwitching ? (
                            <>
                                <Loader2 className="w-4 h-4 animate-spin" />
                                Switching...
                            </>
                        ) : (
                            <>
                                <Package className="w-4 h-4" />
                                Switch to {selectedRef?.startsWith('v') ? selectedRef : `@${selectedRef?.slice(0, 7)}`}
                            </>
                        )}
                    </button>

                    {security && !security.summary.all_passed && (
                        <p className="text-xs text-amber-400 flex items-center gap-1.5">
                            <AlertCircle className="w-3.5 h-3.5" />
                            Some security checks did not pass. Proceed with caution.
                        </p>
                    )}
                </div>
            )}

            {/* Messages */}
            {error && (
                <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm flex items-center gap-2">
                    <AlertCircle className="w-4 h-4" />
                    {error}
                </div>
            )}

            {message && (
                <div className="p-3 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400 text-sm flex items-center gap-2">
                    <Check className="w-4 h-4" />
                    {message}
                </div>
            )}
        </div>
    );
}
