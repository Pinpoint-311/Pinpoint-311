import { useState, useMemo, useEffect, useRef, useCallback, useId } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Bell, MessageSquare, UserPlus, AlertCircle, Clock, ChevronRight, Building2 } from 'lucide-react';
import { ServiceRequest } from '../types';
import { readIdsFromStorage } from './activityBell';
import { useAnnounce } from '../context/AccessibilityContext';

/* The focusable children of the panel, in tab order — the same idea as
 * ui/Modal.tsx's helper. A disabled control still matches the bare selector but
 * silently ignores .focus(), which lands focus on <body> outside the dialog;
 * a control in a display:none subtree would let Tab stop at something
 * invisible. Either one ends with focus escaping to the dashboard behind.
 *
 * Visibility is decided from computed style rather than `offsetParent`: the
 * whole panel is position:fixed, where offsetParent is null for everything
 * inside it, so an offsetParent test rejects every control in this dialog and
 * leaves the trap with nothing to hold on to. */
function getFocusable(root: HTMLElement | null): HTMLElement[] {
    if (!root) return [];
    const candidates = root.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, summary, [contenteditable]:not([contenteditable="false"]), [tabindex]:not([tabindex="-1"])'
    );
    return Array.from(candidates).filter(el => {
        if (el.hasAttribute('disabled') || el.getAttribute('aria-hidden') === 'true') return false;
        if (el.closest('[hidden]')) return false;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden';
    });
}

interface ActivityFeedProps {
    isOpen: boolean;
    onClose: () => void;
    requests: ServiceRequest[];
    userId: string;
    userDepartmentIds: number[];
    onSelectRequest: (request: ServiceRequest) => void;
}

interface FeedItem {
    id: string;
    type: 'new_request' | 'assigned_to_me' | 'assigned_to_dept' | 'status_change' | 'new_comment';
    title: string;
    description: string;
    timestamp: Date;
    request: ServiceRequest;
    isNew: boolean;
}

/**
 * A stable, unique handle for one request's feed items.
 *
 * `service_request_id` is the natural choice, but it can arrive empty -- an
 * intake that never got one, or a partially-hydrated row -- and every such
 * request then produced the same React key (`new-`, `dept-`), so React
 * collapsed them and dropped entries from the rendered feed. Fall back to the
 * numeric primary key, and to the list position only if even that is missing.
 */
function requestKey(request: ServiceRequest, index: number): string {
    if (request.service_request_id) return String(request.service_request_id);
    if (request.id !== undefined && request.id !== null) return `id-${request.id}`;
    return `idx-${index}`;
}

export default function ActivityFeed({
    isOpen,
    onClose,
    requests,
    userId,
    userDepartmentIds,
    onSelectRequest
}: ActivityFeedProps) {
    const [readItems, setReadItems] = useState<Set<string>>(() => {
        const stored = localStorage.getItem('activityFeedRead');
        return stored ? new Set(JSON.parse(stored)) : new Set();
    });
    const announce = useAnnounce();

    /* This slide-over is a modal dialog in every way that matters to a sighted
     * mouse user — it dims the dashboard and swallows outside clicks — but it
     * carried none of the semantics or behaviour that make that true for anyone
     * else. The panel had no role, so a screen reader read it as part of the
     * page it is covering; Tab walked straight out of it into the dashboard
     * underneath (WCAG 2.4.3); Escape did nothing, so a keyboard user who
     * opened it could reach the close button only by tabbing the whole page
     * (2.1.2); and closing it dropped focus on <body>, stranding the user at
     * the top of the document rather than back on the bell they came from.
     *
     * ui/Modal.tsx is not usable here — it centres a box, and this is an
     * edge-anchored full-height rail — so the same contract is implemented on
     * the panel itself: dialog role + aria-modal, a name from the heading, a
     * wrapping Tab trap, Escape to close, and focus restored to whatever was
     * focused when the panel opened. */
    const panelRef = useRef<HTMLDivElement>(null);
    const previouslyFocused = useRef<HTMLElement | null>(null);
    const titleId = useId();

    useEffect(() => {
        if (!isOpen) return;
        previouslyFocused.current = document.activeElement as HTMLElement | null;
        // A frame late: the panel mounts in this same commit, so querying for
        // focusables synchronously can run before the list has painted.
        const id = window.setTimeout(() => {
            const focusable = getFocusable(panelRef.current);
            (focusable[0] ?? panelRef.current)?.focus();
        }, 0);
        return () => {
            window.clearTimeout(id);
            // Restore on close *and* on unmount — the dashboard keeps this
            // component mounted, but a route change away while open would
            // otherwise leave focus nowhere.
            previouslyFocused.current?.focus?.();
        };
    }, [isOpen]);

    const handleKeyDown = useCallback((event: KeyboardEvent) => {
        if (event.key === 'Escape') {
            event.preventDefault();
            onClose();
            return;
        }
        if (event.key !== 'Tab') return;
        const focusable = getFocusable(panelRef.current);
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        } else if (!panelRef.current?.contains(document.activeElement)) {
            // Focus started outside the panel (e.g. on <body> after a click on
            // the backdrop); pull it back in rather than letting Tab continue
            // through the dashboard behind the dialog.
            event.preventDefault();
            first.focus();
        }
    }, [onClose]);

    useEffect(() => {
        if (!isOpen) return;
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [isOpen, handleKeyDown]);

    // Generate feed items from requests
    const feedItems = useMemo<FeedItem[]>(() => {
        const items: FeedItem[] = [];
        const now = Date.now();
        const twentyFourHours = 24 * 60 * 60 * 1000;
        const sevenDays = 7 * 24 * 60 * 60 * 1000;

        requests.forEach((request, index) => {
            const key = requestKey(request, index);
            const requestTime = new Date(request.requested_datetime).getTime();
            const requestAge = now - requestTime;

            // Skip old requests
            if (requestAge > sevenDays) return;

            // Relevance mirrors the notification logic: a request matters to you
            // if it's assigned to you or routed to your department. Staff with no
            // departments configured (e.g. admins) see all activity — the same
            // convention the dashboard uses, and safe because the request list is
            // already department-scoped server-side.
            const mine = request.assigned_to === userId;
            const deptMatch = !!request.assigned_department_id && userDepartmentIds.includes(request.assigned_department_id);
            const noDeptScope = userDepartmentIds.length === 0;
            if (!mine && !deptMatch && !noDeptScope) return;

            const updatedTime = request.updated_datetime ? new Date(request.updated_datetime).getTime() : null;
            const wasUpdated = updatedTime !== null && Math.abs(updatedTime - requestTime) > 60 * 1000;

            // New request attached to you or your department (< 24 hours)
            if (requestAge < twentyFourHours) {
                items.push({
                    id: `new-${key}`,
                    type: mine ? 'assigned_to_me' : 'new_request',
                    title: mine ? `New & assigned to you: ${request.service_name}` : `New: ${request.service_name}`,
                    description: (request.description?.substring(0, 80) + (request.description && request.description.length > 80 ? '...' : '')) || `Request #${request.service_request_id}`,
                    timestamp: new Date(request.requested_datetime),
                    request,
                    isNew: !readItems.has(`new-${key}`)
                });
            }
            // Otherwise, a recent status/activity update on a request relevant to you
            else if (wasUpdated && (now - (updatedTime as number)) < twentyFourHours * 2) {
                items.push({
                    id: `upd-${key}-${updatedTime}`,
                    type: 'status_change',
                    title: `Updated: ${request.service_name}`,
                    description: `Status: ${String(request.status).replace(/_/g, ' ')}${mine ? ' · assigned to you' : ''}`,
                    timestamp: new Date(request.updated_datetime as string),
                    request,
                    isNew: !readItems.has(`upd-${key}-${updatedTime}`)
                });
            }

            // Unassigned request in your department that still needs an owner
            if (deptMatch && !request.assigned_to &&
                requestAge >= twentyFourHours && requestAge < twentyFourHours * 3) {
                items.push({
                    id: `dept-${key}`,
                    type: 'assigned_to_dept',
                    title: `Needs attention: ${request.service_name}`,
                    description: 'Assigned to your department but no individual owner',
                    timestamp: new Date(request.requested_datetime),
                    request,
                    isNew: !readItems.has(`dept-${key}`)
                });
            }
        });

        // Sort by timestamp, newest first
        items.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());

        return items.slice(0, 50); // Limit to 50 items
    }, [requests, userId, userDepartmentIds, readItems]);

    const unreadCount = feedItems.filter(item => item.isNew).length;

    // Both of these are writers of the same `activityFeedRead` set that
    // StaffDashboard's open-detail handler (markKeyRead, in activityBell.ts)
    // also writes to -- and this component is mounted for the dashboard's
    // whole lifetime, so `readItems` is a snapshot taken once at mount, not
    // at each write. Building the next value from `readItems` here would
    // silently discard whatever markKeyRead (or the other writer) added to
    // storage since then: open eight requests from the list, then click one
    // feed item, and the rewrite from the stale in-memory set would put all
    // seven other requests back in the unread count. Re-reading storage
    // immediately before each write, and merging into that instead of into
    // the stale `readItems`, keeps both writers safe.
    const markAsRead = (itemId: string) => {
        const newRead = readIdsFromStorage(localStorage.getItem('activityFeedRead'));
        newRead.add(itemId);
        setReadItems(newRead);
        localStorage.setItem('activityFeedRead', JSON.stringify([...newRead]));
    };

    const markAllAsRead = () => {
        const newRead = readIdsFromStorage(localStorage.getItem('activityFeedRead'));
        feedItems.forEach(item => newRead.add(item.id));
        setReadItems(newRead);
        localStorage.setItem('activityFeedRead', JSON.stringify([...newRead]));
        /* The only feedback for this button is the "N unread" line changing to
         * zero and the button itself disappearing — both silent to a screen
         * reader, which is left unsure the press did anything (WCAG 4.1.3).
         * Announced before the re-render so the count is still readable. */
        announce(`${unreadCount} ${unreadCount === 1 ? 'item' : 'items'} marked as read. No unread activity.`);
    };

    const handleItemClick = (item: FeedItem) => {
        markAsRead(item.id);
        onSelectRequest(item.request);
        onClose();
    };

    const getItemIcon = (type: FeedItem['type']) => {
        switch (type) {
            /* Purely decorative: the item's own title already says what kind of
             * activity this is, so an announced icon would just double it.
             * lucide renders a bare <svg> with no aria-hidden of its own. */
            case 'new_request':
                return <AlertCircle className="w-4 h-4 text-emerald-400" aria-hidden="true" />;
            case 'assigned_to_me':
                return <UserPlus className="w-4 h-4 text-primary-400" aria-hidden="true" />;
            case 'assigned_to_dept':
                return <Building2 className="w-4 h-4 text-purple-400" aria-hidden="true" />;
            case 'status_change':
                return <Clock className="w-4 h-4 text-amber-400" aria-hidden="true" />;
            case 'new_comment':
                return <MessageSquare className="w-4 h-4 text-blue-400" aria-hidden="true" />;
        }
    };

    const formatTimeAgo = (date: Date) => {
        const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
        if (seconds < 60) return 'Just now';
        if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
        if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
        return `${Math.floor(seconds / 86400)}d ago`;
    };

    if (!isOpen) return null;

    return (
        <AnimatePresence>
            {/* The backdrop is a sibling of the panel, not its parent: it has to
              * carry aria-hidden (it is a decorative dimmer with a click
              * handler, invisible to a keyboard user), and while it wrapped the
              * panel that aria-hidden would have hidden the dialog too. */}
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
                onClick={onClose}
                aria-hidden="true"
            />
            <motion.div
                ref={panelRef}
                initial={{ x: -320, opacity: 0 }}
                animate={{ x: 0, opacity: 1 }}
                exit={{ x: -320, opacity: 0 }}
                transition={{ type: 'spring', damping: 25, stiffness: 300 }}
                className="fixed left-0 top-0 bottom-0 z-50 w-full max-w-sm bg-slate-900 border-r border-white/10 shadow-2xl flex flex-col"
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                tabIndex={-1}
            >
                {/* Header */}
                <div className="p-4 border-b border-white/10 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-full bg-primary-500/20 flex items-center justify-center">
                            <Bell className="w-5 h-5 text-primary-400" aria-hidden="true" />
                        </div>
                        <div>
                            <h2 id={titleId} className="text-lg font-semibold text-white">Activity Feed</h2>
                            <p className="text-sm text-white/50">{unreadCount} unread</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {unreadCount > 0 && (
                            <button
                                onClick={markAllAsRead}
                                className="text-xs text-primary-400 hover:text-primary-300 transition-colors"
                            >
                                Mark all read
                            </button>
                        )}
                        <button
                            onClick={onClose}
                            className="p-2 hover:bg-white/10 rounded-lg transition-colors"
                            aria-label="Close activity feed"
                        >
                            <X className="w-5 h-5 text-white/60" aria-hidden="true" />
                        </button>
                    </div>
                </div>

                {/* Feed Items */}
                <div className="flex-1 overflow-y-auto">
                    {feedItems.length === 0 ? (
                        <div className="p-8 text-center">
                            <Bell className="w-12 h-12 text-white/20 mx-auto mb-4" aria-hidden="true" />
                            <p className="text-white/50">No recent activity</p>
                            <p className="text-sm text-white/30 mt-1">New requests and updates will appear here</p>
                        </div>
                    ) : (
                        <div className="divide-y divide-white/5">
                            {feedItems.map((item) => (
                                <button
                                    key={item.id}
                                    onClick={() => handleItemClick(item)}
                                    className={`w-full p-4 text-left hover:bg-white/5 transition-colors flex items-start gap-3 ${item.isNew ? 'bg-primary-500/5' : ''
                                        }`}
                                >
                                    <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${item.type === 'new_request' ? 'bg-emerald-500/20' :
                                        item.type === 'assigned_to_me' ? 'bg-primary-500/20' :
                                            item.type === 'assigned_to_dept' ? 'bg-purple-500/20' :
                                                item.type === 'new_comment' ? 'bg-blue-500/20' :
                                                    'bg-amber-500/20'
                                        }`}>
                                        {getItemIcon(item.type)}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                            <p className={`text-sm font-medium truncate ${item.isNew ? 'text-white' : 'text-white/70'}`}>
                                                {item.title}
                                            </p>
                                            {item.isNew && (
                                                <span className="w-2 h-2 rounded-full bg-primary-400 flex-shrink-0" />
                                            )}
                                        </div>
                                        <p className="text-xs text-white/40 truncate mt-0.5">{item.description}</p>
                                        <p className="text-xs text-white/30 mt-1">{formatTimeAgo(item.timestamp)}</p>
                                    </div>
                                    <ChevronRight className="w-4 h-4 text-white/20 flex-shrink-0 mt-1" aria-hidden="true" />
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            </motion.div>
        </AnimatePresence>
    );
}

// Export the unread count hook for use in the bell icon
export function useActivityFeedCount(
    requests: ServiceRequest[],
    userId: string,
    userDepartmentIds: number[]
): number {
    const [readItems] = useState<Set<string>>(() => {
        const stored = localStorage.getItem('activityFeedRead');
        return stored ? new Set(JSON.parse(stored)) : new Set();
    });

    return useMemo(() => {
        let count = 0;
        const now = Date.now();
        const twentyFourHours = 24 * 60 * 60 * 1000;

        requests.forEach((request, index) => {
            const key = requestKey(request, index);
            const requestTime = new Date(request.requested_datetime).getTime();
            const requestAge = now - requestTime;
            if (requestAge > twentyFourHours * 2) return;

            const mine = request.assigned_to === userId;
            const deptMatch = !!request.assigned_department_id && userDepartmentIds.includes(request.assigned_department_id);
            const noDeptScope = userDepartmentIds.length === 0;
            if (!mine && !deptMatch && !noDeptScope) return;

            const updatedTime = request.updated_datetime ? new Date(request.updated_datetime).getTime() : null;
            const wasUpdated = updatedTime !== null && Math.abs(updatedTime - requestTime) > 60 * 1000;

            // New request attached to you or your department
            if (requestAge < twentyFourHours) {
                if (!readItems.has(`new-${key}`)) count++;
            }
            // Recent status/activity update on a relevant request
            else if (wasUpdated && (now - (updatedTime as number)) < twentyFourHours * 2) {
                if (!readItems.has(`upd-${key}-${updatedTime}`)) count++;
            }
        });

        return count;
    }, [requests, userId, userDepartmentIds, readItems]);
}
