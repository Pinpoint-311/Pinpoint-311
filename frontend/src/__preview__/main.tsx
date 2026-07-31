import { createRoot } from 'react-dom/client';

/**
 * A local harness for looking at admin pages.
 *
 * Not part of the app and not built into it -- Vite's build entry is
 * index.html, so preview.html and this file never reach dist. Run
 * `npx vite` and open /preview.html.
 *
 * It exists because two rounds of this work were verified only by tests
 * asserting on the DOM, which cannot see that a page looks wrong. The
 * departments cards matched the service-category page in every respect a test
 * could check and still read as a different product until they were put side
 * by side here.
 */
import '../index.css';
import './themes.css';

import SetupWizard from '../components/SetupWizard';
import ServiceProviders from '../components/ServiceProviders';
import { DepartmentsTab, ServiceCategoriesTab } from '../pages/AdminConsole';

// Canned API so the components render exactly as they would with a real one.
const CATALOGS: Record<string, any> = {
    identity: { current_provider: 'entra', configured: { entra: true }, providers: [
        { provider: 'entra', name: 'Microsoft Entra ID', credential_fields: [
            { key: 'ENTRA_TENANT_ID', label: 'Directory (tenant) ID', secret: false },
            { key: 'ENTRA_CLIENT_ID', label: 'Application (client) ID', secret: false },
            { key: 'ENTRA_CLIENT_SECRET', label: 'Client secret value', secret: true }]}]},
    maps: { current_provider: 'google', configured: { google: true }, providers: [
        { provider: 'google', name: 'Google Maps', credential_fields: [
            { key: 'GOOGLE_MAPS_API_KEY', label: 'Google Maps API key', secret: true }]}]},
    ai: { current_provider: 'azure', configured: { azure: true }, current_model: 'gpt-4o', providers: [
        { provider: 'azure', name: 'Azure OpenAI', credential_fields: [
            { key: 'AZURE_OPENAI_ENDPOINT', label: 'Endpoint', secret: false },
            { key: 'AZURE_OPENAI_API_KEY', label: 'API key', secret: true }]}]},
    translation: { current_provider: 'azure', configured: { azure: true }, providers: [
        { provider: 'azure', name: 'Azure Translator', credential_fields: [
            { key: 'AZURE_TRANSLATOR_KEY', label: 'Translator key', secret: true },
            { key: 'AZURE_TRANSLATOR_REGION', label: 'Region', secret: false }]}]},
    kms: { current_provider: 'azure', configured: { azure: true }, providers: [
        { provider: 'azure', name: 'Azure Key Vault', credential_fields: [
            { key: 'AZURE_KEYVAULT_URL', label: 'Vault URL', secret: false }]}]},
};
Object.assign(CATALOGS, {
    email: { current_provider: 'acs', configured: { acs: true }, providers: [
        { provider: 'acs', name: 'Azure Communication Services', credential_fields: [
            { key: 'ACS_CONNECTION_STRING', label: 'Connection string', secret: true }]}]},
    sms: { current_provider: 'acs', configured: { acs: false }, providers: [
        { provider: 'acs', name: 'Azure Communication Services', credential_fields: [
            { key: 'ACS_SMS_FROM', label: 'From number', secret: false }]}]},
    redaction: { current_provider: 'local', configured: { local: true }, providers: [
        { provider: 'local', name: 'On this server', credential_fields: [] }]},
});
// Deliberately mixed: a page where everything is green is the easy case, and
// not the one worth looking at.
const ago = (mins: number) => new Date(Date.now() - mins * 60000).toISOString();
const HEALTH = { connectors: [
    { connector: 'identity', status: 'working', last_success_at: ago(360), consecutive_failures: 0 },
    { connector: 'maps', status: 'working', last_success_at: ago(360), consecutive_failures: 0 },
    { connector: 'ai', status: 'down', last_error_at: ago(20), consecutive_failures: 4,
      last_error: '401 — the API key was rejected by Azure OpenAI' },
    { connector: 'translation', status: 'working', last_success_at: ago(1500), consecutive_failures: 0 },
    { connector: 'email', status: 'unknown', consecutive_failures: 0 },
    { connector: 'kms', status: 'working', last_success_at: ago(360), consecutive_failures: 0 },
    { connector: 'redaction', status: 'working', last_success_at: ago(360), consecutive_failures: 0 },
] };
const origFetch = window.fetch.bind(window);
window.fetch = async (input: any, init?: any) => {
    const url = String(typeof input === 'string' ? input : input.url);
    const json = (o: any) => new Response(JSON.stringify(o), { headers: { 'Content-Type': 'application/json' } });
    const m = url.match(/\/system\/([a-z]+)\/catalog/);
    if (m && CATALOGS[m[1]]) return json(CATALOGS[m[1]]);
    if (url.includes('cloud-identity')) return json({ attached: false, provider: null, identity: null, skippable_keys: [] });
    if (url.includes('connectors/health')) return json(HEALTH);
    if (url.includes('/system/')) return json({});
    return origFetch(input, init);
};

const DEPARTMENTS = [
    { id: 1, name: 'Public Works', description: 'Roads, potholes, street lighting and drainage', routing_email: 'publicworks@example.gov', is_active: true },
    { id: 2, name: 'Sanitation', description: 'Refuse collection, recycling and missed pickups', routing_email: 'sanitation@example.gov', is_active: true },
    { id: 3, name: 'Parks & Recreation', description: 'Parks, playgrounds, trees and public grounds', routing_email: null, is_active: true },
    { id: 4, name: 'Code Enforcement', description: 'Property maintenance and zoning complaints', routing_email: 'code@example.gov', is_active: true },
];

const SERVICES = [
    { id: 1, service_code: 'POTHOLE', service_name: 'Pothole', description: 'Damaged road surface', routing_mode: 'road_based', is_active: true, department_id: 1, display_order: 1 },
    { id: 2, service_code: 'STREETLIGHT', service_name: 'Street Light Out', description: 'Lighting fault on a public way', routing_mode: 'township', is_active: true, department_id: 1, display_order: 2 },
    { id: 3, service_code: 'MISSEDPICKUP', service_name: 'Missed Refuse Collection', description: 'Bins not emptied on the scheduled day', routing_mode: 'township', is_active: true, department_id: 2, display_order: 3 },
    { id: 4, service_code: 'TREE', service_name: 'Fallen or Damaged Tree', description: 'Trees on public land', routing_mode: 'third_party', is_active: true, department_id: 3, display_order: 4 },
];

const STATUS = {
    identity: { current_provider: 'entra', configured: { entra: false } },
    maps: { current_provider: 'google', configured: { google: true } },
    ai: { current_provider: 'azure', configured: { azure: false } },
    translation: { current_provider: 'azure', configured: { azure: false } },
    kms: { current_provider: 'azure', configured: { azure: false } },
};

function Section({ id, title, children }: any) {
    return (
        <section id={id} className="p-8 max-w-6xl mx-auto">
            <p className="text-[10px] uppercase tracking-widest text-white/25 mb-4">{title}</p>
            {children}
        </section>
    );
}

function App() {
    return (
        <div style={{ background: 'linear-gradient(135deg, #1e1b4b 0%, #312e81 50%, #1e1b4b 100%)', minHeight: '100vh' }}>
            <Section id="wizard" title="Current (for comparison)">
                <SetupWizard
                    cloud="azure" idp="entra" maps="google"
                    aiProvider="azure" emailProvider="acs" smsProvider="acs" redactionProvider="azure"
                    wanted={new Set(['ai', 'translation', 'secrets'])}
                    status={STATUS as any}
                    isDone={() => false}
                    secretValues={{}} onSecretChange={() => {}} onSaveSecrets={async () => {}}
                    savingSecret={null} isSecretConfigured={() => false}
                    onRefresh={() => {}} publicOrigin="https://311.example.gov"
                    renderFoundation={(cloud) => (
                        <div className="space-y-2.5">
                            <p className="text-[11px] uppercase tracking-wider text-white/45 font-semibold">First, the account</p>
                            <p className="text-sm text-white/70 pl-9">Create a resource group called <code className="bg-black/30 px-1 rounded text-blue-300 text-xs">pinpoint311-rg</code> in the {cloud} portal. Everything below goes in it.</p>
                        </div>
                    )}
                />
            </Section>

            <Section id="spotlight" title="Service providers — Spotlight, built for real">
                <ServiceProviders />
            </Section>

            <Section id="departments" title="Departments">
                <DepartmentsTab departments={DEPARTMENTS as any} onAdd={() => {}} onEdit={() => {}} onDelete={() => {}} />
            </Section>

            <Section id="categories" title="Service categories (for comparison)">
                <ServiceCategoriesTab
                    services={SERVICES as any} setServices={() => {}} loadTabData={() => {}}
                    setShowServiceModal={() => {}} handleEditService={() => {}} handleDeleteService={() => {}}
                />
            </Section>
        </div>
    );
}

createRoot(document.getElementById('root')!).render(<App />);
