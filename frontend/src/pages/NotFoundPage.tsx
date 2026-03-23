import { Link } from 'react-router-dom';

export default function NotFoundPage() {
    return (
        <div className="min-h-screen flex items-center justify-center p-6" style={{ background: 'linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%)' }}>
            <div className="max-w-md w-full text-center">
                <div className="text-8xl font-bold text-white/10 mb-4">404</div>
                <h1 className="text-2xl font-bold text-white mb-2">Page not found</h1>
                <p className="text-white/60 mb-8">The page you're looking for doesn't exist or has been moved.</p>
                <div className="flex flex-col sm:flex-row gap-3 justify-center">
                    <Link
                        to="/"
                        className="px-6 py-3 bg-primary-500 hover:bg-primary-600 text-white rounded-xl font-semibold transition-colors no-underline"
                    >
                        Go to Home
                    </Link>
                    <button
                        onClick={() => window.history.back()}
                        className="px-6 py-3 bg-white/10 hover:bg-white/20 text-white rounded-xl font-semibold transition-colors border border-white/10"
                    >
                        Go Back
                    </button>
                </div>
            </div>
        </div>
    );
}
