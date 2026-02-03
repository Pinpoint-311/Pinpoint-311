import { ServiceRequestDetail, AuditLogEntry } from '../types';
import { Printer } from 'lucide-react';

interface PrintWorkOrderProps {
    request: ServiceRequestDetail;
    auditLog?: AuditLogEntry[];
    townshipName?: string;
    logoUrl?: string;
}

export default function PrintWorkOrder({ request, auditLog, townshipName, logoUrl }: PrintWorkOrderProps) {
    const handlePrint = () => {
        // Create a new window for printing
        const printWindow = window.open('', '_blank', 'width=800,height=600');
        if (!printWindow) return;

        const ai = request.ai_analysis as Record<string, any> | null;
        const priorityScore = request.manual_priority_score ?? ai?.priority_score ?? 5;
        const matchedAsset = (request as any).matched_asset;

        // Format date helper
        const formatDate = (dateStr: string | null) => {
            if (!dateStr) return 'N/A';
            return new Date(dateStr).toLocaleString();
        };

        // Priority label
        const getPriorityLabel = (score: number) => {
            if (score >= 9) return { label: 'CRITICAL', color: '#dc2626' };
            if (score >= 7) return { label: 'HIGH', color: '#ea580c' };
            if (score >= 4) return { label: 'MEDIUM', color: '#ca8a04' };
            return { label: 'LOW', color: '#16a34a' };
        };
        const priority = getPriorityLabel(priorityScore);

        // Determine if priority is AI suggested or staff confirmed
        const isManualPriority = request.manual_priority_score !== null && request.manual_priority_score !== undefined;
        const prioritySource = isManualPriority ? 'Staff Confirmed' : (ai?.priority_score ? 'AI Suggested' : 'Default');

        // Status label
        const getStatusLabel = (status: string, substatus: string | null) => {
            if (status === 'closed') {
                if (substatus === 'resolved') return 'RESOLVED';
                if (substatus === 'no_action') return 'NO ACTION NEEDED';
                if (substatus === 'third_party') return 'REFERRED';
                return 'CLOSED';
            }
            return status.toUpperCase().replace('_', ' ');
        };

        // SVG Icons for formal look
        const icons = {
            location: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/></svg>`,
            document: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>`,
            camera: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>`,
            brain: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-1.54"/><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-1.54"/></svg>`,
            link: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>`,
            list: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>`,
            user: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>`,
            check: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
            clipboard: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/><rect x="8" y="2" width="8" height="4" rx="1" ry="1"/></svg>`,
            alert: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
        };

        // Build photos HTML
        const photosHtml = request.media_urls?.length ? `
            <div class="section">
                <h3>${icons.camera} Photos (${request.media_urls.length})</h3>
                <div class="photos">
                    ${request.media_urls.map(url => `<img src="${url}" alt="Issue photo" />`).join('')}
                </div>
            </div>
        ` : '';

        // Build completion photo HTML
        const completionHtml = request.status === 'closed' && (request.completion_message || request.completion_photo_url) ? `
            <div class="section completion">
                <h3>${icons.check} Resolution</h3>
                ${request.completion_message ? `<p><strong>Message:</strong> ${request.completion_message}</p>` : ''}
                ${request.completion_photo_url ? `<img src="${request.completion_photo_url}" alt="Completion photo" style="max-height: 150px;" />` : ''}
            </div>
        ` : '';

        // Build AI analysis HTML - use correct field names with improved tag styling
        const qualitativeText = ai?.qualitative_analysis ?? request.vertex_ai_summary ?? null;
        const safetyFlagsHtml = ai?.safety_flags?.length ? `
            <div class="ai-tags safety-tags">
                <strong>Safety Flags:</strong>
                ${ai.safety_flags.map((flag: string) => `<span class="tag tag-danger">${flag}</span>`).join('')}
            </div>
        ` : '';

        const aiHtml = (ai || qualitativeText) && !ai?.error && !ai?._error ? `
            <div class="section ai-analysis">
                <h3>${icons.brain} AI Analysis</h3>
                ${qualitativeText ? `<p><strong>Summary:</strong> ${qualitativeText}</p>` : ''}
                ${ai?.classification || request.vertex_ai_classification ? `
                    <div class="ai-tags">
                        <strong>Classification:</strong>
                        <span class="tag tag-purple">${ai?.classification || request.vertex_ai_classification}</span>
                    </div>
                ` : ''}
                ${ai?.root_cause ? `<p><strong>Root Cause:</strong> ${ai.root_cause}</p>` : ''}
                ${ai?.recommended_action ? `<p><strong>Recommended Action:</strong> ${ai.recommended_action}</p>` : ''}
                ${ai?.similar_reports?.length ? `
                    <div class="ai-tags">
                        <strong>Similar Reports:</strong>
                        ${ai.similar_reports.map((r: any) => `<span class="tag tag-gray">#${r.service_request_id}</span>`).join('')}
                    </div>
                ` : ''}
                ${safetyFlagsHtml}
            </div>
        ` : '';

        // Build matched asset HTML
        const assetHtml = matchedAsset ? `
            <div class="section asset">
                <h3>${icons.link} Matched Asset</h3>
                <div class="grid">
                    <div><strong>Layer:</strong> ${matchedAsset.layer_name}</div>
                    ${matchedAsset.asset_id ? `<div><strong>Asset ID:</strong> ${matchedAsset.asset_id}</div>` : ''}
                    ${matchedAsset.asset_type ? `<div><strong>Type:</strong> ${matchedAsset.asset_type}</div>` : ''}
                    ${matchedAsset.distance_meters ? `<div><strong>Distance:</strong> ${Math.round(matchedAsset.distance_meters)}m</div>` : ''}
                </div>
            </div>
        ` : '';

        // Build timeline HTML
        const timelineHtml = auditLog?.length ? `
            <div class="section timeline">
                <h3>${icons.list} Timeline</h3>
                <table>
                    <tr><th>Date</th><th>Action</th><th>By</th><th>Details</th></tr>
                    ${auditLog.map(entry => `
                        <tr>
                            <td>${formatDate(entry.created_at)}</td>
                            <td>${entry.action.replace('_', ' ')}</td>
                            <td>${entry.actor_name || entry.actor_type}</td>
                            <td>${entry.new_value || ''}</td>
                        </tr>
                    `).join('')}
                </table>
            </div>
        ` : '';

        // Build custom fields HTML - format labels nicely
        const formatFieldLabel = (key: string) => {
            return key
                .replace(/_/g, ' ')
                .replace(/([a-z])([A-Z])/g, '$1 $2')
                .split(' ')
                .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
                .join(' ');
        };

        const customFieldsHtml = request.custom_fields && Object.keys(request.custom_fields).length ? `
            <div class="section custom-fields">
                <h3>${icons.clipboard} Additional Information</h3>
                <div class="grid">
                    ${Object.entries(request.custom_fields).map(([key, value]) => `
                        <div><strong>${formatFieldLabel(key)}:</strong> ${Array.isArray(value) ? value.join(', ') : value}</div>
                    `).join('')}
                </div>
            </div>
        ` : '';

        const html = `
            <!DOCTYPE html>
            <html>
            <head>
                <title>Work Order - ${request.service_request_id}</title>
                <style>
                    * { margin: 0; padding: 0; box-sizing: border-box; }
                    body { 
                        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                        font-size: 11px;
                        line-height: 1.4;
                        color: #1f2937;
                        padding: 20px;
                    }
                    .header {
                        display: flex;
                        justify-content: space-between;
                        align-items: flex-start;
                        border-bottom: 3px solid #1e40af;
                        padding-bottom: 15px;
                        margin-bottom: 20px;
                    }
                    .header-left {
                        display: flex;
                        align-items: center;
                        gap: 12px;
                    }
                    .header-left img {
                        max-height: 50px;
                        max-width: 100px;
                    }
                    .header-left h1 {
                        font-size: 20px;
                        color: #1e40af;
                    }
                    .header-left p {
                        color: #6b7280;
                        font-size: 10px;
                    }
                    .header-right {
                        text-align: right;
                    }
                    .request-id {
                        font-size: 18px;
                        font-weight: bold;
                        font-family: monospace;
                        color: #1f2937;
                    }
                    .status-badge {
                        display: inline-block;
                        padding: 4px 12px;
                        border-radius: 4px;
                        font-weight: bold;
                        font-size: 10px;
                        margin-top: 5px;
                    }
                    .status-open { background: #fef3c7; color: #92400e; }
                    .status-in_progress { background: #dbeafe; color: #1e40af; }
                    .status-closed { background: #d1fae5; color: #065f46; }
                    .priority-badge {
                        display: inline-block;
                        padding: 4px 12px;
                        border-radius: 4px;
                        font-weight: bold;
                        font-size: 10px;
                        margin-left: 5px;
                        color: white;
                    }
                    .meta-grid {
                        display: grid;
                        grid-template-columns: repeat(4, 1fr);
                        gap: 10px;
                        margin-bottom: 20px;
                        background: #f9fafb;
                        padding: 12px;
                        border-radius: 6px;
                        border: 1px solid #e5e7eb;
                    }
                    .meta-item label {
                        display: block;
                        font-size: 9px;
                        color: #6b7280;
                        text-transform: uppercase;
                        margin-bottom: 2px;
                        letter-spacing: 0.5px;
                    }
                    .meta-item span {
                        font-weight: 600;
                    }
                    .section {
                        margin-bottom: 15px;
                        page-break-inside: avoid;
                    }
                    .section h3 {
                        font-size: 12px;
                        color: #374151;
                        border-bottom: 1px solid #e5e7eb;
                        padding-bottom: 5px;
                        margin-bottom: 8px;
                        display: flex;
                        align-items: center;
                        gap: 6px;
                    }
                    .section h3 svg {
                        flex-shrink: 0;
                    }
                    .description {
                        background: #f3f4f6;
                        padding: 12px;
                        border-radius: 6px;
                        border-left: 4px solid #1e40af;
                    }
                    .photos {
                        display: flex;
                        gap: 10px;
                        flex-wrap: wrap;
                    }
                    .photos img {
                        max-height: 120px;
                        max-width: 200px;
                        border-radius: 4px;
                        border: 1px solid #e5e7eb;
                    }
                    .grid {
                        display: grid;
                        grid-template-columns: repeat(2, 1fr);
                        gap: 5px 15px;
                    }
                    .ai-analysis {
                        background: #f5f3ff;
                        padding: 12px;
                        border-radius: 6px;
                        border-left: 4px solid #7c3aed;
                    }
                    .ai-analysis p { margin-bottom: 5px; }
                    .ai-tags {
                        margin-bottom: 8px;
                        display: flex;
                        align-items: center;
                        flex-wrap: wrap;
                        gap: 6px;
                    }
                    .ai-tags strong {
                        margin-right: 4px;
                    }
                    .tag {
                        display: inline-block;
                        padding: 2px 8px;
                        border-radius: 4px;
                        font-size: 10px;
                        font-weight: 500;
                    }
                    .tag-purple {
                        background: #ede9fe;
                        color: #6d28d9;
                        border: 1px solid #c4b5fd;
                    }
                    .tag-gray {
                        background: #f3f4f6;
                        color: #374151;
                        border: 1px solid #d1d5db;
                    }
                    .tag-danger {
                        background: #fef2f2;
                        color: #dc2626;
                        border: 1px solid #fecaca;
                    }
                    .priority-source {
                        font-size: 9px;
                        color: #6b7280;
                        font-weight: normal;
                        margin-left: 3px;
                    }
                    .asset {
                        background: #ecfdf5;
                        padding: 12px;
                        border-radius: 6px;
                        border-left: 4px solid #10b981;
                    }
                    .custom-fields {
                        background: #fffbeb;
                        padding: 12px;
                        border-radius: 6px;
                        border-left: 4px solid #f59e0b;
                    }
                    .completion {
                        background: #d1fae5;
                        padding: 12px;
                        border-radius: 6px;
                        border-left: 4px solid #059669;
                    }
                    .completion img {
                        max-height: 150px;
                        margin-top: 8px;
                        border-radius: 4px;
                    }
                    .reporter {
                        background: #f0f9ff;
                        padding: 12px;
                        border-radius: 6px;
                        border-left: 4px solid #0284c7;
                    }
                    table {
                        width: 100%;
                        border-collapse: collapse;
                        font-size: 10px;
                    }
                    th, td {
                        border: 1px solid #e5e7eb;
                        padding: 6px 8px;
                        text-align: left;
                    }
                    th {
                        background: #f3f4f6;
                        font-weight: 600;
                    }
                    .footer {
                        margin-top: 30px;
                        padding-top: 15px;
                        border-top: 1px solid #e5e7eb;
                        display: flex;
                        justify-content: space-between;
                        font-size: 9px;
                        color: #9ca3af;
                    }
                    .signature-box {
                        margin-top: 30px;
                        display: grid;
                        grid-template-columns: 1fr 1fr;
                        gap: 30px;
                    }
                    .signature-line {
                        border-top: 1px solid #374151;
                        padding-top: 5px;
                        font-size: 10px;
                        color: #6b7280;
                    }
                    @media print {
                        body { padding: 0; }
                        .section { page-break-inside: avoid; }
                    }
                </style>
            </head>
            <body>
                <div class="header">
                    <div class="header-left">
                        ${logoUrl ? `<img src="${logoUrl}" alt="Logo" />` : ''}
                        <div>
                            <h1>${townshipName || 'Municipal'} Work Order</h1>
                            <p>311 Service Request</p>
                        </div>
                    </div>
                    <div class="header-right">
                        <div class="request-id">#${request.service_request_id}</div>
                        <span class="status-badge status-${request.status}">${getStatusLabel(request.status, request.closed_substatus)}</span>
                        <span class="priority-badge" style="background: ${priority.color}">${priority.label} (${priorityScore}/10) <span class="priority-source">• ${prioritySource}</span></span>
                    </div>
                </div>

                <div class="meta-grid">
                    <div class="meta-item">
                        <label>Category</label>
                        <span>${request.service_name}</span>
                    </div>
                    <div class="meta-item">
                        <label>Submitted</label>
                        <span>${formatDate(request.requested_datetime)}</span>
                    </div>
                    <div class="meta-item">
                        <label>Department</label>
                        <span>${request.assigned_department?.name || 'Unassigned'}</span>
                    </div>
                    <div class="meta-item">
                        <label>Assigned To</label>
                        <span>${request.assigned_to || 'Unassigned'}</span>
                    </div>
                </div>

                <div class="section">
                    <h3>${icons.location} Location</h3>
                    <p><strong>${request.address || 'No address'}</strong></p>
                    ${request.lat && request.long ? `<p style="color: #6b7280; font-size: 10px;">GPS: ${request.lat.toFixed(6)}, ${request.long.toFixed(6)}</p>` : ''}
                </div>

                <div class="section">
                    <h3>${icons.document} Issue Description</h3>
                    <div class="description">${request.description}</div>
                </div>

                ${customFieldsHtml}
                ${assetHtml}
                ${photosHtml}
                ${aiHtml}
                ${completionHtml}

                <div class="section reporter">
                    <h3>${icons.user} Reporter Contact</h3>
                    <div class="grid">
                        <div><strong>Name:</strong> ${request.first_name || ''} ${request.last_name || ''}</div>
                        <div><strong>Email:</strong> ${request.email}</div>
                        ${request.phone ? `<div><strong>Phone:</strong> ${request.phone}</div>` : ''}
                    </div>
                </div>

                ${timelineHtml}

                <div class="signature-box">
                    <div>
                        <div class="signature-line">Staff Signature / Date</div>
                    </div>
                    <div>
                        <div class="signature-line">Supervisor Approval / Date</div>
                    </div>
                </div>

                <div class="footer">
                    <span>Generated: ${new Date().toLocaleString()}</span>
                    <span>Powered by Pinpoint 311</span>
                </div>
            </body>
            </html>
        `;

        printWindow.document.write(html);
        printWindow.document.close();

        // Wait for images to load, then print
        printWindow.onload = () => {
            setTimeout(() => {
                printWindow.print();
            }, 500);
        };
    };

    return (
        <button
            onClick={handlePrint}
            className="flex items-center gap-2 px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white rounded-lg transition-colors text-sm"
            title="Print Work Order as PDF"
        >
            <Printer className="w-4 h-4" />
            <span>Print Work Order</span>
        </button>
    );
}
