import { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';

interface Props {
    children: ReactNode;
}

interface State {
    hasError: boolean;
    error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false, error: null };

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, errorInfo: ErrorInfo) {
        console.error('ErrorBoundary caught:', error, errorInfo);
        // Report to backend
        try {
            fetch('/api/system/client-errors', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    type: 'react_error_boundary',
                    message: error.message,
                    stack: error.stack,
                    componentStack: errorInfo.componentStack,
                    url: window.location.href,
                    timestamp: new Date().toISOString(),
                    userAgent: navigator.userAgent,
                }),
            }).catch(() => {});
        } catch {}
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="min-h-screen flex items-center justify-center p-6" style={{ background: 'linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%)' }}>
                    <div className="max-w-md w-full text-center">
                        <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-red-500/20 border border-red-500/30 flex items-center justify-center">
                            <AlertTriangle className="w-8 h-8 text-red-400" strokeWidth={2} aria-hidden="true" />
                        </div>
                        <h1 className="text-2xl font-bold text-white mb-2">Something went wrong</h1>
                        <p className="text-white/60 mb-6">An unexpected error occurred. This has been automatically reported.</p>
                        <button
                            onClick={() => window.location.reload()}
                            className="px-6 py-3 bg-primary-500 hover:bg-primary-600 text-white rounded-xl font-semibold transition-colors"
                        >
                            Reload Page
                        </button>
                        {this.state.error && (
                            <details className="mt-6 text-left">
                                <summary className="text-white/40 text-sm cursor-pointer hover:text-white/60">Error details</summary>
                                <pre className="mt-2 p-3 bg-black/30 rounded-lg text-xs text-red-300/70 overflow-auto max-h-32">
                                    {this.state.error.message}
                                </pre>
                            </details>
                        )}
                    </div>
                </div>
            );
        }

        return this.props.children;
    }
}
