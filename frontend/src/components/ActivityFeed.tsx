import { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Bell, MessageSquare, UserPlus, AlertCircle, Clock, ChevronRight, Building2 } from 'lucide-react';
import { ServiceRequest } from '../types';

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

    // Generate feed items from requests
    const feedItems = useMemo<FeedItem[]>(() => {
        const items: FeedItem[] = [];
        const now = Date.now();
        const twentyFourHours = 24 * 60 * 60 * 1000;
        const sevenDays = 7 * 24 * 60 * 60 * 1000;

        requests.forEach(request => {
            const requestTime = new Date(request.requested_datetime).getTime();
            const requestAge = now - requestTime;

            // Skip old requests
            if (requestAge > sevenDays) return;

            // New request in user's department (< 24 hours)
            if (requestAge < twentyFourHours) {
                if (request.assigned_department_id && userDepartmentIds.includes(request.assigned_department_id)) {
                    items.push({
                        id: `new-${request.service_request_id}`,
                        type: 'new_request',
                        title: `New: ${request.service_name}`,
                        description: request.description?.substring(0, 80) + (request.description && request.description.length > 80 ? '...' : '') || 'No description',
                        timestamp: new Date(request.requested_datetime),
                        request,
                        isNew: !readItems.has(`new-${request.service_request_id}`)
                    });
                }
            }

            // Assigned to me
            if (request.assigned_to === userId) {
                const updateTime = request.updated_datetime ? new Date(request.updated_datetime).getTime() : requestTime;
                if (now - updateTime < twentyFourHours) {
                    items.push({
                        id: `assigned-${request.service_request_id}`,
                        type: 'assigned_to_me',
                        title: `Assigned to you: ${request.service_name}`,
                        description: `Request #${request.service_request_id}`,
                        timestamp: request.updated_datetime ? new Date(request.updated_datetime) : new Date(request.requested_datetime),
                        request,
                        isNew: !readItems.has(`assigned-${request.service_request_id}`)
                    });
                }
            }

            // Requests in my department that are unassigned
            if (request.assigned_department_id &&
                userDepartmentIds.includes(request.assigned_department_id) &&
                !request.assigned_to &&
                requestAge < twentyFourHours * 3) {
                items.push({
                    id: `dept-${request.service_request_id}`,
                    type: 'assigned_to_dept',
                    title: `Needs attention: ${request.service_name}`,
                    description: 'Assigned to your department but no individual owner',
                    timestamp: new Date(request.requested_datetime),
                    request,
                    isNew: !readItems.has(`dept-${request.service_request_id}`)
                });
            }
        });

        // Sort by timestamp, newest first
        items.sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime());

        return items.slice(0, 50); // Limit to 50 items
    }, [requests, userId, userDepartmentIds, readItems]);

    const unreadCount = feedItems.filter(item => item.isNew).length;

    const markAsRead = (itemId: string) => {
        const newRead = new Set(readItems);
        newRead.add(itemId);
        setReadItems(newRead);
        localStorage.setItem('activityFeedRead', JSON.stringify([...newRead]));
    };

    const markAllAsRead = () => {
        const newRead = new Set([...readItems, ...feedItems.map(item => item.id)]);
        setReadItems(newRead);
        localStorage.setItem('activityFeedRead', JSON.stringify([...newRead]));
    };

    const handleItemClick = (item: FeedItem) => {
        markAsRead(item.id);
        onSelectRequest(item.request);
        onClose();
    };

    const getItemIcon = (type: FeedItem['type']) => {
        switch (type) {
            case 'new_request':
                return <AlertCircle className="w-4 h-4 text-emerald-400" />;
            case 'assigned_to_me':
                return <UserPlus className="w-4 h-4 text-primary-400" />;
            case 'assigned_to_dept':
                return <Building2 className="w-4 h-4 text-purple-400" />;
            case 'status_change':
                return <Clock className="w-4 h-4 text-amber-400" />;
            case 'new_comment':
                return <MessageSquare className="w-4 h-4 text-blue-400" />;
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
            <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="fixed inset-0 bg-black/60 backdrop-blur-sm z-50"
                onClick={onClose}
            >
                <motion.div
                    initial={{ x: -320, opacity: 0 }}
                    animate={{ x: 0, opacity: 1 }}
                    exit={{ x: -320, opacity: 0 }}
                    transition={{ type: 'spring', damping: 25, stiffness: 300 }}
                    onClick={(e) => e.stopPropagation()}
                    className="absolute left-0 top-0 bottom-0 w-full max-w-sm bg-slate-900 border-r border-white/10 shadow-2xl flex flex-col"
                >
                    {/* Header */}
                    <div className="p-4 border-b border-white/10 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                            <div className="w-10 h-10 rounded-full bg-primary-500/20 flex items-center justify-center">
                                <Bell className="w-5 h-5 text-primary-400" />
                            </div>
                            <div>
                                <h2 className="text-lg font-semibold text-white">Activity Feed</h2>
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
                                <Bell className="w-12 h-12 text-white/20 mx-auto mb-4" />
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
                                        <ChevronRight className="w-4 h-4 text-white/20 flex-shrink-0 mt-1" />
                                    </button>
                                ))}
                            </div>
                        )}
                    </div>
                </motion.div>
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

        requests.forEach(request => {
            const requestTime = new Date(request.requested_datetime).getTime();
            const requestAge = now - requestTime;

            if (requestAge < twentyFourHours) {
                if (request.assigned_department_id && userDepartmentIds.includes(request.assigned_department_id)) {
                    if (!readItems.has(`new-${request.service_request_id}`)) count++;
                }
            }

            if (request.assigned_to === userId) {
                const updateTime = request.updated_datetime ? new Date(request.updated_datetime).getTime() : requestTime;
                if (now - updateTime < twentyFourHours) {
                    if (!readItems.has(`assigned-${request.service_request_id}`)) count++;
                }
            }
        });

        return count;
    }, [requests, userId, userDepartmentIds, readItems]);
}
