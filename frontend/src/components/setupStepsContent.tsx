import { Check, Copy } from 'lucide-react';

import { awsDeployUrl, azureDeployUrl, templateBase } from './deployTemplateUrls';
import type { TemplateBase } from './deployTemplateUrls';
import { defineCloudFork, defineFork, defineSteps } from './setupSteps';
import type { StepBuilder, StepContext } from './setupSteps';

/**
 * The steps themselves, one registration per provider.
 *
 * Separate from setupSteps.tsx on purpose: that file is the mechanism and does
 * not go stale, this one is content about somebody else's console and will.
 * Vendors reorganise their menus on their own schedule, so entries here are
 * expected to be corrected over time, and a provider with no entry is a normal
 * state -- the card falls back to its plain field list.
 *
 * The rule for writing one: every step either does something or produces
 * something. `check` is what tells a clerk they are in the right place, and it
 * only earns its line when the next thing they do is paste a value. Where a
 * value must be copied exactly -- callback URLs, key restrictions -- give them
 * the copy button rather than a string to retype, because one missing character
 * fails silently and looks like a wrong password.
 *
 * The `fields` on each step are checked against the real credential catalogs by
 * backend/tests/test_setup_steps_content.py. A key invented from memory here
 * would otherwise render a box that saves to nothing, which is the failure this
 * whole page exists to avoid.
 */

/** A copy-to-clipboard chip for a value that must be exact. */
function CopyValue({ ctx, id, value }: { ctx: StepContext; id: string; value: string }) {
    return (
        <span className="inline-flex items-center gap-1 align-middle">
            <code className="bg-black/30 px-1.5 py-0.5 rounded text-[11px] text-primary-200 break-all">{value}</code>
            {/* Every chip on the page carried the identical name "Copy to
                clipboard", so a screen-reader user listing the buttons got a
                column of indistinguishable entries and no way to tell which
                value each one copies. Success was likewise a swapped icon and
                nothing else. */}
            <button
                type="button"
                onClick={() => ctx.copy(value, id)}
                aria-label={ctx.copied === id ? `Copied ${value}` : `Copy ${value} to clipboard`}
                className="inline-flex text-white/40 hover:text-white/80 transition-colors"
            >
                {ctx.copied === id
                    ? <Check className="w-3 h-3" aria-hidden="true" />
                    : <Copy className="w-3 h-3" aria-hidden="true" />}
            </button>
        </span>
    );
}

const B = ({ children }: { children: React.ReactNode }) => (
    <strong className="text-white/90">{children}</strong>
);

/** A vendor console link. Always new-tab: a clerk mid-setup who navigates away
 *  loses everything typed into the boxes below. */
const L = ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href} target="_blank" rel="noopener noreferrer"
        className="text-primary-300 underline underline-offset-2">{children}</a>
);

/**
 * One line saying where the file the cloud is about to read comes from.
 *
 * Worth the space because it is the only answer available to "the deployment
 * form came up empty". Both providers report a fetch they could not complete as
 * a broken template rather than as a URL they could not reach, so without this
 * there is nothing on the page to check and nothing to hand to whoever gets
 * asked. Which of the two it says is decided in deployTemplateUrls.ts.
 */
const TemplateSourceNote = ({ from }: { from: TemplateBase }) => (
    from.source === 'instance' ? (
        <span className="mt-1.5 block text-[11px] text-white/40">
            Your cloud fetches the template from this Pinpoint install, at{' '}
            <C>{from.base}/</C>…, so it matches this version. If residents can reach your portal,
            your cloud can reach this address.
        </span>
    ) : (
        <span className="mt-1.5 block text-[11px] text-white/40">
            This install has no public address yet, so the button uses the published copy on
            GitHub, which tracks the latest release. Once the town's domain is set, the template
            comes from this install instead.
        </span>
    )
);

/** A link that opens the provider's own deployment form. Drawn as a button
 *  because that is what it behaves like, and new-tab like every other console
 *  link here: a clerk mid-setup who navigates away loses what they have typed. */
/**
 * The claim a cautious IT department is actually testing.
 *
 * Every sentence is structural rather than a promise: the file is in front of
 * them, the provider renders it, and the provider has its own diff mechanism
 * that does not involve us. The last line matters most -- it is the answer to
 * "what could this do to our tenant", and the answer is bounded.
 */
const WHY_A_TEMPLATE_IS_SAFE = (
    <>
        It runs in <em>your</em> account, and the form you see is drawn by your cloud from a file you
        can read first. Nothing in it reaches us at deploy time — no script, no callback, no
        telemetry — and it emits no key or password as an output, because deployment history is
        readable by more people than the person deploying. Every permission it grants is scoped to
        the resources it just created.
    </>
);

const C = ({ children }: { children: React.ReactNode }) => (
    <code className="bg-black/30 px-1 rounded text-[11px] text-primary-200">{children}</code>
);

// ===========================================================================
// The one choice a cloud gets asked, before any of its cards
//
// Asked once, straight after "which company hosts your town's services", and it
// governs every capability on that cloud rather than one card. Azure's template
// creates the key vault AND the OpenAI account AND the multi-service AI account
// in a single deployment -- resources belonging to four different cards -- so
// the control that sets up nearly everything cannot live inside Key management,
// where a town that unticked key management would never see it at all.
//
// Google is absent from this registry on purpose. There is no one-click
// equivalent on Google and there is deliberately not going to be one: the
// honest alternative is Terraform, which needs a toolchain and a state file
// rather than a click. Offering a greyed-out button there would be a worse
// answer than the sentence in the Google walk that says so.
// ===========================================================================

defineCloudFork('azure', (ctx) => ({
    question: <>Two ways to set up Azure. Both are fully supported, both are kept current, and you can switch at any point.</>,
    launch: {
        href: azureDeployUrl(templateBase(ctx.origin).base),
        label: 'Open the Azure deployment form',
        line: <>Azure's Custom deployment form, with our template already loaded: the key vault, purge protection and the RSA key, plus the OpenAI, Translator and Vision resources if you want them. Pick a subscription and press <B>Create new</B> under Resource group. Nothing is created until you press Create on Azure's review page.</>,
        source: <TemplateSourceNote from={templateBase(ctx.origin)} />,
    },
    templateExtras: AZURE_TEMPLATE_EXTRAS(ctx),
    template: {
        label: 'Deploy with the Azure template',
        blurb: <>One form. Creates the key vault and, if you want them, the OpenAI, Translator and Vision resources.</>,
        switchLabel: 'Use the template instead',
    },
    manual: {
        label: 'Set it up by hand',
        blurb: <>The Azure portal, screen by screen. No template and no cloud shell, which some IT departments require.</>,
        switchLabel: 'Set it up by hand instead',
    },
    trust: {
        line: <>The template runs in your subscription and creates nothing outside it.</>,
        summary: 'What it can and cannot touch',
        body: WHY_A_TEMPLATE_IS_SAFE,
    },
}));

defineCloudFork('aws', (ctx) => ({
    question: <>Two ways to set up AWS. Both are fully supported, both are kept current, and you can switch at any point.</>,
    launch: {
        href: awsDeployUrl(templateBase(ctx.origin).base),
        label: 'Open the CloudFormation console',
        line: <>CloudFormation's Create stack page, with our template already loaded. Set your region in the console's top-right picker first. Every resource is listed on a review page before anything is created, and the stack creates a role rather than an access key.</>,
        source: <TemplateSourceNote from={templateBase(ctx.origin)} />,
    },
    templateExtras: AWS_TEMPLATE_EXTRAS(ctx),
    template: {
        label: 'Deploy with the CloudFormation template',
        blurb: <>One review page listing every resource first. Creates a role rather than an access key, so on AWS compute there is nothing to paste.</>,
        switchLabel: 'Use the template instead',
    },
    manual: {
        label: 'Set it up by hand',
        blurb: <>The AWS console, screen by screen. No template and no cloud shell, which some IT departments require.</>,
        switchLabel: 'Set it up by hand instead',
    },
    trust: {
        line: <>The stack runs in your account and creates nothing outside it.</>,
        summary: 'What it can and cannot touch',
        body: WHY_A_TEMPLATE_IS_SAFE,
    },
}));

// ===========================================================================
// Staff sign-in
//
// All three OIDC providers redirect to the same place. The callback URL goes in
// before the credentials come out in every one of them, because a tenant
// missing the redirect accepts the password and then fails on the way back,
// which reads to everybody as a wrong secret.
// ===========================================================================

const CALLBACK = (origin: string) => `${origin}/api/auth/callback`;

// ---------------------------------------------------------------------------
// Auth0
// ---------------------------------------------------------------------------

defineSteps('identity', 'auth0', (ctx) => [
    {
        body: (
            <>
                Create the account at <L href="https://auth0.com">auth0.com</L>, using a{' '}
                <B>shared town email address</B> rather than a personal one — whoever replaces you will
                need to get in. If your town or state requires data to stay in the US, pick a US region; it
                can't be changed later.
            </>
        ),
        check: <>the Auth0 dashboard, with your town's name in the top-left corner.</>,
    },
    {
        body: (
            <>
                In the left menu open <B>Applications → Applications</B> and press <B>Create
                Application</B>. Choose <B>Regular Web Application</B> — not Single Page, not Machine to
                Machine. If it then offers to pick a technology, close that; it only shows sample code.
            </>
        ),
        check: <>a settings page with boxes labeled Domain, Client ID and Client Secret.</>,
    },
    {
        body: (
            <>
                Still on <B>Settings</B>, scroll to <B>Application URIs</B> and paste these in, using the
                copy buttons rather than retyping:
                <span className="mt-2 grid gap-1.5">
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-40 shrink-0">Allowed Callback URLs</span>
                        <CopyValue ctx={ctx} id="a0cb" value={CALLBACK(ctx.origin)} />
                    </span>
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-40 shrink-0">Allowed Logout URLs</span>
                        <CopyValue ctx={ctx} id="a0lo" value={ctx.origin} />
                    </span>
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-40 shrink-0">Allowed Web Origins</span>
                        <CopyValue ctx={ctx} id="a0wo" value={ctx.origin} />
                    </span>
                </span>
                Then press <B>Save Changes</B> at the bottom.
            </>
        ),
        note: <>Do this before the next step. A tenant missing the callback URL accepts the password and then fails on the redirect, which looks like a wrong secret.</>,
    },
    {
        body: <>Copy the three values from that same Settings page into these boxes.</>,
        fields: ['AUTH0_DOMAIN', 'AUTH0_CLIENT_ID', 'AUTH0_CLIENT_SECRET'],
    },
]);

// ---------------------------------------------------------------------------
// Microsoft Entra ID
//
// The path most towns will actually take, because the staff already have
// Microsoft 365 accounts and Entra is the directory behind them. The one thing
// worth reading twice is the secret: Entra shows it once and then replaces it
// with dots forever, and the box beside it labelled "Secret ID" is not it.
// ---------------------------------------------------------------------------

defineSteps('identity', 'entra', (ctx) => [
    {
        body: (
            <>
                Sign in to the <L href="https://portal.azure.com">Azure portal</L> with an account that
                can administer your directory, open <B>Microsoft Entra ID</B>, and in the left pane choose{' '}
                <B>Manage → App registrations</B>, then <B>New registration</B>.
            </>
        ),
        check: <>a form headed "Register an application".</>,
    },
    {
        body: (
            <>
                Name it something a successor will recognize — <C>Pinpoint 311</C> is fine. Under{' '}
                <B>Redirect URI</B>, set the type to <B>Web</B> and paste{' '}
                <CopyValue ctx={ctx} id="enrd" value={CALLBACK(ctx.origin)} />. Leave the account-types
                option on the default (this directory only) unless your town shares staff with another
                tenant. Press <B>Register</B>.
            </>
        ),
        note: <>Choose Web, not "Single-page application". With the wrong type, staff sign-in fails with an error about the flow.</>,
    },
    {
        body: (
            <>
                The overview page that appears shows <B>Application (client) ID</B> and <B>Directory
                (tenant) ID</B>. Copy both here. Leave the authority box empty unless you are on a
                sovereign cloud — it defaults to the normal commercial endpoint.
            </>
        ),
        check: <>two GUIDs on the overview page, both looking like <C>8f3c…-…-…</C>.</>,
        fields: ['ENTRA_TENANT_ID', 'ENTRA_CLIENT_ID', 'ENTRA_AUTHORITY'],
    },
    {
        body: (
            <>
                In the left pane choose <B>Manage → Certificates &amp; secrets</B>, then{' '}
                <B>Client secrets → New client secret</B>. Give it a description and an expiry, press{' '}
                <B>Add</B>, and copy the <B>Value</B> column into the box below.
            </>
        ),
        fields: ['ENTRA_CLIENT_SECRET'],
        trouble: <>Copy it now. Entra shows the Value only once; if you leave the page, create a new secret. The <B>Secret ID</B> next to it is not the secret. Record the expiry date: staff sign-in stops working when the secret expires.</>,
    },
]);

// ---------------------------------------------------------------------------
// Okta
//
// The trap here is that the issuer is not on the application page. It lives
// under a different menu entirely, and the value people reach for -- the org
// URL in the address bar -- is close enough to look right and wrong enough to
// fail.
// ---------------------------------------------------------------------------

defineSteps('identity', 'okta', (ctx) => [
    {
        body: (
            <>
                In the Okta <B>Admin Console</B> (the "Admin" button in the top-right of the normal
                dashboard), open <B>Applications → Applications</B> and press <B>Create App
                Integration</B>. Choose <B>OIDC – OpenID Connect</B> as the sign-in method and{' '}
                <B>Web Application</B> as the application type, then <B>Next</B>.
            </>
        ),
        trouble: <>Web Application, not Single-Page Application. A SPA integration issues no client secret, and the box below will have nothing to put in it.</>,
    },
    {
        body: (
            <>
                Name it, then fill the two URL fields:
                <span className="mt-2 grid gap-1.5">
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-44 shrink-0">Sign-in redirect URIs</span>
                        <CopyValue ctx={ctx} id="okrd" value={CALLBACK(ctx.origin)} />
                    </span>
                    <span className="flex items-center gap-2 flex-wrap">
                        <span className="text-white/45 text-xs w-44 shrink-0">Sign-out redirect URIs</span>
                        <CopyValue ctx={ctx} id="oklo" value={ctx.origin} />
                    </span>
                </span>
                Under <B>Assignments</B>, pick the groups whose members should be able to sign in to
                Pinpoint, then <B>Save</B>.
            </>
        ),
        check: <>the app's <B>General</B> tab, with a <B>Client Credentials</B> section on it.</>,
    },
    {
        body: (
            <>
                Copy <B>Client ID</B> from that section, and press <B>Show</B> beside <B>Client
                secret</B> to reveal and copy the other.
            </>
        ),
        fields: ['OKTA_CLIENT_ID', 'OKTA_CLIENT_SECRET'],
    },
    {
        body: (
            <>
                The issuer is not on the application page. Open <B>Security → API</B> in the left menu.
                You will see more than one authorization server, and <B>either can be correct</B> — what
                matters is that the one you enter here is the one your app is set to use:
                <span className="mt-2 grid gap-1.5">
                    <span className="text-white/50 text-xs">
                        <B>Org</B> — issuer is your plain Okta domain, <C>https://your-org.okta.com</C>.
                        This is Okta's recommendation for ordinary single sign-on, which is all Pinpoint
                        does.
                    </span>
                    <span className="text-white/50 text-xs">
                        <B>default</B> (a custom server) — issuer ends <C>/oauth2/default</C>. Use this if
                        your Okta administrator has put claims or policies on it.
                    </span>
                </span>
                If you are unsure, ask whoever administers Okta which one the app was assigned to.
            </>
        ),
        fields: ['OKTA_ISSUER'],
        note: <>You can check the value before saving: paste <C>{'<issuer>'}/.well-known/openid-configuration</C> into a browser. A page of JSON means it is right; a 404 or an error means it is not.</>,
    },
]);

// ---------------------------------------------------------------------------
// Generic OIDC
//
// For a state-run identity provider, Keycloak, Shibboleth, or anything else
// standards-compliant. Written as questions to ask whoever runs it rather than
// as a menu path, because there is no menu to describe.
// ---------------------------------------------------------------------------

defineSteps('identity', 'oidc', (ctx) => [
    {
        body: (
            <>
                Ask whoever operates your identity provider to register a <B>confidential client</B>{' '}
                (sometimes called a web or server-side application) using the <B>authorization code</B>{' '}
                flow, with this redirect URI: <CopyValue ctx={ctx} id="oidcrd" value={CALLBACK(ctx.origin)} />.
                Ask for the scopes <C>openid</C>, <C>profile</C> and <C>email</C> — Pinpoint matches staff
                accounts by email address, so a provider that does not release it cannot be used.
            </>
        ),
        note: <>If they offer a "public client", that is the wrong kind: it issues no secret. Say confidential, or server-side.</>,
    },
    {
        body: (
            <>
                Ask for the <B>issuer URL</B> — the base address, not the full endpoint. To check it, open{' '}
                <C>{'<issuer>'}/.well-known/openid-configuration</C> in a browser. A page of JSON means it
                is right; a 404 means it is wrong.
            </>
        ),
        fields: ['OIDC_ISSUER'],
    },
    {
        body: <>Then the client's ID and secret.</>,
        fields: ['OIDC_CLIENT_ID', 'OIDC_CLIENT_SECRET'],
    },
]);

// ===========================================================================
// Maps
// ===========================================================================

// ---------------------------------------------------------------------------
// Google Maps
//
// Billing is step one rather than a footnote: without it Google issues a key
// that looks correct and the map shows a grey box, which is the single most
// common failure on this page.
// ---------------------------------------------------------------------------

defineSteps('maps', 'google', (ctx) => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, open{' '}
                <B>APIs &amp; Services → Library</B> and enable all four: <C>Maps JavaScript API</C>,{' '}
                <C>Maps Embed API</C>, <C>Geocoding API</C> and <C>Places API (New)</C>. Then open{' '}
                <B>Billing</B> and attach a payment method.
            </>
        ),
        check: <>an "API Enabled" banner on each of the four, and a billing account listed under Billing.</>,
        trouble: (
            <>
                Billing is required. Google will issue a key without it, but the map then shows a gray box
                saying "this page can't load Google Maps correctly". Enable <C>Places API (New)</C>,
                not the legacy <C>Places API</C>, or the address box offers no suggestions.
            </>
        ),
    },
    {
        body: (
            <>
                Make <B>two</B> keys under <B>Credentials → Create Credentials → API key</B>. Google
                allows one restriction per key and the two uses need opposite ones.
                <br /><br />
                <B>Browser key</B> — restrict to <B>Websites</B>, add{' '}
                <CopyValue ctx={ctx} id="gmref" value={`${ctx.origin}/*`} /> (the <C>/*</C> matters), and
                check all four: <C>Maps JavaScript API</C>, <C>Maps Embed API</C>,{' '}
                <C>Places API (New)</C> and <C>Geocoding API</C>.
                <br /><br />
                <B>Server key</B> — restrict to <B>IP addresses</B>, add this server's, and check{' '}
                <C>Geocoding API</C> and <C>Places API (New)</C>.
            </>
        ),
        check: <>two keys: one restricted to your site with all four APIs, one restricted to this server's IP with <C>Geocoding API</C> and <C>Places API (New)</C>.</>,
        trouble: (
            <>
                Restrict both keys so they can't be used elsewhere and billed to the town. The Test
                button can't check a website-restricted key from the server; open the report form to
                confirm it works.
            </>
        ),
    },
    {
        body: <>Paste both keys in their own boxes. The Map ID is optional — leave it empty. To run one key for both, put the same value in both boxes.</>,
        fields: ['GOOGLE_MAPS_API_KEY', 'GOOGLE_MAPS_BROWSER_API_KEY', 'GOOGLE_MAPS_MAP_ID'],
        note: <>Changes to a Google key can take up to five minutes. If the map is still gray right after saving, wait before changing anything else.</>,
    },
]);

// ---------------------------------------------------------------------------
// Esri / ArcGIS
//
// The one most likely to already be in place: a town with a GIS department has
// an ArcGIS organisation, and often its own address locator, which is better
// than any national geocoder at finding a local address.
// ---------------------------------------------------------------------------

defineSteps('maps', 'esri', () => [
    {
        body: (
            <>
                Before anything else, ask your GIS department whether the town already has an ArcGIS
                organization. If it does, create the key there rather than on a personal developer
                account, so the town owns it.
            </>
        ),
    },
    {
        body: (
            <>
                Sign in at <L href="https://location.arcgis.com">location.arcgis.com</L>, open the
                developer dashboard, and create an <B>API key</B> credential. Scope it to the services
                you need: <B>Basemap styles</B> and <B>Geocoding</B> at minimum. ArcGIS API keys last up to a
                year, so set an expiry date you'll track.
            </>
        ),
        check: <>a new API key credential in the developer dashboard. Older legacy API keys no longer work; create a new credential if yours predates it.</>,
        note: <>Record the expiry date where the town will see it. Keys expire at 00:00 GMT on that date, and the map goes blank until a new key is saved.</>,
    },
    {
        body: (
            <>
                Paste the key. Both other boxes are optional: the basemap is an Esri style id (for
                example <C>arcgis/navigation</C>) if you want something other than the default, and the
                locator is the URL of your own address locator service if the GIS department publishes
                one. Two key boxes: the browser one goes into the page residents load, so scope that
                credential to <B>Basemaps</B> and set its referrer to your domain; the server one does
                the geocoding. To use one key, put the same value in both.
            </>
        ),
        fields: ['ARCGIS_API_KEY', 'ARCGIS_BROWSER_API_KEY', 'ARCGIS_BASEMAP_ID', 'ARCGIS_LOCATOR_URL'],
        note: <>Ask for the town locator if one exists. It knows your local street names, address ranges and new subdivisions.</>,
    },
]);

// ---------------------------------------------------------------------------
// Azure Maps
// ---------------------------------------------------------------------------

defineSteps('maps', 'azure', () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L>, press <B>Create a
                resource</B>, search for <B>Azure Maps</B>, and create an account in the same
                subscription and region as the rest of your Azure services.
            </>
        ),
        check: <>the new Maps account's overview page.</>,
    },
    {
        body: (
            <>
                Open <B>Settings → Authentication</B> on that account and copy the <B>Primary Key</B>{' '}
                under Shared Key Authentication.
            </>
        ),
        fields: ['AZURE_MAPS_KEY', 'AZURE_MAPS_BROWSER_KEY'],
        note: <>Use the primary key and keep the secondary for rotation. Azure shared keys can't be restricted by origin, so put the primary key in both boxes unless you run a second Maps account for the browser.</>,
    },
]);

// ---------------------------------------------------------------------------
// Apple Maps
//
// The most involved of the four and the only one where a downloaded file is the
// credential. It also requires a paid Apple Developer membership, which is
// worth saying at the top rather than discovering at step three.
// ---------------------------------------------------------------------------

defineSteps('maps', 'apple', () => [
    {
        body: (
            <>
                This needs a paid <L href="https://developer.apple.com/programs/">Apple Developer
                Program</L> membership held by the town, not by a person. Without one,
                choose a different map provider.
            </>
        ),
    },
    {
        body: (
            <>
                At <L href="https://developer.apple.com/account">developer.apple.com/account</L> open{' '}
                <B>Certificates, Identifiers &amp; Profiles → Identifiers</B>, press <B>+</B>, and create
                an identifier of type <B>Maps IDs</B>.
            </>
        ),
        check: <>your new Maps ID in the identifiers list.</>,
    },
    {
        body: (
            <>
                Then open <B>Keys</B> in the same sidebar, press <B>+</B>, check <B>MapKit JS</B>, and
                configure it to use the Maps ID you just made. Create the key and press <B>Download</B>.
                You get a file named <C>AuthKey_XXXXXXXXXX.p8</C>.
            </>
        ),
        trouble: <>Download it now and keep it. Apple allows one download; if the file is lost, revoke the key and create a new one.</>,
    },
    {
        body: (
            <>
                The <B>Key ID</B> is on that key's page. The <B>Team ID</B> is in{' '}
                <B>Membership details</B> at the top of your account. For the private key, open the{' '}
                <C>.p8</C> file in a plain text editor and paste the whole contents — including the{' '}
                <C>-----BEGIN PRIVATE KEY-----</C> and <C>-----END PRIVATE KEY-----</C> lines.
            </>
        ),
        fields: ['APPLE_MAPKIT_TEAM_ID', 'APPLE_MAPKIT_KEY_ID', 'APPLE_MAPKIT_PRIVATE_KEY'],
        note: <>Use a plain text editor, not Word, which adds formatting that breaks the key. Include the header and footer lines.</>,
    },
]);

// ===========================================================================
// AI analysis
// ===========================================================================

defineSteps('ai', 'vertex', () => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, select or create the
                project you want to bill this to, then open <B>APIs &amp; Services → Library</B> and
                enable <C>Vertex AI API</C>. Attach a billing account if the project has none.
            </>
        ),
        check: <>"API Enabled" on the Vertex AI API page.</>,
    },
    {
        body: (
            <>
                Open <B>IAM &amp; Admin → Service Accounts</B> and create one — a name like{' '}
                <C>pinpoint-311</C> is fine. Grant it the <B>Vertex AI User</B> role. Don't grant Owner
                or Editor; this account only needs to call the model.
            </>
        ),
        note: <>Vertex AI User limits what a leaked key can do. A key with Editor can delete the project.</>,
    },
    {
        body: (
            <>
                On that service account open <B>Keys → Add Key → Create new key → JSON</B>. A file
                downloads. Open it in a plain text editor and paste the whole contents below, along with
                your project ID (it is in the file, as <C>project_id</C>).
            </>
        ),
        fields: ['VERTEX_AI_PROJECT', 'VERTEX_AI_SERVICE_ACCOUNT_KEY'],
        trouble: <>Delete the downloaded file once it is saved here. It grants access to your cloud account.</>,
    },
]);

defineSteps('ai', 'azure', () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L>, create an <B>Azure OpenAI</B>{' '}
                resource in a region your town is allowed to use. No application or approval is needed for
                the standard models.
            </>
        ),
        note: <>Older guides describe a registration form and a wait. Microsoft removed that for general access, and Pinpoint uses none of the restricted features that still require it.</>,
    },
    {
        body: (
            <>
                Open the resource in <L href="https://ai.azure.com">Microsoft Foundry</L> and deploy a
                model — <B>Deployments → Deploy model</B>. Enter the <B>deployment name</B> you choose in
                the box below. It can differ from the model name. Pick a model that accepts images
                and JSON output, like <C>gpt-4.1-mini</C> or <C>gpt-4o</C>.
            </>
        ),
        check: <>your deployment listed with status Succeeded.</>,
    },
    {
        body: (
            <>
                Back on the Azure resource, open <B>Resource Management → Keys and Endpoint</B> and copy{' '}
                <B>KEY 1</B> and the <B>Endpoint</B>. Leave the API version box empty for most
                models. For an o-series or GPT-5 deployment, enter <C>2024-12-01-preview</C> or later.
            </>
        ),
        fields: ['AZURE_OPENAI_ENDPOINT', 'AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_DEPLOYMENT', 'AZURE_OPENAI_API_VERSION'],
        note: <>The endpoint is the base address ending in a slash, not the full chat-completions URL from the sample code.</>,
    },
]);

defineSteps('ai', 'bedrock', () => [
    {
        body: (
            <>
                In the <L href="https://console.aws.amazon.com/bedrock">Bedrock console</L>, set the
                region selector (top right) to the region you'll use. Model availability differs by
                region, and the steps below depend on it.
            </>
        ),
    },
    {
        body: (
            <>
                Serverless models turn on the first time they are called. Anthropic models also need a
                one-time use-case form: open a Claude model in the Bedrock console's model catalog and
                submit it.
            </>
        ),
        note: <>The first call to a Marketplace model subscribes the account, which needs the permissions in the next step.</>,
    },
    {
        body: (
            <>
                Create an IAM user for Pinpoint with permission to invoke models —{' '}
                <C>bedrock:InvokeModel</C> and <C>bedrock:InvokeModelWithResponseStream</C>, plus{' '}
                <C>aws-marketplace:Subscribe</C> and <C>aws-marketplace:ViewSubscriptions</C> for a
                model's first use. Take an access key from <B>Security credentials</B> and paste it here with the same
                region you set above.
            </>
        ),
        fields: ['AWS_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'],
        trouble: <>The secret access key is shown only once. If you miss it, create a new one.</>,
    },
]);

// ===========================================================================
// Translation
// ===========================================================================

defineSteps('translation', 'google', () => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, open{' '}
                <B>APIs &amp; Services → Library</B> and enable <C>Cloud Translation API</C> in the same
                project you are using elsewhere.
            </>
        ),
        check: <>"API Enabled" on the Cloud Translation API page.</>,
    },
    {
        body: (
            <>
                That's all. Translation uses the Google service account entered at Setup, so there
                is nothing to enter here.
            </>
        ),
        note: <>If this card says the service account is missing, add it at Setup. It can't be edited from a provider card.</>,
    },
]);

/* Forked, because the template already made the account.
 *
 * These steps used to open with "press Create a resource and create a
 * Translator resource" for everybody. An operator who had just run the
 * deployment template therefore created a second, redundant Translator resource
 * -- billed separately, in whatever region they happened to pick, and not the
 * one the template's own `translatorRegion` output names. The template creates
 * one multi-service AI Services account precisely so that translation, vision
 * and face share a key; there is nothing left to create.
 *
 * Named StepBuilder consts rather than inline arrays: the fields each path
 * claims are read out of this file's source by
 * backend/tests/test_setup_steps_content.py, and it resolves a fork through the
 * builder names. An inline array is invisible to it, which silently drops both
 * paths out of every check that file makes.
 */
const azureTranslatorTemplateSteps: StepBuilder = () => [
    {
        body: (
            <>
                <B>Nothing to create.</B> The deployment already made the AI Services account
                that serves Translator — the same one behind photo redaction. Its region came
                back as the <C>translatorRegion</C> output, so if you pasted the outputs the
                region box below is already filled.
            </>
        ),
        check: <>a region already in the box below, matching the deployment's output.</>,
    },
    {
        body: (
            <>
                Open your <B>AI Services</B> account (the one the deployment created, not a new Translator resource) → <B>Resource Management → Keys and Endpoint</B> and copy{' '}
                <B>KEY 1</B> and the <B>Location/Region</B> value. If you filled in{' '}
                <B>Allowed IP address</B> on the form, paste the account's endpoint
                (<C>https://NAME.cognitiveservices.azure.com/</C>) in the endpoint box, because the
                firewall blocks the global one. Otherwise leave it empty.
            </>
        ),
        fields: ['AZURE_TRANSLATOR_KEY', 'AZURE_TRANSLATOR_REGION', 'AZURE_TRANSLATOR_ENDPOINT'],
        check: <>a key pasted in and a region like <C>eastus</C> beside it.</>,
        note: <>The region must be the short form shown on that page, like <C>eastus</C>, not "East US". A wrong region shows up as a bad-key error.</>,
    },
];

const azureTranslatorManualSteps: StepBuilder = () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L>, press <B>Create a
                resource</B> and create a <B>Translator</B> resource. Pick the tier that suits a
                small town's volume; note the <B>region</B> you pick, because it is part of the
                credentials.
            </>
        ),
        check: <>the Translator resource listed in your resource group.</>,
    },
    {
        body: (
            <>
                Open that resource → <B>Resource Management → Keys and Endpoint</B> and copy{' '}
                <B>KEY 1</B> and the <B>Location/Region</B> value. Leave the endpoint box empty
                unless you were given a custom one.
            </>
        ),
        fields: ['AZURE_TRANSLATOR_KEY', 'AZURE_TRANSLATOR_REGION', 'AZURE_TRANSLATOR_ENDPOINT'],
        check: <>a key pasted in and a region like <C>eastus</C> beside it.</>,
        note: <>The region must be the short form shown on that page, like <C>eastus</C>, not "East US". A wrong region shows up as a bad-key error.</>,
    },
];

defineFork('translation', 'azure', (ctx) => ({
    template: azureTranslatorTemplateSteps(ctx),
    manual: azureTranslatorManualSteps(ctx),
}));

defineSteps('translation', 'aws', () => [
    {
        body: (
            <>
                Amazon Translate needs no setup in its own console — it is on by default. Create an IAM
                user for Pinpoint with the <C>TranslateReadOnly</C> managed policy, which despite the
                name is what permits translating text.
            </>
        ),
        note: <>If you already have an IAM user for Bedrock or SES, add this policy to that user instead of creating new keys.</>,
    },
    {
        body: <>Take an access key from that user's <B>Security credentials</B> tab and enter it with your region.</>,
        fields: ['AWS_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'],
    },
]);

// ===========================================================================
// Email
// ===========================================================================

defineSteps('email', 'smtp', () => [
    {
        body: (
            <>
                Ask whoever runs the town's email for the SMTP server address and port, and for a
                dedicated account to send from. Residents' replies to status updates go to this
                account.
            </>
        ),
        note: <>Google Workspace blocks password sign-in for SMTP by default. At the end of December 2026, Microsoft 365 turns password-based SMTP off by default; admins can turn it back on. On Microsoft 365, SES or Azure Communication Services is the durable choice.</>,
    },
    {
        body: (
            <>
                Fill in the server details. Use port <C>587</C> with STARTTLS. Port <C>465</C>{' '}
                (implicit TLS) also works if you set the TLS box to <C>false</C>.
            </>
        ),
        fields: ['SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_USE_TLS'],
        note: <>On Brevo: host <C>smtp-relay.brevo.com</C>, port <C>587</C>. The username is the Login shown under <B>Settings → SMTP &amp; API</B>, and the password is an SMTP key, not an API key.</>,
    },
    {
        body: (
            <>
                Then what residents see in their inbox. Use a monitored address such as{' '}
                <C>311@yourtown.gov</C> rather than <C>noreply@</C>, because residents reply to these.
                On Brevo, it must be a verified sender or on an authenticated domain.
            </>
        ),
        fields: ['SMTP_FROM_EMAIL', 'SMTP_FROM_NAME'],
    },
]);

defineSteps('email', 'ses', () => [
    {
        body: (
            <>
                In the <L href="https://console.aws.amazon.com/ses">SES console</L>, set your region,
                then open <B>Identities → Create identity</B> and verify your <B>domain</B> — not just a
                single address. A verified domain lets you send from any address on it and enables DKIM.
            </>
        ),
        check: <>the identity showing <B>Verified</B>. It requires DNS records, so whoever manages the town's DNS needs to be involved.</>,
    },
    {
        body: (
            <>
                New SES accounts are in the <B>sandbox</B> and can only send to addresses you have also
                verified, so residents receive nothing. Open <B>Account dashboard</B> and press{' '}
                <B>Request production access</B>.
            </>
        ),
        trouble: <>Complete this before launch. In the sandbox, SES rejects mail to residents with "Email address is not verified".</>,
    },
    {
        body: (
            <>
                Create an IAM user for Pinpoint with the <C>AmazonSESFullAccess</C> policy (or only{' '}
                <C>ses:SendEmail</C>, <C>ses:SendRawEmail</C> and <C>ses:GetSendQuota</C>), then
                fill these in. The from address must be on the domain you verified.
            </>
        ),
        fields: ['AWS_REGION', 'SES_FROM_EMAIL', 'SMTP_FROM_NAME', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY'],
        note: <>The region must be the one where you verified the domain. A different region reports an unverified sender.</>,
    },
]);

defineSteps('email', 'acs', () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L> create two resources:{' '}
                <B>Communication Services</B>, and <B>Email Communication Services</B>. Both are needed,
                and they must be in the <B>same geography</B> to connect.
            </>
        ),
        note: <>The names are similar. The Email resource holds the domain; the Communication Services resource holds the endpoint and key.</>,
    },
    {
        body: (
            <>
                On the Email resource, add a domain. <B>Add a free Azure subdomain</B> is one click and
                works immediately, but sends from an <C>azurecomm.net</C> address, which residents will
                not recognize as the town. <B>Set up a custom domain</B> takes DNS records (TXT, SPF and
                DKIM) and is the right choice for public-facing email.
            </>
        ),
        check: <>the domain listed with verification complete, and a MailFrom address shown on its page.</>,
    },
    {
        body: (
            <>
                Open the Communication Services resource, go to <B>Email → Domains</B> and press{' '}
                <B>Connect domain</B> to link the one you just made.
            </>
        ),
    },
    {
        body: (
            <>
                Then on that same resource open <B>Settings → Keys</B> and copy the <B>Endpoint</B> and{' '}
                <B>Primary key</B>. The from address is the MailFrom value on the domain page.
            </>
        ),
        fields: ['ACS_ENDPOINT', 'ACS_ACCESS_KEY', 'ACS_FROM_EMAIL', 'SMTP_FROM_NAME'],
    },
]);

// ===========================================================================
// Text messages
// ===========================================================================

defineSteps('sms', 'twilio', () => [
    {
        body: (
            <>
                Sign in at <L href="https://console.twilio.com">console.twilio.com</L>. The{' '}
                <B>Account SID</B> and <B>Auth Token</B> are on the dashboard home page.
            </>
        ),
        fields: ['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN'],
    },
    {
        body: <>Buy or select a number under <B>Phone Numbers → Manage → Active numbers</B>, and enter it in <C>+1XXXXXXXXXX</C> form.</>,
        fields: ['TWILIO_PHONE_NUMBER'],
        note: <>Use a number you own in Twilio. A trial account can only text numbers you have verified. To text US numbers from a local number, register for A2P 10DLC in Twilio, or use a verified toll-free number.</>,
    },
]);

defineSteps('sms', 'sns', () => [
    {
        body: (
            <>
                In the <L href="https://console.aws.amazon.com/sns">SNS console</L>, open <B>Text
                messaging (SMS)</B> in the left pane and check the account status at the top. A new
                account is in the <B>SMS sandbox</B> and can only text numbers you have verified there.
            </>
        ),
        trouble: <>Leave the sandbox from that same page before launch. In the sandbox, messages to residents are rejected and the error appears only in the log.</>,
    },
    {
        body: (
            <>
                Still on that page, set a <B>monthly spending limit</B> you are comfortable with, then
                register an origination identity. For a US municipality that is a{' '}
                <B>10DLC</B> number, which requires registering the town as a brand. Carriers filter
                unregistered traffic.
            </>
        ),
        note: <>Start the 10DLC registration early. It is a carrier process rather than an AWS one, and it is not immediate.</>,
    },
    {
        body: (
            <>
                Create an IAM user for Pinpoint with permission for <C>sns:Publish</C> and{' '}
                <C>sns:GetSMSAttributes</C>, and enter its
                access key with your region. The sender ID box is optional and has no effect on US numbers.
            </>
        ),
        fields: ['AWS_REGION', 'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'SMS_SENDER_ID'],
    },
]);

defineSteps('sms', 'acs', () => [
    {
        body: (
            <>
                <B>Register before you try to buy a number.</B> On the Communication Services resource,
                open <B>Telephony and SMS → Regulatory Documents</B> and complete the 10DLC{' '}
                <B>brand</B> and <B>campaign</B> registration for the town. In the US, both must be
                approved before you can acquire or SMS-enable a number.
            </>
        ),
        note: <>This requires a paid Azure subscription; trials and free credits can't acquire numbers. Availability depends on your billing country.</>,
    },
    {
        body: (
            <>
                Once registration is approved, go to <B>Telephony and SMS → Phone numbers</B> and acquire
                a number with SMS among its capabilities. Use the same Communication Services resource as
                email if you already made one.
            </>
        ),
        check: <>the number listed with SMS in its capabilities.</>,
    },
    {
        body: (
            <>
                Then <B>Settings → Keys</B> on that resource for the endpoint and key, and the number you
                just acquired in <C>+1XXXXXXXXXX</C> form.
            </>
        ),
        fields: ['ACS_ENDPOINT', 'ACS_ACCESS_KEY', 'SMS_FROM_NUMBER'],
    },
]);

defineSteps('sms', 'http', () => [
    {
        body: (
            <>
                For a gateway not listed here — a regional carrier, a state contract, an existing
                notification system. Pinpoint POSTs JSON with the number and the message, and treats
                any 2xx as delivered.
            </>
        ),
    },
    {
        body: (
            <>
                Enter the endpoint URL your provider gave you, and the key they issued. The key is sent
                as a bearer token. Add a sender number only if your gateway requires one.
            </>
        ),
        fields: ['SMS_HTTP_API_URL', 'SMS_HTTP_API_KEY', 'SMS_FROM_NUMBER'],
        note: <>The gateway must accept this request format. Confirm with your provider, then send yourself a test message with the button below.</>,
    },
    {
        body: (
            <>
                If your gateway publishes a URL that reports your balance, quota or key status,
                paste it here so this card can check the connection without sending a message.
            </>
        ),
        fields: ['SMS_HTTP_TEST_URL'],
        note: <>Optional. Pinpoint only reads from this URL. If it's blank, the card shows that the connection can't be checked.</>,
    },
]);

/**
 * The risk none of the key-level controls cover.
 *
 * Denying deletion, purge protection and liens all stop somebody deleting the
 * *key*. None of them survives the loss of the *account* that holds it, and for
 * a municipality that is the likelier way this ends: a card that expires
 * between budget cycles, a subscription opened on a departing employee's
 * personal account, a purchasing gap nobody notices until the disable notice.
 *
 * Verified timelines, all of which start quietly: an Azure subscription is
 * deleted 90 days after cancellation and its resources go with it; an AWS
 * account's resources are deleted 90 days after closure; a deleted Google
 * project takes its key ring, and Google commits to erasing the key material
 * within 45 days. The key survives none of those, and no setting inside the key
 * changes it.
 */
const ACCOUNT_SURVIVES = (
    <>
        <B>Look after the account, not only the key.</B> A closed account takes the key with it, so
        put the cloud account in the town's name on a town payment method, make more than one person
        an administrator, and send billing alerts to a shared address.
    </>
);

// ===========================================================================
// Key management for resident data
//
// These wrap the key that encrypts resident names, emails and phone numbers.
// The recurring warning is the same in all three: this key is not something you
// can lose and re-create. Losing it means the data it protected is gone.
// ===========================================================================

/**
 * The identity a deployment running *on* the cloud already has.
 *
 * Every cloud attaches one to the compute, `cloud_identity.py` detects it, and
 * the card greys out the boxes it replaces. It belongs in the walk as well,
 * because by the time a clerk reads the card they have usually already created
 * the credential it would have saved them -- and on Azure that credential is a
 * client secret with an expiry date nobody records.
 */
const ATTACHED_IDENTITY = (
    <>
        If this server runs on the same cloud, skip creating a credential: grant the role to the
        machine's own identity instead. There's nothing to copy and nothing expires.
    </>
);

defineSteps('kms', 'google', () => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, enable{' '}
                <C>Cloud KMS API</C>. Under <B>Security → Key Management</B>, create a <B>key ring</B>,
                then a <B>key</B> inside it: purpose <B>Symmetric encrypt/decrypt</B>, rotation 90 days.
            </>
        ),
        check: <>your key listed inside your key ring.</>,
        trouble: <>Set the <B>destroy scheduled duration</B> on that same form — 24 hours minimum, 30 days default, up to 120 days. It is only offered at creation.</>,
        note: <>Requires Cloud KMS Admin or Owner; Project Editor can't create keys. Google has no one-click template, so set this up by hand.</>,
    },
    {
        body: (
            <>
                On the key's own permissions panel, grant the service account this deployment uses{' '}
                <B>Cloud KMS CryptoKey Encrypter/Decrypter</B> — on the key, not on the
                project. {ATTACHED_IDENTITY}
            </>
        ),
        check: <>the service account listed in the key's permissions, not only in the project's.</>,
        trouble: <>Without this role, settings still save, but resident data is quietly encrypted with the application key instead. The health dashboard shows when that happens.</>,
    },
    {
        body: (
            <>
                Enter them as the console shows them. The location is the short form, like{' '}
                <C>us-central1</C>. The project and service account JSON go in Setup, not here.
            </>
        ),
        fields: ['KMS_LOCATION', 'KMS_KEY_RING', 'KMS_KEY_ID'],
    },
    {
        body: (
            <>
                <B>Check who can destroy a version.</B> Rotating is safe; old versions keep
                decrypting old rows. Destroying a version is permanent, so make sure no everyday account
                holds{' '}
                <C>cloudkms.cryptoKeyVersions.destroy</C> on this key.
            </>
        ),
        check: <>only administrators holding destroy on this key.</>,
        trouble: <>A destroyed version cannot be recovered, by you or by Google.</>,
    },
    {
        body: (
            <>
                <B>Protect the project too.</B> Deleting the project takes the key ring with it,
                whatever is set on the key. A <B>lien</B> blocks that until somebody removes the lien:
                <span className="mt-2 block"><C>gcloud alpha resource-manager liens create --project=YOUR_PROJECT --restrictions=resourcemanager.projects.delete --reason="Holds the Pinpoint 311 PII encryption key"</C></span>
            </>
        ),
        check: <>the lien returned by <C>liens list</C>.</>,
        note: <>No command line? Whoever manages your Google Cloud billing can run it.</>,
    },
    {
        body: <>{ACCOUNT_SURVIVES}</>,
    },
]);

/**
 * The Azure walk, done in the portal.
 *
 * Complete on its own and numbered from 1, because for a good number of towns
 * it is the only path there is: templates and cloud shells are forbidden
 * outright by plenty of government IT policies. A walk written as the
 * consolation prize for those readers would be both insulting and, in the end,
 * the one nobody maintains.
 */
const azureManualSteps: StepBuilder = () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L>, create a <B>Key Vault</B>.
                On the <B>Access configuration</B> tab, leave <B>Azure role-based access control</B>
                {' '}selected — that is what the steps below assume. Turn on <B>purge protection</B>{' '}
                beside the retention period.
            </>
        ),
        check: <>the vault's overview, showing a URL ending <C>.vault.azure.net</C>.</>,
        trouble: <>Turn on purge protection now. It can be turned on later, but never turned off.</>,
    },
    {
        body: (
            <>
                <B>Give yourself permission to use the vault.</B> Creating one grants its creator no
                access to the keys inside. On the vault's <B>Access control (IAM)</B>, assign yourself{' '}
                <B>Key Vault Crypto Officer</B>.
            </>
        ),
        check: <>your account on the vault's role assignments as Key Vault Crypto Officer.</>,
        note: <>Role assignments can take a moment to apply. On the older access policy model, add yourself under the vault's access policies instead.</>,
    },
    {
        body: <>Open the vault's <B>Objects → Keys</B> and use <B>Generate/Import</B> to create an <B>RSA</B> key. 2048 or 4096, either is fine. Note its name.</>,
        check: <>the key listed, status Enabled.</>,
        trouble: <>"Not authorized to view the contents" means the role above has not arrived yet, or went on something other than the vault.</>,
    },
    {
        body: (
            <>
                Now the identity Pinpoint signs in as. {ATTACHED_IDENTITY} Otherwise open{' '}
                <B>Microsoft Entra ID → App registrations → New registration</B>. Choose{' '}
                <B>Accounts in this organizational directory only</B> and leave{' '}
                <B>Redirect URI</B> empty — this app never signs a person in, so it needs none. Then
                open its <B>Certificates &amp; secrets</B> and add a client secret. Copy its{' '}
                <B>Value</B> now.
            </>
        ),
        check: <>an Application (client) ID and Directory (tenant) ID on the app's overview, and a copied Value.</>,
        trouble: <>Entra shows the Value once. The box beside it labeled <B>Secret ID</B> is a different thing.</>,
    },
    {
        body: (
            <>
                Back on the vault's <B>Access control (IAM)</B>, assign that identity <B>Key Vault
                Crypto User</B>: it wraps and unwraps with this key and does nothing else.
            </>
        ),
        check: <>that identity on the vault's role assignments as Key Vault Crypto User.</>,
        trouble: <>On the older access policy model, grant the key permissions <B>Wrap Key</B> and <B>Unwrap Key</B>.</>,
    },
    {
        body: <>Fill these in. The vault URL is the <C>https://yourvault.vault.azure.net/</C> address on the overview.</>,
        fields: ['AZURE_KEYVAULT_URL', 'AZURE_KEYVAULT_KEY', 'AZURE_TENANT_ID', 'AZURE_KEYVAULT_CLIENT_ID', 'AZURE_KEYVAULT_CLIENT_SECRET', 'AZURE_KEYVAULT_CLIENT_SECRET_EXPIRES'],
        note: <>On a managed identity the last three stay empty. A client secret expires; add a reminder to the town's calendar a month ahead, because decryption stops on that date.</>,
    },
    {
        body: (
            <>
                Under <B>Settings → Locks</B>, add a <B>Delete</B> lock. It blocks deletion of the vault,
                even by accounts with delete permission. You can now remove your own Crypto Officer
                role; Pinpoint doesn't use it.
            </>
        ),
        check: <>a Delete lock on the vault, and Properties showing soft delete and purge protection enabled.</>,
        note: <>Confirm that everyday accounts hold neither Delete nor Purge on keys.</>,
    },
    {
        body: (
            <>
                <B>Decide about the audit trail.</B> Azure keeps no record of key use unless a
                diagnostic setting routes it somewhere. Under the vault's <B>Monitoring → Diagnostic
                settings</B>, add one for <C>AuditEvent</C> pointing at a Log Analytics workspace or a
                storage account.
            </>
        ),
        check: <>a diagnostic setting on the vault with AuditEvent checked.</>,
        note: <>Logging starts when you add the setting. Skip this step if your town doesn't need the trail.</>,
    },
    {
        body: <>{ACCOUNT_SURVIVES}</>,
    },
];

/**
 * The Azure walk, done by handing the template to Azure's own form.
 *
 * Shorter than the manual walk but not a subset of it: what the template cannot
 * do — the directory objects — is still here, because a path that stops before
 * the deployment can actually use the key is not a path.
 */
const azureTemplateSteps: StepBuilder = () => [
    {
        body: (
            <>
                <B>Paste what the deployment printed.</B> When Azure finishes, open the deployment's{' '}
                <B>Outputs</B> tab, copy the whole block and paste it into the{' '}
                <B>Deployment outputs</B> box at the top of this cloud's setup to fill these in, or
                type them individually.
            </>
        ),
        fields: ['AZURE_KEYVAULT_URL', 'AZURE_KEYVAULT_KEY'],
        check: <>the vault URL and key name filled in, and saved.</>,
    },
    {
        body: (
            <>
                <B>How this server opens the vault.</B> Not staff sign-in — that is its own card.
                If Pinpoint runs on Azure, grant the vault role to the machine's own identity and
                leave these three empty. Otherwise open <B>Microsoft Entra ID → App registrations →
                New registration</B>: <B>this organizational directory only</B>, and no redirect URI,
                since this app never signs a person in. Add a client secret under{' '}
                <B>Certificates &amp; secrets</B> and copy its <B>Value</B> now.
            </>
        ),
        fields: ['AZURE_TENANT_ID', 'AZURE_KEYVAULT_CLIENT_ID', 'AZURE_KEYVAULT_CLIENT_SECRET', 'AZURE_KEYVAULT_CLIENT_SECRET_EXPIRES'],
        check: <>an Application (client) ID and Directory (tenant) ID on the app's overview, and a copied Value.</>,
        trouble: <>Entra shows the Value once. The box beside it labeled <B>Secret ID</B> is a different thing. On a managed identity all three of these stay empty.</>,
        note: (
            <>
                Entra caps a client secret at 24 months. Put its expiry date in the box and
                Pinpoint warns a month ahead; on a managed identity there is none.
            </>
        ),
    },
    {
        /* Its own step, because it is not an edge case: the template runs
           before this app registration exists, so there is no object id to put
           on the form and the template grants nothing. Every operator who
           follows these steps in order needs this one. It used to be the last
           clause of the note above, conditional on a form field the reader had
           filled in days earlier -- and skipping it produces a vault, a key,
           credentials that all authenticate, and a flat 403 on every wrap, with
           resident data quietly falling back to the application key. */
        body: (
            <>
                <B>Let that identity use the key.</B> Creating the app registration grants it
                nothing. Open the vault → <B>Access control (IAM)</B> → <B>Add role assignment</B>,
                choose <B>Key Vault Crypto User</B>, then on <B>Members</B> pick{' '}
                <B>User, group, or service principal</B> — <em>not</em> Managed identity — and
                search for the app registration <B>by the name you gave it</B>. Pick{' '}
                <B>Managed identity</B> only if you left the three boxes above empty because
                Pinpoint runs on Azure. If this same vault is also Pinpoint's secret store, add{' '}
                <B>Key Vault Secrets Officer</B> the same way.
            </>
        ),
        check: <>that identity on the vault's <B>Role assignments</B> tab as Key Vault Crypto User.</>,
        trouble: (
            <>
                Search by <em>name</em>, not by the Application (client) ID; the client ID returns
                "No results". <B>Entra ID → App registrations</B> lists the name beside the ID.
                <br /><br />
                Without this role, Key Vault returns <C>403 Forbidden</C> and Pinpoint encrypts
                resident data with its own key instead of yours. Press <B>Save &amp; Test</B> on this
                card to confirm. Role assignments can take a moment to apply.
            </>
        ),
    },
];

/**
 * What the template deliberately leaves to a person, offered as a disclosure
 * rather than as steps.
 *
 * These are real hardening and they are not dropped -- but they are not on the
 * path either. A reader who chose the template chose it to stop reading
 * instructions, and numbering "add a Delete lock" as step 5 of 6 rebuilds the
 * manual walk inside the short path. Folded shut, they are there for the town
 * whose policy asks for them and invisible to the town whose policy does not.
 */
export const AZURE_TEMPLATE_EXTRAS = (ctx: StepContext) => (
    <>
        Purge protection and soft delete are already on and can't be turned off. Two optional
        additions: a <B>Delete</B> lock under the vault's <B>Settings → Locks</B>, and an audit
        trail, which needs a diagnostic setting for <C>AuditEvent</C> and logs from the time you
        add it.
        <br /><br />
        Two optional boxes on the form: <B>Allowed IP address</B> limits the vault and the AI
        accounts to one address, so a copied key doesn't work elsewhere. Get the server's with <CopyValue ctx={ctx} id="azip" value="curl -s ifconfig.me" />. <B>Monthly budget</B>{' '}
        emails you at 50%, 80% and 100% of an amount you choose.
    </>
);

defineFork('kms', 'azure', (ctx) => ({
    template: azureTemplateSteps(ctx),
    manual: azureManualSteps(ctx),
}));

const awsManualSteps: StepBuilder = () => [
    {
        body: (
            <>
                In the <L href="https://console.aws.amazon.com/kms">KMS console</L>, set your region,
                choose <B>Customer managed keys</B>, then <B>Create key</B>. Key type <B>Symmetric</B>,
                usage <B>Encrypt and decrypt</B> — both are the defaults. Give it an alias like{' '}
                <C>pinpoint-311-pii</C> and turn on automatic rotation.
            </>
        ),
        check: <>the key under Customer managed keys, status Enabled, your alias beside it.</>,
    },
    {
        body: (
            <>
                The wizard then asks who administers the key and who may use it. Add the identity this
                deployment signs in as under <B>key users</B>. {ATTACHED_IDENTITY} On EC2 or ECS, use
                the instance or task role, which has no long-lived credential.
            </>
        ),
        check: <>your role or user listed as a key user on this key and no other.</>,
        trouble: <>Keep your own administrators in that policy. If a key policy locks out the owning account, it can't be fixed later, even by AWS support.</>,
    },
    {
        body: <>Enter the region and the key ID — the alias works, but the ID is unambiguous.</>,
        fields: ['AWS_REGION', 'AWS_KMS_KEY_ID'],
        note: <>No secret to enter. Pinpoint reaches this key with the identity added above.</>,
    },
    {
        body: (
            <>
                <B>Make deletion deliberate.</B> AWS has no switch for it, so add a statement to the
                key policy that <B>denies</B> <C>kms:ScheduleKeyDeletion</C> and <C>kms:DisableKey</C>{' '}
                to everyone. An explicit deny overrides every allow, including the account root, so
                retiring the key requires removing this statement first.
            </>
        ),
        check: <>a Deny statement naming both actions in the key policy.</>,
        trouble: <>A key stops working when deletion is <em>scheduled</em>, not when the 30 days end. Canceling within the window restores it; after that, the data can't be recovered.</>,
    },
    {
        body: (
            <>
                <B>Decide about the audit trail.</B> CloudTrail records this key being created and its
                policy being changed. It records key <em>use</em> only if a trail carries a data event
                selector for KMS, so add one if your town needs to show who decrypted what.
            </>
        ),
        check: <>a trail with a data event selector naming this key, if your town needs one.</>,
        note: <>Data events are billed per event, and a busy portal decrypts often, so weigh the cost. Logging starts when you add the selector.</>,
    },
    {
        body: <>{ACCOUNT_SURVIVES}</>,
    },
];

const awsTemplateSteps: StepBuilder = () => [
    {
        body: (
            <>
                <B>Paste what the stack printed.</B> When CloudFormation finishes, open the stack's{' '}
                <B>Outputs</B> tab, copy the whole block and paste it into the
                <B> Deployment outputs</B> box at the top of this cloud's setup to fill both in, or
                type them individually.
            </>
        ),
        fields: ['AWS_REGION', 'AWS_KMS_KEY_ID'],
        check: <>the region and key ID filled in, and saved.</>,
        note: <>No secret is needed; the role below handles access.</>,
    },
    {
        body: (
            <>
                <B>Attach the identity the stack created.</B> This is done on the AWS side. On EC2, assign the new <B>instance profile</B> to the instance
                running Pinpoint; on ECS, name the new <B>role</B> as the task role. The application
                picks the identity up from the platform.
            </>
        ),
        check: <>the instance profile on the instance, or the task role on the task definition.</>,
        note: <>Running Pinpoint outside AWS? Create an IAM user and attach the same policy the stack made. This card has no key boxes; it uses the AWS access key entered on any AWS card.</>,
    },
];

/**
 * The AWS equivalent of AZURE_TEMPLATE_EXTRAS, and folded away for the same
 * reason: true, worth having, and not part of getting the key working.
 */
export const AWS_TEMPLATE_EXTRAS = (ctx: StepContext) => (
    <>
        The stack already protects the key: <B>PreventAccidentalKeyDeletion</B> (default{' '}
        <B>Yes</B>) stops everyone, including the account root, from scheduling it for deletion, and{' '}
        <C>DeletionPolicy: Retain</C> keeps the key if the stack is deleted. To log key{' '}
        <em>use</em>, add a KMS data event selector to an existing CloudTrail trail; logging starts
        when you add it.
        <br /><br />
        Two optional boxes on the form: <B>AllowedIpAddress</B> limits Translate, Rekognition,
        Bedrock and Secrets Manager to one address, so a copied role doesn't work elsewhere. Get
        the server's with{' '}
        <CopyValue ctx={ctx} id="awsip" value="curl -s ifconfig.me" />. <B>MonthlyBudgetUsd</B>{' '}
        emails you at 50%, 80% and 100% of an amount you choose.
    </>
);

defineFork('kms', 'aws', (ctx) => ({
    template: awsTemplateSteps(ctx),
    manual: awsManualSteps(ctx),
}));

// ===========================================================================
// Secret storage
//
// These providers collect nothing: the credentials are the ones already entered
// on the PII Encryption card or in Setup. What each needs is a second
// permission on that same identity, and on all three clouds the grant that lets
// Pinpoint use the encryption key grants nothing over secrets. Azure is the
// sharp one -- a vault using Azure roles gives nobody access to its secrets by
// default, including whoever created the vault, which is the same trap that
// stops the key screen working on a brand-new vault.
// ===========================================================================

defineSteps('secrets', 'azure', () => [
    {
        body: (
            <>
                This is the vault from the PII Encryption card, so there is nothing to create and
                nothing to enter — only one more role. On the vault's <B>Access control (IAM)</B>, add{' '}
                <B>Key Vault Secrets Officer</B> for the identity you gave Crypto User there.
            </>
        ),
        check: <>that identity listed twice on the vault's role assignments: Key Vault Crypto User, and Key Vault Secrets Officer.</>,
        trouble: <>Use Officer, not User. Pinpoint writes credentials to this vault, and Secrets User can only read. On the older access policy model, give the identity the secret permissions <B>Get</B>, <B>Set</B>, <B>Delete</B> and <B>Recover</B>.</>,
    },
    {
        body: <>Creating the vault did not give <em>you</em> access to its secrets either.</>,
        note: <>To read these credentials yourself in the portal, grant your own account Key Vault Secrets Officer on the vault as well.</>,
    },
]);

defineSteps('secrets', 'google', () => [
    {
        body: (
            <>
                This uses the service account already entered in Setup, so there is nothing to enter
                below. Enable <C>Secret Manager API</C> on the project, then grant that service
                account <B>Secret Manager Admin</B>:
                <span className="mt-2 block"><C>gcloud projects add-iam-policy-binding YOUR_PROJECT --member=serviceAccount:YOUR_SERVICE_ACCOUNT --role=roles/secretmanager.admin</C></span>
            </>
        ),
        check: <>the service account listed with Secret Manager Admin on the project's IAM page.</>,
        trouble: <>Secret Accessor is not enough. Pinpoint creates and updates secrets here, so it needs Admin.</>,
    },
]);

defineSteps('secrets', 'aws', () => [
    {
        body: (
            <>
                This uses the identity your server already signs in to AWS as, typically the instance
                role, so there is nothing to enter below. Attach a policy allowing{' '}
                <C>secretsmanager:CreateSecret</C>, <C>secretsmanager:PutSecretValue</C>,{' '}
                <C>secretsmanager:GetSecretValue</C>, <C>secretsmanager:DescribeSecret</C>,{' '}
                <C>secretsmanager:DeleteSecret</C> and <C>secretsmanager:ListSecrets</C> in the region
                entered on the other AWS cards.
            </>
        ),
        check: <>those six actions on the role or user's attached policy.</>,
        note: <>Every secret Pinpoint writes is named <C>pinpoint/…</C>, so scope the resource to <C>arn:aws:secretsmanager:REGION:ACCOUNT:secret:pinpoint/*</C>.</>,
    },
]);

// ===========================================================================
// Photo redaction
//
// Three cloud detectors and one that runs here. The steps are short because the
// work is a permission, not a console tour -- and the settings below are what a
// town is actually deciding, which is what to blur.
// ===========================================================================

/**
 * The two warnings every redaction path needs.
 *
 * Redaction is the one capability whose failure is invisible from inside the
 * product. A misconfigured email provider bounces and somebody notices; a
 * detector that finds nothing looks exactly like a photo with nobody in it. The
 * blurring either happened or it did not, and the only way to know is to look
 * at a photo.
 */
const UNCONFIGURED_DETECTOR = (
    <>
        With wrong credentials, the detector finds nothing and photos are stored unblurred while
        this card still shows on. Check the Photo Redaction line on the health dashboard, then run
        the test below.
    </>
);

const VERIFY_WITH_A_PHOTO = (
    <>
        <B>Test it once, with a real photo.</B> File a test report from the resident portal with a
        recognizable face in the picture, then check the stored image in the staff dashboard. Delete
        the test report afterward.
    </>
);

const REDACTION_CHOICE = (
    <>
        Faces and license plates are both blurred by default, since resident photos often include
        bystanders and parked cars.
    </>
);

defineSteps('redaction', 'google', () => [
    {
        body: (
            <>
                In <L href="https://console.cloud.google.com">Google Cloud</L>, open{' '}
                <B>APIs &amp; Services → Library</B> and enable <C>Cloud Vision API</C>. Redaction signs
                in with the service account key entered on the AI Provider card under Vertex AI. Enter
                it there even if AI is off.
            </>
        ),
        check: <>"API Enabled" on the Cloud Vision API page.</>,
        note: <>{UNCONFIGURED_DETECTOR}</>,
    },
    { body: REDACTION_CHOICE, fields: ['REDACT_FACES', 'REDACT_PLATES'], trouble: VERIFY_WITH_A_PHOTO },
]);

defineSteps('redaction', 'aws', () => [
    {
        body: (
            <>
                Amazon Rekognition needs nothing enabled in its console. Add{' '}
                <C>rekognition:DetectFaces</C> and <C>rekognition:DetectText</C> to the IAM user this
                deployment uses — plate detection works by reading text in the image, so without
                DetectText, plates aren't blurred.
            </>
        ),
        check: <>both actions listed on the IAM user's policy.</>,
        note: <>{UNCONFIGURED_DETECTOR}</>,
    },
    { body: REDACTION_CHOICE, fields: ['REDACT_FACES', 'REDACT_PLATES'], trouble: VERIFY_WITH_A_PHOTO },
]);

// Azure is the only redaction backend with credentials of its own. Google and
// AWS reuse what was entered elsewhere. One Azure AI Services account serves
// both Face and Vision, so the same endpoint and key go in both pairs of boxes;
// the template creates exactly that account. Face detection with
// returnFaceId=false, which is all Pinpoint sends, needs no Limited Access
// approval.
//
// Forked like translation, for the same reason: an operator who ran the
// template would otherwise create a second, redundant resource.

const azureRedactionTemplateSteps: StepBuilder = () => [
    {
        body: (
            <>
                <B>Nothing to create.</B> The deployment made the AI Services account that serves
                both faces and plates. If you pasted the outputs, both endpoint boxes are filled.
                Open that account → <B>Resource Management → Keys and Endpoint</B>, copy{' '}
                <B>KEY 1</B>, and paste it into both key boxes.
            </>
        ),
        fields: ['AZURE_FACE_ENDPOINT', 'AZURE_FACE_KEY', 'AZURE_VISION_ENDPOINT', 'AZURE_VISION_KEY'],
        check: <>the same endpoint in both endpoint boxes and the same key in both key boxes.</>,
        note: <>{UNCONFIGURED_DETECTOR}</>,
    },
    { body: REDACTION_CHOICE, fields: ['REDACT_FACES', 'REDACT_PLATES'], trouble: VERIFY_WITH_A_PHOTO },
];

const azureRedactionManualSteps: StepBuilder = () => [
    {
        body: (
            <>
                In the <L href="https://portal.azure.com">Azure portal</L>, create an{' '}
                <B>Azure AI Services</B> multi-service resource. One resource serves faces and
                plates. Open <B>Resource Management → Keys and Endpoint</B>, put its endpoint in
                both endpoint boxes and <B>KEY 1</B> in both key boxes.
            </>
        ),
        fields: ['AZURE_FACE_ENDPOINT', 'AZURE_FACE_KEY', 'AZURE_VISION_ENDPOINT', 'AZURE_VISION_KEY'],
        check: <>the same endpoint in both endpoint boxes and the same key in both key boxes.</>,
        note: (
            <>
                Separate <B>Face</B> and <B>Azure AI Vision</B> (formerly Computer Vision) resources
                also work; each goes in its own pair of boxes. Face detection needs no Limited Access
                approval, because Pinpoint asks only where faces are, not who they are.{' '}
                {UNCONFIGURED_DETECTOR}
            </>
        ),
    },
    { body: REDACTION_CHOICE, fields: ['REDACT_FACES', 'REDACT_PLATES'], trouble: VERIFY_WITH_A_PHOTO },
];

defineFork('redaction', 'azure', (ctx) => ({
    template: azureRedactionTemplateSteps(ctx),
    manual: azureRedactionManualSteps(ctx),
}));

defineSteps('redaction', 'local', () => [
    {
        body: (
            <>
                <B>This is the default.</B> Detection runs on this server using OpenCV, with no account
                or key, and resident photos never leave the server.
            </>
        ),
        note: <>It runs whenever no cloud detector is configured.</>,
    },
    {
        body: (
            <>
                <B>Limits.</B> It detects larger, front-facing faces. It misses small faces, profiles and
                faces in shadow or behind glass more often, and plate detection is weaker. The cloud
                detectors handle these better.
            </>
        ),
        note: <>Without a cloud detector, keep this on <em>and</em> have staff review photos before they are published.</>,
    },
    { body: REDACTION_CHOICE, fields: ['REDACT_FACES', 'REDACT_PLATES'], trouble: VERIFY_WITH_A_PHOTO },
]);
