
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

        // Status label
        const getStatusLabel = (status: string, substatus: string | null) => {
            if (status === 'closed') {
                if (substatus === 'resolved') return '✓ RESOLVED';
                if (substatus === 'no_action') return 'NO ACTION NEEDED';
                if (substatus === 'third_party') return 'REFERRED';
                return 'CLOSED';
            }
            return status.toUpperCase().replace('_', ' ');
        };

        // Build photos HTML
        const photosHtml = request.media_urls?.length ? `
            <div class="section">
                <h3>📷 Photos (${request.media_urls.length})</h3>
                <div class="photos">
                    ${request.media_urls.map(url => `<img src="${url}" alt="Issue photo" />`).join('')}
                </div>
            </div>
        ` : '';

        // Build completion photo HTML
        const completionHtml = request.status === 'closed' && (request.completion_message || request.completion_photo_url) ? `
            <div class="section completion">
                <h3>✓ Resolution</h3>
                ${request.completion_message ? `<p><strong>Message:</strong> ${request.completion_message}</p>` : ''}
                ${request.completion_photo_url ? `<img src="${request.completion_photo_url}" alt="Completion photo" style="max-height: 150px;" />` : ''}
            </div>
        ` : '';

        // Build AI analysis HTML
        const aiHtml = ai && !ai.error ? `
            <div class="section ai-analysis">
                <h3>🤖 AI Analysis</h3>
                ${ai.summary ? `<p><strong>Summary:</strong> ${ai.summary}</p>` : ''}
                ${ai.classification ? `<p><strong>Classification:</strong> ${ai.classification}</p>` : ''}
                ${ai.root_cause ? `<p><strong>Root Cause:</strong> ${ai.root_cause}</p>` : ''}
                ${ai.recommended_action ? `<p><strong>Recommended Action:</strong> ${ai.recommended_action}</p>` : ''}
                ${ai.safety_flags?.length ? `<p class="safety-flags"><strong>⚠️ Safety Flags:</strong> ${ai.safety_flags.join(', ')}</p>` : ''}
            </div>
        ` : '';

        // Build matched asset HTML
        const assetHtml = matchedAsset ? `
            <div class="section asset">
                <h3>🔗 Matched Asset</h3>
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
                <h3>📋 Timeline</h3>
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

        // Build custom fields HTML
        const customFieldsHtml = request.custom_fields && Object.keys(request.custom_fields).length ? `
            <div class="section">
                <h3>📝 Additional Information</h3>
                <div class="grid">
                    ${Object.entries(request.custom_fields).map(([key, value]) => `
                        <div><strong>${key.replace(/_/g, ' ')}:</strong> ${Array.isArray(value) ? value.join(', ') : value}</div>
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
                        border-bottom: 3px solid #3b82f6;
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
                    }
                    .meta-item label {
                        display: block;
                        font-size: 9px;
                        color: #6b7280;
                        text-transform: uppercase;
                        margin-bottom: 2px;
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
                    }
                    .description {
                        background: #f3f4f6;
                        padding: 12px;
                        border-radius: 6px;
                        border-left: 4px solid #3b82f6;
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
                        background: #faf5ff;
                        padding: 10px;
                        border-radius: 6px;
                        border-left: 4px solid #8b5cf6;
                    }
                    .ai-analysis p { margin-bottom: 5px; }
                    .safety-flags { color: #dc2626; }
                    .asset {
                        background: #ecfdf5;
                        padding: 10px;
                        border-radius: 6px;
                        border-left: 4px solid #10b981;
                    }
                    .completion {
                        background: #d1fae5;
                        padding: 10px;
                        border-radius: 6px;
                        border-left: 4px solid #059669;
                    }
                    .completion img {
                        max-height: 150px;
                        margin-top: 8px;
                        border-radius: 4px;
                    }
                    .reporter {
                        background: #fefce8;
                        padding: 10px;
                        border-radius: 6px;
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
                        <span class="priority-badge" style="background: ${priority.color}">${priority.label} (${priorityScore}/10)</span>
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
                    <h3>📍 Location</h3>
                    <p><strong>${request.address || 'No address'}</strong></p>
                    ${request.lat && request.long ? `<p style="color: #6b7280; font-size: 10px;">GPS: ${request.lat.toFixed(6)}, ${request.long.toFixed(6)}</p>` : ''}
                </div>

                <div class="section">
                    <h3>📝 Issue Description</h3>
                    <div class="description">${request.description}</div>
                </div>

                ${customFieldsHtml}
                ${assetHtml}
                ${photosHtml}
                ${aiHtml}
                ${completionHtml}

                <div class="section reporter">
                    <h3>👤 Reporter Contact</h3>
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
