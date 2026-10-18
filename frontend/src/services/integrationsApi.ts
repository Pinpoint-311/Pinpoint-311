/**
 * Town-system mapping and failed-sync calls.
 *
 * Kept beside api.ts rather than inside it so this screen's calls can grow
 * without touching the shared client. Requests go through the shared client's
 * own `request` helper, so they carry the same session header, the same
 * auto-logout on an expired session, and the same error shape as every other
 * call in the app.
 */
import { api } from './api';
import type { ServiceDefinition } from '../types';

type RequestFn = <T>(endpoint: string, options?: RequestInit) => Promise<T>;

// Element access reaches the client's private helper without widening its
// public surface; bound so `this` (and the session token) is the shared client.
const request: RequestFn = <T,>(endpoint: string, options?: RequestInit): Promise<T> =>
    (api['request'] as RequestFn).call(api, endpoint, options) as Promise<T>;

export interface LookupItem {
    code: string;
    name: string;
}

/** The vendor's own lists, as the last refresh found them. */
export interface IntegrationLookups {
    services?: LookupItem[];
    statuses?: LookupItem[];
    fields?: LookupItem[];
    _source?: Record<string, string>;
    [list: string]: LookupItem[] | Record<string, string> | undefined;
}

export interface LookupsRefreshResult {
    ok: boolean;
    supported?: boolean;
    detail?: string;
    lookups?: IntegrationLookups;
    fetched_at?: string;
}

export interface MappingSave {
    status_map_out?: Record<string, string>;
    status_map_in?: Record<string, string>;
    service_code_map_out?: Record<string, string>;
    service_code_map_in?: Record<string, string>;
    field_map?: Record<string, string>;
    attribute_map?: Record<string, string>;
    share_pii?: boolean;
    import_new_records?: boolean;
}

export interface BacklogItem {
    id: number;
    operation: 'push' | 'push_status' | 'push_comment' | string;
    request_id: string | null;
    comment_id: number | null;
    attempts: number;
    last_error: string | null;
    first_failed_at: string | null;
    last_attempt_at: string | null;
    next_attempt_at: string | null;
    stalled: boolean;
    resolved_at: string | null;
    resolution: string | null;
    resolution_note: string | null;
}

export interface SyncProblems {
    link_errors: {
        request_id: string;
        external_id: string;
        pending: boolean;
        error: string | null;
        last_pushed_at: string | null;
    }[];
    warnings: { id: number; operation: string; detail: string | null; created_at: string | null }[];
}

export const integrationsApi = {
    refreshLookups(id: number): Promise<LookupsRefreshResult> {
        return request<LookupsRefreshResult>(`/integrations/${id}/lookups/refresh`, { method: 'POST' });
    },

    saveMapping<T = unknown>(id: number, body: MappingSave): Promise<T> {
        return request<T>(`/integrations/${id}/mapping`, {
            method: 'POST',
            body: JSON.stringify(body),
        });
    },

    getBacklog(id: number): Promise<BacklogItem[]> {
        return request<BacklogItem[]>(`/integrations/${id}/backlog`);
    },

    retryBacklogItem(id: number, itemId: number): Promise<{ ok: boolean; started?: boolean; detail: string }> {
        return request(`/integrations/${id}/backlog/${itemId}/retry`, { method: 'POST' });
    },

    discardBacklogItem(id: number, itemId: number, reason: string): Promise<{ ok: boolean; detail: string }> {
        return request(`/integrations/${id}/backlog/${itemId}/discard`, {
            method: 'POST',
            body: JSON.stringify({ reason }),
        });
    },

    getSyncProblems(id: number): Promise<SyncProblems> {
        return request<SyncProblems>(`/integrations/${id}/sync-problems`);
    },

    /** This town's categories, the left-hand side of every category mapping.
     *  The admin list, so a category hidden from the public is still mappable. */
    getCategories(): Promise<ServiceDefinition[]> {
        return request<ServiceDefinition[]>('/services/all');
    },
};
