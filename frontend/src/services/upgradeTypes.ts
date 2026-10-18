/** Secure upgrades (docs/design/secure-upgrades.md, Phase 3): what the console
 *  shows about the host updater, the releases it verified, and the requests
 *  admins file for it. Mirrors backend/app/services/upgrades.py. */

export type UpgradeAction = 'upgrade' | 'rollback' | 'restart';

export type UpgradeStatus =
    | 'pending_approval' | 'approved' | 'claimed' | 'running'
    | 'succeeded' | 'failed' | 'rolled_back' | 'needs_approval' | 'cancelled' | 'refused';

export interface UpdaterState {
    connected: boolean;
    last_seen_at: string | null;
    version: string | null;
    /** What release.lock says runs: image references by digest. */
    current: { version?: string; backend?: string; frontend?: string } | null;
    require_two_person_approval: boolean;
}

export interface UpdaterRelease {
    tag: string;
    version: string | null;
    name: string | null;
    published_at: string | null;
    notes: string | null;
    url: string | null;
    prerelease: boolean;
    /** null = the updater did not check this one. */
    signature_verified: boolean | null;
    gate_passed: boolean | null;
    attested: boolean | null;
    db_revision: string | null;
    min_db_revision: string | null;
    compatible_with_this_instance: boolean | null;
    compatibility_detail: string | null;
    backend_digest: string | null;
    frontend_digest: string | null;
    reported_at: string | null;
    requestable: boolean;
    refusal: string | null;
    current: boolean;
}

export interface UpgradeStep {
    step: string;
    status: string;
    detail: string | null;
    at: string | null;
}

export interface UpgradeRequestRecord {
    id: number;
    action: UpgradeAction;
    target_tag: string | null;
    reason: string;
    requested_by: string;
    requested_at: string | null;
    scheduled_for: string | null;
    status: UpgradeStatus;
    approved_by: string | null;
    approved_at: string | null;
    cancelled_by: string | null;
    claimed_at: string | null;
    finished_at: string | null;
    outcome: string | null;
    outcome_summary: string | null;
    allow_destructive: boolean;
    can_approve?: boolean;
    approve_blocked_reason?: string | null;
    can_cancel?: boolean;
    can_mark_failed?: boolean;
    last_report_at?: string | null;
    steps?: UpgradeStep[];
}

export interface CurrentVersion {
    version: string | null;
    git_sha: string | null;
    sha: string;
    tag: string | null;
    display: string;
    backend_image: string | null;
    frontend_image: string | null;
    backend_digest: string | null;
    frontend_digest: string | null;
    db_revision: string | null;
    min_db_revision: string | null;
}

export interface UpdaterTokenRecord {
    id: number;
    label: string | null;
    token_prefix: string;
    created_by: string | null;
    created_at: string | null;
    last_used_at: string | null;
    revoked_at: string | null;
    revoked_by: string | null;
    status: 'active' | 'revoked';
    /** Only in the create response, once. */
    token?: string;
}

export interface NewUpgradeRequest {
    action: UpgradeAction;
    target_tag?: string | null;
    reason: string;
    scheduled_for?: string | null;
    allow_destructive?: boolean;
}

export const ACTIVE_UPGRADE_STATUSES: UpgradeStatus[] = ['pending_approval', 'approved', 'claimed', 'running'];
export const IN_FLIGHT_UPGRADE_STATUSES: UpgradeStatus[] = ['claimed', 'running'];
