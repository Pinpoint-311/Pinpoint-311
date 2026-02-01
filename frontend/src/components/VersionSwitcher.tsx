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
    Loader2,
    GitCommit
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

// Short labels for sidebar display
const SHORT_LABELS: Record<string, string> = {
    'owasp_zap': 'Security',
    'codeql': 'CodeQL',
    'docker_build': 'Build',
    'accessibility': 'A11y'
};

export default function VersionSwitcher() {
    const [currentVersion, setCurrentVersion] = useState<{ sha: string; tag: string | null; display: string; commit_message?: string } | null>(null);
    const [releases, setReleases] = useState<Release[]>([]);
    const [recentCommits, setRecentCommits] = useState<RecentCommit[]>([]);
    const [selectedRef, setSelectedRef] = useState<string | null>(null);
    const [selectedRelease, setSelectedRelease] = useState<Release | null>(null);
    const [selectedCommit, setSelectedCommit] = useState<RecentCommit | null>(null);
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

    const handleSelectRef = (ref: string, release: Release | null, commit: RecentCommit | null) => {
        setSelectedRef(ref);
        setSelectedRelease(release);
        setSelectedCommit(commit);
        setDropdownOpen(false);
        fetchSecurity(ref);
    };

    const handleSwitchVersion = async () => {
        if (!selectedRef) return;

        const deploymentWarning = `🚀 FULL DEPLOYMENT

This will:
1. Create database backup
2. Checkout version ${selectedRef.slice(0, 7)}
3. Run database migrations
4. Rebuild all containers
5. Health check the new deployment

If anything fails, it will automatically rollback.

${security && !security.summary.all_passed ? '⚠️ Warning: Some security checks did not pass.\n\n' : ''}Continue with deployment?`;

        if (!confirm(deploymentWarning)) {
            return;
        }

        setIsSwitching(true);
        setMessage('Starting deployment...');
        setError(null);

        try {
            const token = localStorage.getItem('token');
            const response = await fetch(`/api/system/switch-version?ref=${encodeURIComponent(selectedRef)}`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });

            const data = await response.json();

            if (response.ok) {
                setMessage(`✅ ${data.message}`);
                setSelectedRef(null);
                setSelectedRelease(null);
                setSelectedCommit(null);
                setSecurity(null);
                fetchCurrentVersion();
                fetchReleases();
            } else {
                // Handle rollback response
                const detail = data.detail;
                if (typeof detail === 'object') {
                    setError(`❌ ${detail.message || 'Deployment failed'}${detail.rollback_performed ? ' - Rollback completed' : ''}`);
                } else {
                    setError(detail || 'Failed to deploy version');
                }
            }
        } catch (err: any) {
            setError(`Failed to deploy: ${err.message}`);
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
            day: 'numeric'
        });
    };

    const getStatusIcon = (check: SecurityCheck) => {
        if (check.status === 'not_found') return <span className="text-white/30">—</span>;
        if (check.status === 'in_progress' || check.status === 'queued') {
            return <Loader2 className="w-3.5 h-3.5 text-amber-400 animate-spin" />;
        }
        if (check.passed === true) return <Check className="w-3.5 h-3.5 text-emerald-400" />;
        if (check.passed === false) return <X className="w-3.5 h-3.5 text-red-400" />;
        return <Clock className="w-3.5 h-3.5 text-white/50" />;
    };

    // Parse commit message into type and description
    const parseCommitMessage = (msg: string) => {
        const match = msg.match(/^(\w+)(?:\(([^)]+)\))?:\s*(.+)$/);
        if (match) {
            return { type: match[1], scope: match[2], desc: match[3] };
        }
        return { type: null, scope: null, desc: msg };
    };

    const getTypeColor = (type: string | null) => {
        switch (type) {
            case 'feat': return 'bg-emerald-500/20 text-emerald-400';
            case 'fix': return 'bg-amber-500/20 text-amber-400';
            case 'style': return 'bg-purple-500/20 text-purple-400';
            case 'refactor': return 'bg-blue-500/20 text-blue-400';
            case 'docs': return 'bg-sky-500/20 text-sky-400';
            case 'chore': return 'bg-gray-500/20 text-gray-400';
            default: return 'bg-white/10 text-white/60';
        }
    };

    return (
        <div className="space-y-3">
            {/* Current Version */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 min-w-0">
                    <div className="w-8 h-8 rounded-lg bg-indigo-500/20 flex items-center justify-center flex-shrink-0">
                        <GitBranch className="w-4 h-4 text-indigo-400" />
                    </div>
                    <div className="min-w-0">
                        <p className="text-xs text-white/50">Current</p>
                        <p className="font-mono text-sm text-white font-medium truncate">
                            {currentVersion?.display || '...'}
                        </p>
                    </div>
                </div>
                <button
                    onClick={() => { fetchCurrentVersion(); fetchReleases(); }}
                    className="p-1.5 hover:bg-white/10 rounded-lg transition-colors flex-shrink-0"
                    title="Refresh"
                >
                    <RefreshCw className={`w-3.5 h-3.5 text-white/60 ${isLoading ? 'animate-spin' : ''}`} />
                </button>
            </div>

            {/* Current commit message */}
            {currentVersion?.commit_message && (
                <p className="text-xs text-white/50 px-1 truncate" title={currentVersion.commit_message}>
                    {currentVersion.commit_message}
                </p>
            )}

            {/* Version Selector */}
            <div className="relative">
                <button
                    onClick={() => setDropdownOpen(!dropdownOpen)}
                    className="w-full flex items-center justify-between bg-white/10 border border-white/20 rounded-lg px-3 py-2 text-white hover:bg-white/15 transition-colors text-sm"
                >
                    <span className="flex items-center gap-2 min-w-0">
                        <Package className="w-3.5 h-3.5 text-white/60 flex-shrink-0" />
                        {selectedRef ? (
                            <span className="font-mono truncate">@{selectedRef.slice(0, 7)}</span>
                        ) : (
                            <span className="text-white/50">Select version</span>
                        )}
                    </span>
                    <ChevronDown className={`w-3.5 h-3.5 text-white/60 transition-transform flex-shrink-0 ${dropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {dropdownOpen && (
                    <div className="absolute z-50 mt-2 w-[calc(100%+60px)] -left-[30px] bg-slate-800 border border-white/20 rounded-xl shadow-xl max-h-80 overflow-y-auto">
                        {/* Releases */}
                        {releases.length > 0 && (
                            <>
                                <p className="px-3 py-1.5 text-xs font-medium text-white/40 uppercase tracking-wider border-b border-white/10">
                                    Releases
                                </p>
                                {releases.map((release) => (
                                    <button
                                        key={release.tag}
                                        onClick={() => handleSelectRef(release.tag, release, null)}
                                        className={`w-full px-3 py-2 text-left hover:bg-white/10 transition-colors ${selectedRef === release.tag ? 'bg-indigo-500/20' : ''
                                            }`}
                                    >
                                        <div className="flex items-center justify-between">
                                            <span className="font-mono text-white text-sm">{release.tag}</span>
                                            <span className="text-xs text-white/40">{formatDate(release.published_at)}</span>
                                        </div>
                                        <p className="text-xs text-white/60 mt-0.5">{release.name}</p>
                                    </button>
                                ))}
                            </>
                        )}

                        {/* Recent Commits - Enhanced */}
                        {recentCommits.length > 0 && (
                            <>
                                <p className="px-3 py-1.5 text-xs font-medium text-white/40 uppercase tracking-wider border-y border-white/10">
                                    Recent Updates
                                </p>
                                {recentCommits.map((commit) => {
                                    const parsed = parseCommitMessage(commit.message);
                                    return (
                                        <button
                                            key={commit.sha}
                                            onClick={() => handleSelectRef(commit.full_sha, null, commit)}
                                            className={`w-full px-3 py-2.5 text-left hover:bg-white/10 transition-colors border-b border-white/5 last:border-0 ${selectedRef === commit.full_sha ? 'bg-indigo-500/20' : ''
                                                }`}
                                        >
                                            <div className="flex items-center justify-between mb-1">
                                                <div className="flex items-center gap-2">
                                                    <GitCommit className="w-3 h-3 text-white/40" />
                                                    <span className="font-mono text-white text-xs">@{commit.sha}</span>
                                                    {parsed.type && (
                                                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${getTypeColor(parsed.type)}`}>
                                                            {parsed.type}
                                                        </span>
                                                    )}
                                                </div>
                                                <span className="text-[10px] text-white/40">{formatDate(commit.date)}</span>
                                            </div>
                                            <p className="text-sm text-white/80 leading-snug">
                                                {parsed.scope && <span className="text-white/40">[{parsed.scope}]</span>} {parsed.desc}
                                            </p>
                                        </button>
                                    );
                                })}
                            </>
                        )}

                        {releases.length === 0 && recentCommits.length === 0 && (
                            <p className="px-3 py-4 text-center text-white/50 text-sm">
                                {isLoading ? 'Loading...' : 'No releases found'}
                            </p>
                        )}
                    </div>
                )}
            </div>

            {/* Selected Version Details */}
            {selectedRef && (
                <div className="bg-white/5 border border-white/10 rounded-lg p-3 space-y-3">
                    {/* What's in this update */}
                    <div>
                        <p className="text-xs font-medium text-white/50 mb-1.5">What's in this update:</p>
                        {selectedRelease ? (
                            <div className="text-sm text-white/80">
                                <p className="font-medium text-white mb-1">{selectedRelease.name}</p>
                                <p className="text-xs text-white/60 line-clamp-3">{selectedRelease.body.split('\n').slice(0, 3).join(' ')}</p>
                            </div>
                        ) : selectedCommit ? (
                            <div className="text-sm">
                                {(() => {
                                    const parsed = parseCommitMessage(selectedCommit.message);
                                    return (
                                        <>
                                            <div className="flex items-center gap-2 mb-1">
                                                {parsed.type && (
                                                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${getTypeColor(parsed.type)}`}>
                                                        {parsed.type === 'feat' ? 'New Feature' :
                                                            parsed.type === 'fix' ? 'Bug Fix' :
                                                                parsed.type === 'style' ? 'Style Update' :
                                                                    parsed.type === 'refactor' ? 'Refactor' : parsed.type}
                                                    </span>
                                                )}
                                                {parsed.scope && <span className="text-xs text-white/40">{parsed.scope}</span>}
                                            </div>
                                            <p className="text-white/80">{parsed.desc}</p>
                                        </>
                                    );
                                })()}
                                <p className="text-[10px] text-white/40 mt-1">by {selectedCommit.author} • {formatDate(selectedCommit.date)}</p>
                            </div>
                        ) : (
                            <p className="text-xs text-white/50">Commit details not available</p>
                        )}
                    </div>

                    {/* Security Verification - Compact */}
                    <div>
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-xs font-medium text-white/50 flex items-center gap-1">
                                <Shield className="w-3 h-3" />
                                Verified
                            </span>
                            {security?.summary && (
                                <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${security.summary.all_passed
                                    ? 'bg-emerald-500/20 text-emerald-400'
                                    : 'bg-amber-500/20 text-amber-400'
                                    }`}>
                                    {security.summary.score}
                                </span>
                            )}
                        </div>

                        {isLoadingSecurity ? (
                            <div className="flex items-center gap-2 text-white/50 text-xs">
                                <Loader2 className="w-3 h-3 animate-spin" />
                                Checking...
                            </div>
                        ) : security ? (
                            <div className="grid grid-cols-2 gap-1">
                                {Object.entries(security.verification).map(([key, check]) => (
                                    <div
                                        key={key}
                                        className="flex items-center gap-1.5 text-[11px] bg-white/5 rounded px-2 py-1"
                                        title={check.name}
                                    >
                                        {getStatusIcon(check)}
                                        <span className="text-white/70">{SHORT_LABELS[key] || key}</span>
                                        {check.run_url && (
                                            <a
                                                href={check.run_url}
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                className="text-white/30 hover:text-white/60 ml-auto"
                                            >
                                                <ExternalLink className="w-2.5 h-2.5" />
                                            </a>
                                        )}
                                    </div>
                                ))}
                            </div>
                        ) : null}
                    </div>

                    {/* Switch Button */}
                    <button
                        onClick={handleSwitchVersion}
                        disabled={isSwitching || !selectedRef}
                        className={`w-full flex items-center justify-center gap-1.5 py-2 rounded-lg font-medium transition-colors text-sm ${security?.summary.all_passed
                            ? 'bg-indigo-600 hover:bg-indigo-500 text-white'
                            : 'bg-amber-600/80 hover:bg-amber-600 text-white'
                            }`}
                    >
                        {isSwitching ? (
                            <>
                                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                Switching...
                            </>
                        ) : (
                            <>
                                <Package className="w-3.5 h-3.5" />
                                Deploy this version
                            </>
                        )}
                    </button>

                    {security && !security.summary.all_passed && (
                        <p className="text-[10px] text-amber-400/80 flex items-start gap-1">
                            <AlertCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                            <span>Some checks incomplete</span>
                        </p>
                    )}
                </div>
            )}

            {/* Messages */}
            {error && (
                <div className="p-2 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-xs flex items-center gap-1.5">
                    <AlertCircle className="w-3 h-3 flex-shrink-0" />
                    <span className="truncate">{error}</span>
                </div>
            )}

            {message && (
                <div className="p-2 bg-emerald-500/10 border border-emerald-500/30 rounded-lg text-emerald-400 text-xs flex items-center gap-1.5">
                    <Check className="w-3 h-3 flex-shrink-0" />
                    <span>{message}</span>
                </div>
            )}
        </div>
    );
}
