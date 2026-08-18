import { useEffect } from 'react';
import { Link } from 'react-router-dom';

export default function NotFoundPage() {
    /* Without this the 404 kept whatever title the page before it had set, so
     * the browser tab, the history entry and the bookmark all claimed the
     * resident was still on the page they had failed to reach (WCAG 2.4.2). */
    useEffect(() => {
        const previousTitle = document.title;
        document.title = 'Page not found | Municipality 311';
        return () => { document.title = previousTitle; };
    }, []);

    return (
        <div className="min-h-screen flex items-center justify-center p-6" style={{ background: 'linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%)' }}>
            {/* The app-wide skip link targets #main-content, and this page had no
                such landmark -- so on the 404 the skip link pointed at nothing.
                The big "404" is decorative: the heading below says the same
                thing in words, and read aloud the digits are just noise. */}
            <main id="main-content" className="max-w-md w-full text-center">
                <div className="text-8xl font-bold text-white/10 mb-4" aria-hidden="true">404</div>
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
            </main>
        </div>
    );
}
