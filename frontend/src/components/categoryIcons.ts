import {
    Accessibility, AlertCircle, Axe, Banknote, Bell, Bike, Biohazard, Bird, Bug, Briefcase, Building, Building2,
    Bus, Calculator, Camera, Car, Cat, Cctv, Circle, CircleParking, ClipboardCheck, Clock, CloudRain,
    Construction, Dog, DollarSign, DoorOpen, Droplet, Droplets, Dumbbell, Eye, Fence, FerrisWheel,
    FileCheck, FileText, Fish, Flag, Flame, Flower2, Footprints, Gavel, Hammer, HandHelping,
    HardHat, Heart, HeartHandshake, HelpCircle, Home, House, IdCard, Info, KeyRound, LandPlot,
    Landmark, Leaf, Library, Lightbulb, Mail, Mailbox, Map, MapPin, Megaphone, MessageCircleQuestion,
    Package, PaintBucket, PawPrint, Phone, Plug, RadioTower, Rat, Receipt, Recycle, Route, Ruler,
    School, ScrollText, Settings, Shield, ShieldAlert, Shovel, SignpostBig, Siren, Snowflake,
    Sofa, SprayCan, Sprout, Squirrel, Star, Stamp, Tent, Thermometer, Toilet, TrafficCone, Trash2,
    TreePine, Trees, Truck, Users, Volleyball, Volume2, Vote, Wallet, Warehouse, Waves, Wind, Wrench,
    Zap, type LucideIcon,
} from 'lucide-react';

/**
 * The one list of service-category icons, used everywhere a category icon is
 * picked or shown: the admin picker, the admin category list, the resident
 * report form and the staff screens.
 *
 * There used to be two lists that disagreed: the admin picker offered 29 icons
 * and the resident form knew 8, under partly different names (the picker saved
 * `Trash`, the form knew `Trash2`), so most choices showed residents a generic
 * alert icon instead. Resolve every name through `categoryIconFor` and that
 * cannot happen again.
 *
 * `name` is what is stored on the category (ServiceDefinition.icon), so names
 * are never renamed once shipped; add an alias instead.
 */

export interface CategoryIconDef {
    name: string;
    label: string;
    icon: LucideIcon;
    /** Lowercase words or phrases that suggest this icon from a category name. */
    keywords: string[];
    /** Matches only when nothing more specific does ("question", "other"). */
    generic?: boolean;
}

export interface CategoryIconGroup {
    id: string;
    label: string;
    icons: CategoryIconDef[];
}

const i = (name: string, label: string, icon: LucideIcon, keywords: string[] = [], generic = false): CategoryIconDef =>
    ({ name, label, icon, keywords, generic });

export const CATEGORY_ICON_GROUPS: CategoryIconGroup[] = [
    {
        id: 'streets', label: 'Streets and traffic', icons: [
            i('Construction', 'Road repair', Construction, ['pothole', 'road repair', 'pavement', 'asphalt', 'road damage', 'street repair', 'paving']),
            i('TrafficCone', 'Traffic safety', TrafficCone, ['traffic', 'traffic safety', 'detour', 'work zone', 'speeding']),
            i('SignpostBig', 'Street signs', SignpostBig, ['street sign', 'road sign', 'sign', 'stop sign', 'signage']),
            i('Lightbulb', 'Street lighting', Lightbulb, ['street lighting', 'street light', 'streetlight', 'lighting', 'light out', 'lamp']),
            i('Car', 'Vehicles', Car, ['abandoned vehicle', 'abandoned car', 'vehicle', 'car']),
            i('CircleParking', 'Parking', CircleParking, ['parking', 'parking meter', 'permit parking']),
            i('Bus', 'Transit', Bus, ['bus', 'bus stop', 'transit', 'shuttle']),
            i('Bike', 'Bike lanes', Bike, ['bike', 'bicycle', 'bike lane']),
            i('Footprints', 'Sidewalks', Footprints, ['sidewalk', 'crosswalk', 'pedestrian', 'curb']),
            i('Route', 'Roads', Route, ['road', 'roadway', 'street', 'route']),
        ],
    },
    {
        id: 'sanitation', label: 'Trash and recycling', icons: [
            i('Trash2', 'Trash pickup', Trash2, ['trash', 'garbage', 'refuse', 'litter', 'waste']),
            i('Recycle', 'Recycling', Recycle, ['recycling', 'recycle', 'compost']),
            i('Sofa', 'Bulk pickup', Sofa, ['bulk', 'bulky', 'furniture', 'large item', 'appliance']),
            i('Sprout', 'Brush and yard waste', Sprout, ['brush', 'yard waste', 'branches', 'grass clippings']),
            i('Leaf', 'Leaf pickup', Leaf, ['leaf', 'leaves']),
            i('Truck', 'Collection truck', Truck, ['missed pickup', 'missed collection', 'hauling', 'sanitation truck']),
            i('SprayCan', 'Graffiti', SprayCan, ['graffiti', 'vandalism', 'tagging']),
            i('Biohazard', 'Hazardous waste', Biohazard, ['hazardous', 'needle', 'syringe', 'biohazard', 'chemical']),
            i('Toilet', 'Restrooms', Toilet, ['restroom', 'bathroom', 'toilet', 'porta potty']),
        ],
    },
    {
        id: 'water', label: 'Water, storms and weather', icons: [
            i('Droplet', 'Water', Droplet, ['water', 'water main', 'leak', 'hydrant', 'water service']),
            i('Droplets', 'Sewer', Droplets, ['sewer', 'sanitary', 'septic', 'sewage', 'backup']),
            i('Waves', 'Storm drains', Waves, ['storm drain', 'catch basin', 'drainage', 'drain', 'culvert', 'stormwater']),
            i('CloudRain', 'Flooding', CloudRain, ['flooding', 'flood', 'ponding', 'standing water']),
            i('Snowflake', 'Snow and ice', Snowflake, ['snow', 'plow', 'plowing', 'ice', 'icy', 'salting', 'sanding']),
            i('Shovel', 'Snow shoveling', Shovel, ['shovel', 'shoveling', 'unshoveled']),
            i('Wind', 'Storm damage', Wind, ['storm damage', 'wind', 'downed']),
            i('Thermometer', 'Heat and cooling', Thermometer, ['heat', 'cooling center', 'warming center', 'no heat']),
            i('Flame', 'Burning and smoke', Flame, ['burning', 'smoke', 'open burning', 'fire pit']),
        ],
    },
    {
        id: 'parks', label: 'Parks and trees', icons: [
            i('TreePine', 'Parks', TreePine, ['park', 'parks', 'playground', 'open space']),
            i('Trees', 'Trees', Trees, ['tree', 'trees', 'tree trimming', 'tree removal', 'forestry', 'stump']),
            i('Axe', 'Tree removal', Axe, ['fallen tree', 'dead tree', 'limb']),
            i('Flower2', 'Landscaping', Flower2, ['landscaping', 'garden', 'flower', 'mowing', 'overgrown']),
            i('FerrisWheel', 'Recreation', FerrisWheel, ['recreation', 'amusement', 'carnival', 'event']),
            i('Volleyball', 'Sports fields', Volleyball, ['field', 'sports', 'court', 'athletic', 'ballfield']),
            i('Dumbbell', 'Fitness', Dumbbell, ['fitness', 'gym']),
            i('Tent', 'Camping', Tent, ['camping', 'campground', 'encampment']),
            i('Fence', 'Fences', Fence, ['fence', 'fencing', 'gate']),
        ],
    },
    {
        id: 'animals', label: 'Animals', icons: [
            i('PawPrint', 'Animals', PawPrint, ['animal', 'animals', 'pet', 'pets', 'stray']),
            i('Dog', 'Dogs', Dog, ['dog', 'dogs', 'barking', 'leash', 'dog waste']),
            i('Cat', 'Cats', Cat, ['cat', 'cats', 'feral']),
            i('Rat', 'Rodents', Rat, ['rodent', 'rodents', 'rat', 'rats', 'mice']),
            i('Bug', 'Insects', Bug, ['insect', 'mosquito', 'bees', 'wasp', 'pest', 'pests']),
            i('Bird', 'Birds', Bird, ['bird', 'birds', 'geese']),
            i('Squirrel', 'Wildlife', Squirrel, ['wildlife', 'deer', 'raccoon', 'squirrel', 'dead animal']),
            i('Fish', 'Ponds and fish', Fish, ['fish', 'pond', 'lake']),
        ],
    },
    {
        id: 'buildings', label: 'Buildings, code and permits', icons: [
            i('Gavel', 'Code enforcement', Gavel, ['code enforcement', 'code violation', 'violation', 'ordinance', 'enforcement']),
            i('HardHat', 'Construction permits', HardHat, ['construction permit', 'building permit', 'construction', 'contractor']),
            i('Stamp', 'Permits', Stamp, ['permit', 'permits', 'approval', 'application', 'license application']),
            i('FileCheck', 'Certificates', FileCheck, ['certificate of occupancy', 'certificate', 'certification', 'occupancy']),
            i('ClipboardCheck', 'Inspections', ClipboardCheck, ['inspection', 'inspections', 'inspector']),
            i('LandPlot', 'Zoning', LandPlot, ['zoning', 'zoning permit', 'variance', 'land use', 'subdivision', 'site plan']),
            i('Ruler', 'Surveys', Ruler, ['survey', 'setback', 'property line']),
            i('Map', 'Planning', Map, ['planning', 'master plan', 'map']),
            i('House', 'Housing', House, ['housing', 'property maintenance', 'residential', 'home']),
            i('Building2', 'Buildings', Building2, ['building', 'commercial', 'business']),
            i('KeyRound', 'Rentals', KeyRound, ['rental', 'landlord', 'tenant', 'rental registration']),
            i('DoorOpen', 'Vacant property', DoorOpen, ['vacant', 'abandoned property', 'abandoned building', 'unsecured']),
            i('Volume2', 'Noise', Volume2, ['noise', 'loud', 'music']),
            i('Hammer', 'Repairs', Hammer, ['repair', 'repairs']),
            i('Warehouse', 'Facilities', Warehouse, ['facility', 'facilities', 'public works', 'garage']),
        ],
    },
    {
        id: 'finance', label: 'Taxes, fees and records', icons: [
            i('Calculator', 'Tax assessment', Calculator, ['tax assessment', 'assessment', 'assessor', 'appraisal', 'reassessment']),
            i('Receipt', 'Tax collection', Receipt, ['tax collection', 'tax bill', 'tax payment', 'property tax', 'taxes', 'tax']),
            i('DollarSign', 'Fees and payments', DollarSign, ['fee', 'fees', 'payment', 'fine', 'fines']),
            i('Banknote', 'Utility billing', Banknote, ['utility bill', 'billing', 'water bill', 'sewer bill']),
            i('Wallet', 'Refunds', Wallet, ['refund', 'refunds']),
            i('Briefcase', 'Business licenses', Briefcase, ['business license', 'license', 'licensing']),
            i('ScrollText', 'Public records', ScrollText, ['records', 'records request', 'opra', 'foia', 'public records']),
            i('FileText', 'Forms and documents', FileText, ['form', 'forms', 'document', 'documents']),
            i('IdCard', 'Registrations', IdCard, ['registration', 'id card', 'dog license']),
            i('Vote', 'Elections', Vote, ['election', 'elections', 'voting', 'voter']),
        ],
    },
    {
        id: 'community', label: 'Community and safety', icons: [
            i('Accessibility', 'Accessibility (ADA)', Accessibility, ['ada', 'accessibility', 'accessible', 'disability', 'wheelchair']),
            i('ShieldAlert', 'Safety hazards', ShieldAlert, ['safety', 'hazard', 'unsafe', 'dangerous']),
            i('Siren', 'Public safety', Siren, ['police', 'public safety', 'alarm']),
            i('Cctv', 'Cameras', Cctv, ['camera', 'cameras', 'surveillance']),
            i('Megaphone', 'Complaints and notices', Megaphone, ['complaint', 'complaints', 'notice', 'announcement']),
            i('Users', 'Community', Users, ['community', 'neighborhood', 'meeting', 'senior']),
            i('HeartHandshake', 'Social services', HeartHandshake, ['social services', 'assistance', 'welfare', 'food']),
            i('HandHelping', 'Volunteering', HandHelping, ['volunteer', 'volunteering', 'donation']),
            i('Library', 'Library', Library, ['library']),
            i('School', 'Schools', School, ['school', 'schools', 'crossing guard']),
            i('Landmark', 'Town hall', Landmark, ['town hall', 'municipal building', 'municipal', 'government', 'council']),
            i('Plug', 'Power outages', Plug, ['power outage', 'outage', 'electric', 'electricity']),
            i('Zap', 'Electrical', Zap, ['electrical', 'wires', 'power line', 'power lines']),
            i('RadioTower', 'Telecom', RadioTower, ['cell tower', 'cable', 'internet', 'telecom']),
            i('Eye', 'Observations', Eye, ['observation', 'suspicious']),
        ],
    },
    {
        id: 'general', label: 'General', icons: [
            i('MessageCircleQuestion', 'Questions', MessageCircleQuestion, ['question', 'questions', 'inquiry', 'general', 'other', 'info', 'information'], true),
            i('AlertCircle', 'General issue', AlertCircle, ['concern', 'concerns', 'issue', 'problem'], true),
            i('Info', 'Information', Info, []),
            i('Mailbox', 'Mail', Mailbox, ['mail', 'mailbox', 'postal']),
            i('Phone', 'Phone', Phone, ['phone', 'call']),
            i('Clock', 'Hours', Clock, ['hours', 'schedule']),
            i('Bell', 'Alerts', Bell, ['alert', 'alerts', 'notification']),
            i('Wrench', 'Maintenance', Wrench, ['maintenance', 'broken', 'fix']),
            i('Package', 'Deliveries', Package, ['package', 'delivery']),
            i('Camera', 'Photos', Camera, ['photo']),
            i('Flag', 'Flag', Flag, ['flag']),
            i('Star', 'Star', Star, []),
            i('Settings', 'Settings', Settings, []),
        ],
    },
];

export const CATEGORY_ICONS: CategoryIconDef[] = CATEGORY_ICON_GROUPS.flatMap(g => g.icons);

const BY_NAME: Record<string, CategoryIconDef> = Object.fromEntries(CATEGORY_ICONS.map(d => [d.name, d]));

/** Names stored by earlier versions, which must keep rendering. */
const LEGACY: Record<string, LucideIcon> = {
    Trash: Trash2,
    Building,
    Home,
    PaintBucket,
    Shield,
    Heart,
    Mail,
    MapPin,
    HelpCircle,
    Circle,
    Spray: SprayCan,
    CircleAlert: AlertCircle,
};

export const DEFAULT_CATEGORY_ICON = 'AlertCircle';

/** The component for a stored icon name. Never undefined. */
export function categoryIconFor(name?: string | null): LucideIcon {
    if (!name) return AlertCircle;
    return BY_NAME[name]?.icon ?? LEGACY[name] ?? AlertCircle;
}

/** Whether a stored name is the default or something the picker no longer shows. */
export function isDefaultOrUnknownIcon(name?: string | null): boolean {
    return !name || name === DEFAULT_CATEGORY_ICON || (!BY_NAME[name] && !LEGACY[name]);
}

function normalise(text: string): string {
    return ` ${text.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()} `;
}

function escapeRegExp(s: string): string {
    return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * The best icon for a category from its name (and code or description), or
 * null when nothing matches. The longest matching phrase wins, so "Zoning
 * Permit Inquiry" gets zoning rather than the generic permit icon, and generic
 * words ("question", "other") only count when nothing specific matched.
 */
export function suggestCategoryIcon(...texts: (string | null | undefined)[]): string | null {
    const text = normalise(texts.filter(Boolean).join(' '));
    let best: { name: string; score: number } | null = null;
    for (const def of CATEGORY_ICONS) {
        for (const keyword of def.keywords) {
            const kw = normalise(keyword).trim();
            if (!kw) continue;
            // Whole words, with an optional plural "s": "drains" matches "drain",
            // but "roadway" does not match "road".
            const re = new RegExp(` ${escapeRegExp(kw)}s? `);
            if (!re.test(text)) continue;
            const score = (def.generic ? 0.1 : 1) * kw.length;
            if (!best || score > best.score) best = { name: def.name, score };
        }
    }
    return best?.name ?? null;
}

/** Icons matching a search box, by label, name or keyword. */
export function searchCategoryIcons(query: string): CategoryIconDef[] {
    const q = query.trim().toLowerCase();
    if (!q) return CATEGORY_ICONS;
    return CATEGORY_ICONS.filter(d =>
        d.label.toLowerCase().includes(q)
        || d.name.toLowerCase().includes(q)
        || d.keywords.some(k => k.includes(q)));
}
