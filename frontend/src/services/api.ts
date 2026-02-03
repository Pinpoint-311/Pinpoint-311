import {
    AuthToken,
    User,
    ServiceDefinition,
    ServiceRequest,
    ServiceRequestDetail,
    ServiceRequestCreate,
    ManualIntakeCreate,
    SystemSettings,
    SystemSecret,
    Statistics,
    AdvancedStatistics,
    UserCreate,
    ServiceCreate,
    Department,
    RequestComment,
    PublicServiceRequest,
} from '../types';

const API_BASE = '/api';

class ApiClient {
    private token: string | null = null;

    setToken(token: string | null) {
        this.token = token;
    }

    private async request<T>(
        endpoint: string,
        options: RequestInit = {}
    ): Promise<T> {
        const headers: Record<string, string> = {
            'Content-Type': 'application/json',
            ...(options.headers as Record<string, string> || {}),
        };

        if (this.token) {
            headers['Authorization'] = `Bearer ${this.token}`;
        }

        // Add Accept-Language header for automatic backend translation
        // Must match the LANGUAGE_STORAGE_KEY in TranslationContext.tsx
        const preferredLanguage = localStorage.getItem('preferred_language') || 'en';
        headers['Accept-Language'] = preferredLanguage;

        const response = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers,
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Request failed' }));
            // Handle FastAPI validation errors (422)
            if (error.detail && Array.isArray(error.detail)) {
                const messages = error.detail.map((e: any) => e.msg || e.message || JSON.stringify(e)).join(', ');
                throw new Error(messages || 'Validation error');
            }
            throw new Error(error.detail || error.message || 'Request failed');
        }

        if (response.status === 204) {
            return undefined as T;
        }

        return response.json();
    }

    // Auth
    async login(username: string, password: string): Promise<AuthToken> {
        const formData = new URLSearchParams();
        formData.append('username', username);
        formData.append('password', password);

        const response = await fetch(`${API_BASE}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: formData,
        });

        if (!response.ok) {
            const error = await response.json().catch(() => ({ detail: 'Login failed' }));
            throw new Error(error.detail || 'Login failed');
        }

        return response.json();
    }

    async getMe(): Promise<User> {
        return this.request<User>('/auth/me');
    }

    // Services (Public)
    async getServices(): Promise<ServiceDefinition[]> {
        return this.request<ServiceDefinition[]>('/services/');
    }

    // Services (Admin)
    async createService(data: ServiceCreate): Promise<ServiceDefinition> {
        return this.request<ServiceDefinition>('/services/', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async deleteService(id: number): Promise<void> {
        return this.request<void>(`/services/${id}`, { method: 'DELETE' });
    }

    async updateService(id: number, data: Partial<ServiceDefinition>): Promise<ServiceDefinition> {
        return this.request<ServiceDefinition>(`/services/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    // Departments
    async getDepartments(): Promise<Department[]> {
        return this.request<Department[]>('/departments/');
    }

    async createDepartment(data: Partial<Department>): Promise<Department> {
        return this.request<Department>('/departments/', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async updateDepartment(id: number, data: Partial<Department>): Promise<Department> {
        return this.request<Department>(`/departments/${id}`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async deleteDepartment(id: number): Promise<void> {
        return this.request<void>(`/departments/${id}`, { method: 'DELETE' });
    }

    // Service Requests (Public)
    async createRequest(data: ServiceRequestCreate): Promise<ServiceRequest> {
        return this.request<ServiceRequest>('/open311/v2/requests.json', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async getPublicRequests(status?: string, serviceCode?: string): Promise<PublicServiceRequest[]> {
        const params = new URLSearchParams();
        if (status) params.append('status', status);
        if (serviceCode) params.append('service_code', serviceCode);
        const queryString = params.toString() ? `?${params.toString()}` : '';
        return this.request<PublicServiceRequest[]>(`/open311/v2/public/requests${queryString}`);
    }

    async getPublicRequestDetail(requestId: string): Promise<PublicServiceRequest> {
        return this.request<PublicServiceRequest>(`/open311/v2/public/requests/${requestId}`);
    }

    async getPublicComments(requestId: string): Promise<RequestComment[]> {
        return this.request<RequestComment[]>(`/open311/v2/public/requests/${requestId}/comments`);
    }

    async addPublicComment(requestId: string, content: string): Promise<RequestComment> {
        return this.request<RequestComment>(`/open311/v2/public/requests/${requestId}/comments?content=${encodeURIComponent(content)}`, {
            method: 'POST',
        });
    }

    // Service Requests (Staff)
    async getRequests(status?: string, includeDeleted?: boolean): Promise<ServiceRequest[]> {
        const params = new URLSearchParams();
        if (status) params.append('status', status);
        if (includeDeleted) params.append('include_deleted', 'true');
        const queryString = params.toString() ? `?${params.toString()}` : '';
        return this.request<ServiceRequest[]>(`/open311/v2/requests.json${queryString}`);
    }

    async getRequestDetail(requestId: string): Promise<ServiceRequestDetail> {
        return this.request<ServiceRequestDetail>(`/open311/v2/requests/${requestId}.json`);
    }

    async updateRequest(
        requestId: string,
        data: {
            status?: string;
            staff_notes?: string;
            priority?: number;
            assigned_department_id?: number;
            assigned_to?: string;
            closed_substatus?: string;
            completion_message?: string;
            completion_photo_url?: string;
            manual_priority_score?: number | null;
            flagged?: boolean;
        }
    ): Promise<ServiceRequestDetail> {
        return this.request<ServiceRequestDetail>(`/open311/v2/requests/${requestId}/status`, {
            method: 'PUT',
            body: JSON.stringify(data),
        });
    }

    async deleteRequest(requestId: string, justification: string): Promise<void> {
        return this.request<void>(`/open311/v2/requests/${requestId}`, {
            method: 'DELETE',
            body: JSON.stringify({ justification }),
        });
    }

    async restoreRequest(requestId: string): Promise<{ message: string }> {
        return this.request<{ message: string }>(`/open311/v2/requests/${requestId}/restore`, {
            method: 'POST',
            body: JSON.stringify({}),
        });
    }

    async acceptAiPriority(requestId: string): Promise<{ message: string; priority_score: number }> {
        return this.request<{ message: string; priority_score: number }>(`/open311/v2/requests/${requestId}/accept-ai-priority`, {
            method: 'POST',
            body: JSON.stringify({}),
        });
    }

    async createManualIntake(data: ManualIntakeCreate): Promise<ServiceRequest> {
        return this.request<ServiceRequest>('/open311/v2/requests/manual', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    // Request Comments
    async getComments(requestId: number): Promise<RequestComment[]> {
        return this.request<RequestComment[]>(`/requests/${requestId}/comments`);
    }

    async createComment(
        requestId: number,
        content: string,
        visibility: 'internal' | 'external' = 'internal'
    ): Promise<RequestComment> {
        return this.request<RequestComment>(`/requests/${requestId}/comments`, {
            method: 'POST',
            body: JSON.stringify({ content, visibility }),
        });
    }

    async deleteComment(requestId: number, commentId: number): Promise<void> {
        return this.request<void>(`/requests/${requestId}/comments/${commentId}`, {
            method: 'DELETE',
        });
    }

    // Audit Log (Staff)
    async getAuditLog(requestId: string): Promise<import('../types').AuditLogEntry[]> {
        return this.request<import('../types').AuditLogEntry[]>(`/open311/v2/requests/${requestId}/audit-log`);
    }

    // Audit Log (Public)
    async getPublicAuditLog(requestId: string): Promise<import('../types').AuditLogEntry[]> {
        return this.request<import('../types').AuditLogEntry[]>(`/open311/v2/public/requests/${requestId}/audit-log`);
    }

    // Users (Admin)
    async getUsers(): Promise<User[]> {
        return this.request<User[]>('/users/');
    }

    // Staff members (accessible by any staff user)
    async getStaffMembers(): Promise<User[]> {
        return this.request<User[]>('/users/staff');
    }

    // Public staff list (no auth required, for resident portal filters)
    async getPublicStaffList(): Promise<User[]> {
        return this.request<User[]>('/users/staff/public');
    }

    async createUser(data: UserCreate): Promise<User> {
        return this.request<User>('/users/', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async deleteUser(id: number): Promise<void> {
        return this.request<void>(`/users/${id}`, { method: 'DELETE' });
    }

    async resetUserPassword(id: number, newPassword: string): Promise<User> {
        return this.request<User>(`/users/${id}/reset-password-json`, {
            method: 'POST',
            body: JSON.stringify({ new_password: newPassword }),
        });
    }

    // System Settings
    async getSettings(): Promise<SystemSettings> {
        return this.request<SystemSettings>('/system/settings');
    }

    async updateSettings(data: Partial<SystemSettings>): Promise<SystemSettings> {
        return this.request<SystemSettings>('/system/settings', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    // System Secrets (Admin)
    async getSecrets(): Promise<SystemSecret[]> {
        return this.request<SystemSecret[]>('/system/secrets');
    }

    async updateSecret(keyName: string, value: string): Promise<SystemSecret> {
        return this.request<SystemSecret>('/system/secrets', {
            method: 'POST',
            body: JSON.stringify({ key_name: keyName, key_value: value }),
        });
    }

    async syncSecrets(): Promise<{ status: string; added_secrets: string[]; count: number }> {
        return this.request('/system/secrets/sync', { method: 'POST' });
    }

    // Statistics
    async getStatistics(): Promise<Statistics> {
        return this.request<Statistics>('/system/statistics');
    }

    // Advanced Statistics (PostGIS-powered)
    async getAdvancedStatistics(): Promise<AdvancedStatistics> {
        return this.request<AdvancedStatistics>('/system/advanced-statistics');
    }

    // System Update (Admin)
    async updateSystem(): Promise<{ status: string; message: string }> {
        return this.request<{ status: string; message: string }>('/system/update', {
            method: 'POST',
        });
    }

    // Domain Configuration (Admin)
    async configureDomain(domain: string): Promise<{
        status: string;
        message: string;
        domain?: string;
        url?: string;
        reload_success?: boolean;
        next_step?: string | null;
    }> {
        return this.request(`/system/domain/configure?domain=${encodeURIComponent(domain)}`, {
            method: 'POST',
        });
    }

    async getDomainStatus(): Promise<{
        configured_domains: Array<{ domain: string; has_ssl: boolean }>;
        server_ip: string;
    }> {
        return this.request('/system/domain/status');
    }

    // GIS / Maps
    async getMapsConfig(): Promise<{
        has_google_maps: boolean;
        google_maps_api_key: string | null;
        township_boundary: object | null;
        default_center: { lat: number; lng: number };
        default_zoom: number;
    }> {
        return this.request('/gis/config');
    }

    async searchOsmTownship(query: string): Promise<{
        results: Array<{
            osm_id: number;
            display_name: string;
            type: string;
            class: string;
            lat: string;
            lon: string;
            boundingbox: string[];
            geojson?: object;  // Boundary GeoJSON from Nominatim polygon_geojson=1
        }>;
    }> {
        return this.request(`/gis/osm/search?query=${encodeURIComponent(query)}`);
    }


    async fetchOsmBoundary(osmId: number): Promise<{
        geojson: object;
        osm_id: number;
    }> {
        return this.request(`/gis/osm/boundary/${osmId}`);
    }

    async saveTownshipBoundary(geojsonData: object, name?: string, centerLat?: number, centerLng?: number): Promise<{
        status: string;
        message: string;
    }> {
        const params = new URLSearchParams();
        if (name) params.append('name', name);
        if (centerLat !== undefined && centerLng !== undefined) {
            params.append('center_lat', centerLat.toString());
            params.append('center_lng', centerLng.toString());
        }
        const queryString = params.toString();
        const url = queryString ? `/gis/township-boundary?${queryString}` : '/gis/township-boundary';
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(geojsonData),
        });
    }


    async geocodeAddress(address: string): Promise<{
        lat: number;
        lng: number;
        formatted_address: string;
        place_id?: string;
    }> {
        return this.request(`/gis/geocode?address=${encodeURIComponent(address)}`);
    }

    async reverseGeocode(lat: number, lng: number): Promise<{
        lat: number;
        lng: number;
        formatted_address: string;
    }> {
        return this.request(`/gis/reverse-geocode?lat=${lat}&lng=${lng}`);
    }


    async searchCensusBoundary(townName: string, stateAbbr: string, layerType: string = 'township'): Promise<{
        results: Array<{
            name: string;
            full_name: string;
            geoid: string;
            state: string;
            layer_type: string;
            geometry: any;
        }>;
        message?: string;
    }> {
        return this.request(`/gis/census-boundary-search?town_name=${encodeURIComponent(townName)}&state_abbr=${stateAbbr}&layer_type=${layerType}`);
    }

    async saveCensusBoundary(name: string, geometry: any): Promise<{ status: string; message: string }> {
        return this.request(`/gis/boundaries/save-census?name=${encodeURIComponent(name)}`, {
            method: 'POST',
            body: JSON.stringify(geometry),
        });
    }

    // ========== Map Layers ==========

    async getMapLayers(): Promise<MapLayer[]> {
        return this.request('/map-layers/');
    }

    async getAllMapLayers(): Promise<MapLayer[]> {
        return this.request('/map-layers/all');
    }

    async createMapLayer(layerData: {
        name: string;
        description?: string;
        layer_type?: string;
        fill_color?: string;
        stroke_color?: string;
        fill_opacity?: number;
        stroke_width?: number;
        service_codes?: string[];
        geojson: object;
        routing_mode?: string;
        routing_config?: object | null;
        visible_on_map?: boolean;
    }): Promise<MapLayer> {
        return this.request('/map-layers/', {
            method: 'POST',
            body: JSON.stringify(layerData),
        });
    }

    async updateMapLayer(layerId: number, layerData: {
        name?: string;
        description?: string;
        layer_type?: string;
        fill_color?: string;
        stroke_color?: string;
        fill_opacity?: number;
        stroke_width?: number;
        is_active?: boolean;
        service_codes?: string[];
        geojson?: object;
        routing_mode?: string;
        routing_config?: object | null;
        visible_on_map?: boolean;
    }): Promise<MapLayer> {
        return this.request(`/map-layers/${layerId}`, {
            method: 'PUT',
            body: JSON.stringify(layerData),
        });
    }

    async deleteMapLayer(layerId: number): Promise<void> {
        return this.request(`/map-layers/${layerId}`, {
            method: 'DELETE',
        });
    }

    // Image Upload
    async uploadImage(file: File): Promise<{ url: string; filename: string }> {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`${API_BASE}/system/upload/image`, {
            method: 'POST',
            headers: this.token ? { Authorization: `Bearer ${this.token}` } : {},
            body: formData,
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || 'Upload failed');
        }

        return response.json();
    }

    // Asset Related Requests
    async getAssetRelatedRequests(assetId: string, excludeRequestId?: string): Promise<{
        service_request_id: string;
        service_name: string;
        status: string;
        requested_datetime: string;
        address: string;
        description: string;
    }[]> {
        const params = new URLSearchParams();
        if (excludeRequestId) params.append('exclude_request_id', excludeRequestId);
        const queryString = params.toString() ? `?${params.toString()}` : '';
        return this.request(`/open311/v2/requests/asset/${encodeURIComponent(assetId)}/related${queryString}`);
    }

    // Notification Preferences
    async getNotificationPreferences(): Promise<NotificationPreferences> {
        return this.request<NotificationPreferences>('/users/me/notification-preferences');
    }

    async updateNotificationPreferences(prefs: Partial<NotificationPreferences>): Promise<NotificationPreferences> {
        return this.request<NotificationPreferences>('/users/me/notification-preferences', {
            method: 'PUT',
            body: JSON.stringify(prefs),
        });
    }

    // Research Suite endpoints
    async getResearchStatus(): Promise<ResearchStatus> {
        return this.request<ResearchStatus>('/research/status');
    }

    async getResearchAnalytics(params?: { start_date?: string; end_date?: string; service_code?: string }): Promise<ResearchAnalytics> {
        const queryParams = new URLSearchParams();
        if (params?.start_date) queryParams.append('start_date', params.start_date);
        if (params?.end_date) queryParams.append('end_date', params.end_date);
        if (params?.service_code) queryParams.append('service_code', params.service_code);
        const queryString = queryParams.toString() ? `?${queryParams.toString()}` : '';
        return this.request<ResearchAnalytics>(`/research/analytics${queryString}`);
    }

    async getResearchCodeSnippets(): Promise<ResearchCodeSnippets> {
        return this.request<ResearchCodeSnippets>('/research/code-snippets');
    }

    async exportResearchCSV(params?: { start_date?: string; end_date?: string; service_code?: string; privacy_mode?: string }): Promise<Blob> {
        const queryParams = new URLSearchParams();
        if (params?.start_date) queryParams.append('start_date', params.start_date);
        if (params?.end_date) queryParams.append('end_date', params.end_date);
        if (params?.service_code) queryParams.append('service_code', params.service_code);
        if (params?.privacy_mode) queryParams.append('privacy_mode', params.privacy_mode);
        const queryString = queryParams.toString() ? `?${queryParams.toString()}` : '';

        const response = await fetch(`${API_BASE}/research/export/csv${queryString}`, {
            headers: this.token ? { 'Authorization': `Bearer ${this.token}` } : {},
        });
        if (!response.ok) throw new Error('Export failed');
        return response.blob();
    }

    async exportResearchGeoJSON(params?: { start_date?: string; end_date?: string; service_code?: string; privacy_mode?: string }): Promise<Blob> {
        const queryParams = new URLSearchParams();
        if (params?.start_date) queryParams.append('start_date', params.start_date);
        if (params?.end_date) queryParams.append('end_date', params.end_date);
        if (params?.service_code) queryParams.append('service_code', params.service_code);
        if (params?.privacy_mode) queryParams.append('privacy_mode', params.privacy_mode);
        const queryString = queryParams.toString() ? `?${queryParams.toString()}` : '';

        const response = await fetch(`${API_BASE}/research/export/geojson${queryString}`, {
            headers: this.token ? { 'Authorization': `Bearer ${this.token}` } : {},
        });
        if (!response.ok) throw new Error('Export failed');
        return response.blob();
    }

    async exportDataDictionary(): Promise<Blob> {
        const response = await fetch(`${API_BASE}/research/export/data-dictionary`, {
            headers: this.token ? { 'Authorization': `Bearer ${this.token}` } : {},
        });
        if (!response.ok) throw new Error('Export failed');
        return response.blob();
    }

    // ========== Document Retention ==========

    async getRetentionStates(): Promise<RetentionState[]> {
        return this.request<RetentionState[]>('/system/retention/states');
    }

    async getRetentionPolicy(): Promise<RetentionPolicyConfig> {
        return this.request<RetentionPolicyConfig>('/system/retention/policy');
    }

    async updateRetentionPolicy(params: {
        state_code?: string;
        override_days?: number;
        mode?: 'anonymize' | 'delete';
    }): Promise<{ status: string; state_code: string; override_days: number | null; mode: string }> {
        const queryParams = new URLSearchParams();
        if (params.state_code) queryParams.append('state_code', params.state_code);
        if (params.override_days !== undefined) queryParams.append('override_days', params.override_days.toString());
        if (params.mode) queryParams.append('mode', params.mode);
        return this.request(`/system/retention/policy?${queryParams.toString()}`, { method: 'POST' });
    }

    async runRetentionNow(): Promise<{ status: string; task_id: string; message: string }> {
        return this.request('/system/retention/run', { method: 'POST' });
    }

    async getLegalHoldRequests(): Promise<{
        count: number;
        requests: Array<{
            id: number;
            service_request_id: string;
            service_name: string;
            description: string;
            status: string;
            address: string;
            requested_datetime: string;
            closed_datetime: string | null;
        }>;
    }> {
        return this.request('/system/retention/legal-hold');
    }

    async exportForPublicRecords(startDate?: string, endDate?: string): Promise<void> {
        const params = new URLSearchParams();
        if (startDate) params.append('start_date', startDate);
        if (endDate) params.append('end_date', endDate);
        const queryString = params.toString() ? `?${params.toString()}` : '';

        const response = await fetch(`/api/system/retention/export${queryString}`, {
            headers: this.token ? { 'Authorization': `Bearer ${this.token}` } : {},
        });

        if (!response.ok) throw new Error('Export failed');

        // Trigger download
        const blob = await response.blob();
        const contentDisposition = response.headers.get('Content-Disposition');
        const filename = contentDisposition?.match(/filename=(.+)/)?.[1] || 'public_records_export.csv';
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        window.URL.revokeObjectURL(url);
    }

    // ========== Database Backups ==========

    async getBackupStatus(): Promise<BackupStatus> {
        return this.request<BackupStatus>('/system/backups/status');
    }

    async listBackups(): Promise<BackupList> {
        return this.request<BackupList>('/system/backups');
    }

    async createBackup(): Promise<BackupResult> {
        return this.request<BackupResult>('/system/backups/create', { method: 'POST' });
    }

    async deleteBackup(backupName: string): Promise<{ status: string; deleted: string }> {
        return this.request(`/system/backups/${encodeURIComponent(backupName)}`, { method: 'DELETE' });
    }

    async cleanupBackups(): Promise<{ status: string; deleted_count: number; deleted: string[] }> {
        return this.request('/system/backups/cleanup', { method: 'POST' });
    }

    // ========== Setup Wizard ==========

    async getSetupStatus(): Promise<{
        auth0_configured: boolean;
        gcp_configured: boolean;
        auth0_details?: any;
        gcp_details?: any;
    }> {
        return this.request('/setup/status');
    }

    async configureAuth0(data: {
        domain: string;
        management_client_id: string;
        management_client_secret: string;
        callback_url: string;
    }): Promise<{
        success: boolean;
        message: string;
        domain: string;
        client_id: string;
    }> {
        return this.request('/setup/auth0/configure', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async configureGCP(data: {
        project_id: string;
        service_account_json: string;
    }): Promise<{
        success: boolean;
        message: string;
        project_id: string;
    }> {
        return this.request('/setup/gcp/configure', {
            method: 'POST',
            body: JSON.stringify(data),
        });
    }

    async verifySetup(): Promise<{
        auth0: { configured: boolean; reachable: boolean; error: string | null; domain?: string };
        gcp: { configured: boolean; reachable: boolean; error: string | null };
    }> {
        return this.request('/setup/verify', { method: 'POST' });
    }

    // ========== Health Dashboard & Runbook (Bus Factor Mitigation) ==========

    async getHealthDashboard(): Promise<HealthDashboard> {
        return this.request<HealthDashboard>('/system/health-dashboard');
    }

    async executeRunbook(action: string, backupName?: string): Promise<RunbookResult> {
        const params = backupName ? `?backup_name=${encodeURIComponent(backupName)}` : '';
        return this.request<RunbookResult>(`/system/runbook/${action}${params}`, { method: 'POST' });
    }

    // ========== Secret Manager Migration ==========

    async migrateToSecretManager(): Promise<{
        status: string;
        migrated: number;
        migrated_keys: string[];
        scrubbed: number;
        scrubbed_keys: string[];
        skipped: number;
        skipped_keys: string[];
        failed: number;
        failed_keys: Array<{ key: string; error: string }>;
        reason?: string;
        error?: string;
    }> {
        return this.request('/system/secrets/migrate-to-secret-manager', { method: 'POST' });
    }

    // ========== Uptime Monitoring ==========

    async getUptimeHistory(hours: number = 24): Promise<UptimeHistory> {
        return this.request<UptimeHistory>(`/health/uptime/history?hours=${hours}`);
    }

    async getUptimeStats(): Promise<UptimeStats> {
        return this.request<UptimeStats>('/health/uptime/stats');
    }

    async triggerUptimeCheck(): Promise<{
        checked: number;
        results: Record<string, { status: string; response_time_ms: number }>;
    }> {
        return this.request('/health/uptime/check-now', { method: 'POST' });
    }

}


// Notification Preferences type
export interface NotificationPreferences {
    email_new_requests: boolean;
    email_status_changes: boolean;
    email_comments: boolean;
    email_assigned_only: boolean;
    sms_new_requests: boolean;
    sms_status_changes: boolean;
    phone: string | null;
}

// Research Suite types
export interface ResearchAnalytics {
    total_requests: number;
    status_distribution: Record<string, number>;
    avg_resolution_hours: number | null;
    category_distribution: Array<{ code: string; name: string; count: number }>;
    source_distribution: Record<string, number>;
    filters_applied: {
        start_date: string | null;
        end_date: string | null;
        service_code: string | null;
    };
}

export interface ResearchCodeSnippets {
    python: string;
    r: string;
}

export interface ResearchStatus {
    enabled: boolean;
    user: string;
    role: string;
}

export const api = new ApiClient();
export default api;

// Type for MapLayer
export interface MapLayer {
    id: number;
    name: string;
    description?: string;
    layer_type?: string;
    fill_color: string;
    stroke_color: string;
    fill_opacity: number;
    stroke_width: number;
    geojson: object;
    is_active: boolean;
    show_on_resident_portal: boolean;
    service_codes?: string[];  // Categories this layer applies to (empty = all)
    routing_mode?: 'none' | 'log' | 'block';  // Polygon behavior
    visible_on_map?: boolean;  // Whether to render the layer visually
    routing_config?: {
        message?: string;
        contacts?: { name: string; phone: string; url: string }[];
    };
    created_at?: string;
    updated_at?: string;
}

// Document Retention types
export interface RetentionState {
    code: string;
    name: string;
    retention_days: number;
    retention_years: number;
    source: string;
    public_records_law: string;
}

export interface RetentionPolicyConfig {
    state_code: string;
    policy: {
        state_code: string;
        name: string;
        retention_days: number;
        retention_years: number;
        source: string;
        public_records_law: string;
    };
    override_days: number | null;
    effective_days: number;
    mode: 'anonymize' | 'delete';
    stats: {
        retention_policy: object;
        cutoff_date: string;
        eligible_for_archival: number;
        under_legal_hold: number;
        already_archived: number;
        next_run: string;
    };
}

// Database Backup types
export interface BackupStatus {
    configured: boolean;
    message?: string;
    required_secrets?: string[];
    optional_secrets?: string[];
    bucket?: string;
    endpoint?: string;
    last_backup?: {
        name: string;
        size_bytes: number;
        created_at: string;
        age_days: number;
    } | null;
    total_backups?: number;
    next_scheduled?: string;
}

export interface BackupList {
    status: string;
    count: number;
    message?: string;
    backups: Array<{
        name: string;
        size_bytes: number;
        created_at: string;
        age_days: number;
    }>;
}

export interface BackupResult {
    status: string;
    message?: string;
    backup_name?: string;
    size_bytes?: number;
    unencrypted_size_bytes?: number;
    created_at?: string;
    bucket?: string;
}

// Health Dashboard (Bus Factor Mitigation)
export interface HealthDashboard {
    timestamp: string;
    overall_status: 'healthy' | 'degraded' | 'critical';
    services: Record<string, {
        status: 'running' | 'stopped' | 'unknown';
        uptime?: string;
        error?: string;
    }>;
    database: {
        status: 'healthy' | 'error';
        size?: string;
        connections?: number;
        error?: string;
    };
    cache: {
        status: 'healthy' | 'error' | 'not_configured';
        used_memory?: string;
        connected_clients?: number;
        error?: string;
    };
    last_backup: {
        name?: string;
        created?: string;
        size?: string;
        status?: string;
    } | null;
}

export interface RunbookResult {
    action: string;
    executed_by: string;
    timestamp: string;
    status: 'success' | 'error' | 'timeout' | 'skipped';
    details: Record<string, unknown>;
}

// Uptime Monitoring types
export interface UptimeHistory {
    period_hours: number;
    since: string;
    services: Record<string, Array<{
        status: string;
        response_time_ms: number | null;
        error: string | null;
        checked_at: string;
    }>>;
}

export interface UptimeStats {
    services: Record<string, {
        '24h'?: { uptime_percent: number; checks: number; healthy: number };
        '7d'?: { uptime_percent: number; checks: number; healthy: number };
        '30d'?: { uptime_percent: number; checks: number; healthy: number };
    }>;
}
