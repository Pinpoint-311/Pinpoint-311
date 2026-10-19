import type { RoutingContact, ServiceDefinition } from '../types';

/**
 * Reusing a third-party agency, and its roads, across categories.
 *
 * Agencies live inside each category's routing_config (third_party_contacts).
 * There is no town-wide agency table, and adding one would need a migration,
 * so the "saved agencies" are simply every agency already configured on some
 * other category, gathered here. Applying one COPIES it: the categories do not
 * share an object afterwards, so editing PennDOT on Potholes cannot silently
 * change PennDOT on Street Signs. Each category is saved, and audited, on its
 * own.
 *
 * The same shape is read from a file ("pinpoint311.agencies"), so a ready-made
 * set -- a county and state road list for one town -- can be imported in one go.
 */

export interface SavedAgency {
    /** Stable for the dropdown: identical agencies on several categories collapse to one. */
    key: string;
    agency: RoutingContact;
    /** Category names this exact agency is configured on. */
    usedBy: string[];
    roads: string[];
}

const ROAD_SPLIT = /\s*,\s*/;

/** An agency's roads as a list, from whichever field it carries them in. */
export function agencyRoads(agency: Partial<RoutingContact> | null | undefined): string[] {
    if (!agency) return [];
    if (typeof agency.road_list === 'string' && agency.road_list.trim()) {
        return agency.road_list.split(ROAD_SPLIT).map(r => r.trim()).filter(Boolean);
    }
    if (Array.isArray(agency.roads)) {
        return agency.roads.map(roadLabel).filter(Boolean);
    }
    return [];
}

/** A road entry as text. `{name, from_street, to_street}` becomes "Name (From to To)". */
export function roadLabel(entry: unknown): string {
    if (typeof entry === 'string') return entry.trim();
    if (entry && typeof entry === 'object') {
        const e = entry as Record<string, unknown>;
        const name = String(e.name ?? '').trim();
        const from = String(e.from_street ?? e.from ?? '').trim();
        const to = String(e.to_street ?? e.to ?? '').trim();
        if (!name) return '';
        return from && to ? `${name} (${from} to ${to})` : name;
    }
    return '';
}

/** "Oak Rd (Elm St to Route 10)" -> its parts. Limits are null when absent. */
export function parseRoadEntry(text: string): { name: string; from: string | null; to: string | null } {
    const m = /^\s*([^()]+?)\s*\(\s*(?:from\s+|between\s+)?([^()]+?)\s+(?:to|and|thru|through|-|–|—)\s+([^()]+?)\s*\)\s*$/i.exec(text);
    if (m) return { name: m[1].trim(), from: m[2].trim(), to: m[3].trim() };
    return { name: text.trim(), from: null, to: null };
}

/**
 * A fresh, independent copy of an agency, ready to put on another category.
 * Nothing in the result is shared with the source: arrays and nested contact
 * lists are rebuilt, so later edits to either side stay on that side.
 */
export function cloneAgency(source: RoutingContact): RoutingContact {
    const roads = agencyRoads(source);
    const copy: RoutingContact = JSON.parse(JSON.stringify({
        name: source.name ?? '',
        phone: source.phone ?? '',
        email: source.email ?? '',
        url: source.url ?? '',
        message: source.message ?? '',
    }));
    // road_list only. The server prefers `roads` when both exist, and the
    // editor only ever updates road_list, so a copied `roads` would go stale
    // the first time the clerk edits the list.
    copy.road_list = roads.join(', ');
    const contacts = (source as RoutingContact & { contacts?: unknown }).contacts;
    if (Array.isArray(contacts) && contacts.length) {
        (copy as RoutingContact & { contacts?: unknown }).contacts = JSON.parse(JSON.stringify(contacts));
    }
    return copy;
}

const signature = (a: RoutingContact) => JSON.stringify([
    (a.name || '').trim().toLowerCase(),
    (a.phone || '').trim(), (a.email || '').trim().toLowerCase(), (a.url || '').trim(),
    (a.message || '').trim(),
    agencyRoads(a).map(r => r.toLowerCase()),
]);

/**
 * Agencies configured on categories other than `excludeServiceId`, each once.
 *
 * Two categories carrying the very same agency (same name, contacts and roads)
 * show as one entry "used by" both. The same name with different roads stays
 * separate, because which road list is meant is exactly the clerk's choice.
 */
export function savedAgencies(services: ServiceDefinition[], excludeServiceId?: number | null): SavedAgency[] {
    const byKey = new Map<string, SavedAgency>();
    for (const service of services) {
        if (service.id === excludeServiceId) continue;
        const agencies = service.routing_config?.third_party_contacts;
        if (!Array.isArray(agencies)) continue;
        for (const agency of agencies) {
            if (!agency || !(agency.name || '').trim()) continue;
            const key = signature(agency);
            const existing = byKey.get(key);
            if (existing) {
                if (!existing.usedBy.includes(service.service_name)) existing.usedBy.push(service.service_name);
            } else {
                byKey.set(key, { key, agency, usedBy: [service.service_name], roads: agencyRoads(agency) });
            }
        }
    }
    return [...byKey.values()].sort((a, b) =>
        (a.agency.name || '').localeCompare(b.agency.name || '') || b.roads.length - a.roads.length);
}

/** The flattened road list the coverage map and legacy readers use. */
export function combinedRoadList(agencies: RoutingContact[]): string {
    return agencies.flatMap(agencyRoads).join(', ');
}

/**
 * Agencies from an imported file. Accepts the bundled format
 * ({format: "pinpoint311.agencies", agencies: [...]}) or a bare array.
 * Throws with a message an admin can act on.
 */
export function parseAgencyFile(text: string): RoutingContact[] {
    let doc: unknown;
    try {
        doc = JSON.parse(text);
    } catch {
        throw new Error('That file is not valid JSON.');
    }
    const list = Array.isArray(doc) ? doc : (doc as { agencies?: unknown })?.agencies;
    if (!Array.isArray(list) || list.length === 0) {
        throw new Error('No agencies found. The file needs an "agencies" list.');
    }
    const out = list.map((raw, i) => {
        if (!raw || typeof raw !== 'object') throw new Error(`Agency ${i + 1} is not an object.`);
        const r = raw as Record<string, unknown>;
        const name = String(r.name ?? '').trim();
        if (!name) throw new Error(`Agency ${i + 1} has no name.`);
        const roads = Array.isArray(r.roads)
            ? r.roads.map(roadLabel).filter(Boolean)
            : agencyRoads({ road_list: typeof r.road_list === 'string' ? r.road_list : '' });
        return cloneAgency({
            name,
            phone: String(r.phone ?? ''),
            email: String(r.email ?? ''),
            url: String(r.url ?? ''),
            message: String(r.message ?? ''),
            roads,
        });
    });
    return out;
}
