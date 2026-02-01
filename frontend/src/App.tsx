import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { SettingsProvider } from './context/SettingsContext';
import { AccessibilityProvider } from './context/AccessibilityContext';
import { TranslationProvider } from './context/TranslationContext';
import { AutoTranslate } from './components/AutoTranslate';
import ResidentPortal from './pages/ResidentPortal';
import StaffDashboard from './pages/StaffDashboard';
import AdminConsole from './pages/AdminConsole';
import { ResearchLab } from './pages/ResearchLab';
import { SetupWizard } from './pages/SetupWizard';
import Login from './pages/Login';

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

function AppRoutes() {
    return (
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
            <Route
                path="/setup"
                element={
                    <ProtectedRoute requiredRole="admin">
                        <SetupWizard />
                    </ProtectedRoute>
                }
            />
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
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
    );
}

export default function App() {
    return (
        <BrowserRouter>
            <AccessibilityProvider>
                <SettingsProvider>
                    <TranslationProvider>
                        <AutoTranslate>
                            <AuthProvider>
                                <AppRoutes />
                            </AuthProvider>
                        </AutoTranslate>
                    </TranslationProvider>
                </SettingsProvider>
            </AccessibilityProvider>
        </BrowserRouter>
    );
}
