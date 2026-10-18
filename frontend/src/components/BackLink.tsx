import type { MouseEvent, ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';

/**
 * The back arrow on the static pages (Terms, Privacy, Accessibility).
 *
 * It used to be a plain <Link to="/">, which PUSHED a fresh "/" with no hash.
 * A resident who followed "Terms of Service" from the middle of a report and
 * pressed this arrow was dropped on the home page instead of the form they
 * came from -- the "#report/<code>" entry they came from was still in history,
 * just one step behind.
 *
 * When there is in-app history (react-router gives the first entry of a
 * session the key "default"), this goes back to exactly where the resident
 * came from, hash and all. Arriving cold -- a bookmark, a shared link, a new
 * tab -- there is nothing to go back to inside the app, so it falls back to
 * home. It stays a real link to "/" so it still works without the handler
 * (middle-click, open in new tab) and reads as a link to assistive tech.
 */
export default function BackLink({
    className,
    label = 'Go back',
    children,
}: {
    className?: string;
    label?: string;
    children: ReactNode;
}) {
    const navigate = useNavigate();
    const location = useLocation();
    const hasInAppHistory = location.key !== 'default';

    const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
        // Leave modified clicks (new tab / window) to the browser.
        if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        if (!hasInAppHistory) return; // the Link's own "/" navigation
        e.preventDefault();
        navigate(-1);
    };

    return (
        <Link to="/" onClick={onClick} className={className} aria-label={label}>
            {children}
        </Link>
    );
}
