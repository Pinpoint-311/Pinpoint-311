import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { SettingsProvider } from './context/SettingsContext';
import { AccessibilityProvider } from './context/AccessibilityContext';
import { TranslationProvider } from './context/TranslationContext';
import { DialogProvider } from './components/DialogProvider';
import { AutoTranslate } from './components/AutoTranslate';
import ErrorBoundary from './components/ErrorBoundary';
import ResidentPortal from './pages/ResidentPortal';
import Login from './pages/Login';

// Staff/admin/research surfaces (and legal pages) are code-split so a
// resident's first paint doesn't download the entire admin console,
// integration wizard, and analytics lab. Each becomes its own chunk,
// fetched on demand behind the auth wall.
const StaffDashboard = lazy(() => import('./pages/StaffDashboard'));
const AdminConsole = lazy(() => import('./pages/AdminConsole'));
const ResearchLab = lazy(() => import('./pages/ResearchLab').then(m => ({ default: m.ResearchLab })));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));
const PrivacyPolicy = lazy(() => import('./pages/PrivacyPolicy'));
const TermsOfService = lazy(() => import('./pages/TermsOfService'));
const AccessibilityPage = lazy(() => import('./pages/AccessibilityPage'));

// Global error handlers — report unhandled errors to backend
function reportError(payload: Record<string, unknown>) {
    try {
        fetch('/api/system/client-errors', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                ...payload,
                url: window.location.href,
                timestamp: new Date().toISOString(),
                userAgent: navigator.userAgent,
            }),
        }).catch(() => {});
    } catch {}
}

window.onerror = (message, source, lineno, colno, error) => {
    reportError({
        type: 'unhandled_error',
        message: String(message),
        source,
        lineno,
        colno,
        stack: error?.stack,
    });
};

window.onunhandledrejection = (event: PromiseRejectionEvent) => {
    reportError({
        type: 'unhandled_promise_rejection',
        message: event.reason?.message || String(event.reason),
        stack: event.reason?.stack,
    });
};

// Protected route wrapper
function ProtectedRoute({
    children,
    requiredRole
}: {
    children: React.ReactNode;
    requiredRole?: 'staff' | 'admin' | 'researcher';
}) {
    const { isAuthenticated, isLoading, user } = useAuth();

    if (isLoading) {
        return (
            <div className="min-h-screen flex items-center justify-center" role="status" aria-label="Loading">
                <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
                <span className="sr-only">Loading, please wait...</span>
            </div>
        );
    }

    if (!isAuthenticated) {
        return <Navigate to="/login" replace />;
    }

    if (requiredRole === 'admin' && user?.role !== 'admin') {
        return <Navigate to="/staff" replace />;
    }

    if (requiredRole === 'researcher' && user?.role !== 'researcher' && user?.role !== 'admin') {
        return <Navigate to="/staff" replace />;
    }

    return <>{children}</>;
}

// Shared fallback shown while a code-split route chunk is loading.
function RouteFallback() {
    return (
        <div className="min-h-screen flex items-center justify-center" role="status" aria-label="Loading">
            <div className="w-8 h-8 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
            <span className="sr-only">Loading, please wait...</span>
        </div>
    );
}

function AppRoutes() {
    return (
        <Suspense fallback={<RouteFallback />}>
        <Routes>
            <Route path="/" element={<ResidentPortal />} />
            <Route path="/login" element={<Login />} />
            <Route
                path="/staff"
                element={
                    <ProtectedRoute requiredRole="staff">
                        <StaffDashboard />
                    </ProtectedRoute>
                }
            />
            <Route
                path="/admin"
                element={
                    <ProtectedRoute requiredRole="admin">
                        <AdminConsole />
                    </ProtectedRoute>
                }
            />
            <Route path="/setup" element={<Navigate to="/admin#integration" replace />} />
            <Route
                path="/staff/request/:requestId"
                element={
                    <ProtectedRoute requiredRole="staff">
                        <StaffDashboard />
                    </ProtectedRoute>
                }
            />
            <Route
                path="/research"
                element={
                    <ProtectedRoute requiredRole="researcher">
                        <ResearchLab />
                    </ProtectedRoute>
                }
            />
            <Route path="/privacy" element={<PrivacyPolicy />} />
            <Route path="/terms" element={<TermsOfService />} />
            <Route path="/accessibility" element={<AccessibilityPage />} />
            <Route path="*" element={<NotFoundPage />} />
        </Routes>
        </Suspense>
    );
}

export default function App() {
    return (
        <ErrorBoundary>
            <BrowserRouter>
                <AccessibilityProvider>
                    <SettingsProvider>
                        <TranslationProvider>
                            <DialogProvider>
                                <AutoTranslate>
                                    <AuthProvider>
                                        <AppRoutes />
                                    </AuthProvider>
                                </AutoTranslate>
                            </DialogProvider>
                        </TranslationProvider>
                    </SettingsProvider>
                </AccessibilityProvider>
            </BrowserRouter>
        </ErrorBoundary>
    );
}
