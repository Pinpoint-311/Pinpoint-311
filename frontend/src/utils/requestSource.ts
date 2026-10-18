/** How a report reached the town, as staff read it. Matches the intake
 *  "Received by" selector; connector imports name their system. */
export function sourceLabel(source?: string | null): string {
    switch (source) {
        case 'resident_portal':
        case undefined:
        case null:
        case '':
            return 'Online';
        case 'phone': return 'Phone';
        case 'email': return 'Email';
        case 'walk_in': return 'In person';
        case 'other': return 'Other';
        default:
            if (source.startsWith('integration_')) {
                const name = source.slice('integration_'.length).replace(/_/g, ' ');
                return `From ${name.charAt(0).toUpperCase()}${name.slice(1)}`;
            }
            return source;
    }
}
